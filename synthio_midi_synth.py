# synthio_midi_synth.py - pretty usable MIDI-controlled synth using synthio in CircuitPython
# 11 May 2023 - @todbot / Tod Kurt
# Uses cheapie PCM5102 DAC on QTPY RP2040
# Video demo: https://www.youtube.com/watch?v=N-PbbWWDE6k
# Features:
# - midi velocity controls attack rate (gentle press = slow, hard press = fast)
# - notes have small random detune on all oscillators to reduce phase stacking
# - adjustable number of detuned oscillators per note 1-5 (midi controller 83)
# - five selectable waveforms: saw, squ, sin, noisy sin, noise (midi controller 82)
# - vibrato depth on mod wheel (midi controller 1)
#
import time,random
import board, analogio
import audiobusio, audiomixer
import synthio
import ulab.numpy as np

import usb_midi
import adafruit_midi
from adafruit_midi.note_on import NoteOn
from adafruit_midi.note_off import NoteOff
from adafruit_midi.control_change import ControlChange
import neopixel

led = neopixel.NeoPixel(board.NEOPIXEL, 1, brightness=0.2)
midi = adafruit_midi.MIDI(midi_in=usb_midi.ports[0], in_channel=0 )

# qtpy rp2040 SPI pins, be sure PCM5102 SCK is tied to Gnd
lck_pin, bck_pin, dat_pin  = board.MISO, board.MOSI, board.SCK

SAMPLE_RATE = 28000  # clicks @ 36kHz & 48kHz on rp2040
SAMPLE_SIZE = 256    # we like powers of two
VOLUME = 12000       # 16384 is max volume I think
wave_saw = np.linspace(VOLUME, -VOLUME, num=SAMPLE_SIZE, dtype=np.int16)
wave_squ = np.concatenate((np.ones(SAMPLE_SIZE//2, dtype=np.int16)*VOLUME,np.ones(SAMPLE_SIZE//2, dtype=np.int16)*-VOLUME))
wave_sin = np.array(np.sin(np.linspace(0, 4*np.pi, SAMPLE_SIZE, endpoint=False)) * VOLUME, dtype=np.int16)
wave_noise = np.array([random.randint(-VOLUME, VOLUME) for i in range(SAMPLE_SIZE)], dtype=np.int16)
wave_sin_dirty = np.array( wave_sin + (wave_noise/4), dtype=np.int16)
waveforms = (wave_saw, wave_squ, wave_sin, wave_sin_dirty, wave_noise)

synth = synthio.Synthesizer(sample_rate=SAMPLE_RATE)  # note: no envelope or waveform, we do that in Note now!
audio = audiobusio.I2SOut(bit_clock=bck_pin, word_select=lck_pin, data=dat_pin)
mixer = audiomixer.Mixer(voice_count=1, sample_rate=SAMPLE_RATE, channel_count=1,
                         bits_per_sample=16, samples_signed=True, buffer_size=2048 ) # buffer_size=4096 )
audio.play(mixer)           # attach mixer to DAC
mixer.voice[0].play(synth)  # start synth engine playing

wave_i = 0  # which waveform to play
num_oscs = 1  # how many oscillators per note
max_oscs = 5
osc_detune = 0.01 # how much detune (fatness)

notes_pressed = {}  # which notes are currently being pressed, and their note objects (so we can unpress them)
mod_val = 0  # ranges 0-1

def note_on(notenum, vel):
    at_time = max(0, 2 * (127-(vel*1.2)) / 127) # velocity controls attack time
    amp_env = synthio.Envelope(attack_time=at_time, decay_time=0.05, release_time=0.8,
                               attack_level=1, sustain_level=0.8)
    waveform = waveforms[wave_i]
    notes = []
    f = synthio.midi_to_hz(notenum)
    for i in range(num_oscs):
        #  add detuning to oscillators + a bit of random so phases w/ other notes don't perfectly align
        fr = f * (1 + (osc_detune*i) + (random.random()/1000) )
        print("fr:",fr)
        notes.append( synthio.Note( frequency=fr, envelope=amp_env, waveform=waveform,
                                    bend_mode=synthio.BendMode.VIBRATO,
                                    bend_depth = 0.5 * mod_val, bend_rate = 20 * mod_val ) )
    notes_pressed[notenum] = notes
    synth.press(notes)

def note_off(notenum,vel):
    notes = notes_pressed.get(notenum, None)
    if notes:
        synth.release(notes)
        del notes_pressed[notenum]

debug_notes = False

print("synthio_midi_synth ready")
while True:
    msg = midi.receive()
    if isinstance(msg, NoteOn) and msg.velocity != 0:
        print("noteOn: ", msg.note, "vel=", msg.velocity)
        led.fill(0xff00ff)
        note_on( msg.note, msg.velocity)
        if debug_notes: print("notes_pressed:", notes_pressed)
    elif isinstance(msg,NoteOff) or isinstance(msg,NoteOn) and msg.velocity==0:
        print("noteOff:", msg.note, "vel=", msg.velocity)
        led.fill(0x00000)
        note_off( msg.note, msg.velocity)
        if debug_notes: print("notes_pressed:", notes_pressed)
    elif isinstance(msg,ControlChange):
        print("controlChange", msg.control, "=", msg.value)
        if msg.control == 1: # mod wheel
            mod_val = msg.value / 127
            for notes in notes_pressed.values():
                for n in notes:  # adjust vibrato depth & rate for all notes
                    n.bend_depth = 0.5 * mod_val
                    n.bend_rate = 20 * mod_val
        elif msg.control == 82:  # leftmost slider on minilab3
            num_oscs = int( 1 + (msg.value/127) * max_oscs )
            print("num_oscs:",num_oscs)
        elif msg.control == 83:  # leftmost+1 slider on minilab3
            wave_i = int( (msg.value/127) * (len(waveforms)-1) )
            print("wave_i:",wave_i)

