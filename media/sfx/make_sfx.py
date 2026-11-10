"""The two sound effects of the demo video, made from sine waves here and nowhere else.

  python media/sfx/make_sfx.py        # writes media/sfx/ding.wav and media/sfx/tap.wav (48 kHz, 16-bit, mono)

Standard library only. No sampled, downloaded or generated-by-a-model audio: every sample is computed below,
so running this again writes the same two files, byte for byte. What each is, and why, is in SOURCE.md.
"""
import math
import struct
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
RATE = 48000


def write(name, samples, peak_db):
    """Scale so the loudest sample sits at peak_db (dB below full scale) and write a 16-bit mono WAV."""
    top = max(abs(s) for s in samples)
    gain = 10 ** (peak_db / 20) / top
    with wave.open(str(HERE / name), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"".join(struct.pack("<h", int(round(s * gain * 32767))) for s in samples))
    print(f"{name}: {len(samples) / RATE * 1000:.0f} ms, peak {peak_db} dBFS")


def ding():
    """A small struck bell, the "ding" of a shop till: the pitches a struck metal bar rings at (1 : 2.76 : 5.40
    times the lowest), a quieter note an octave under them for body, each dying away on its own, the high
    ones fastest. 3 ms attack, gone in about 0.6 s."""
    f0 = 1760.0                                        # A6
    # (frequency, loudness, seconds to fall by 60 dB)
    partials = [(f0 / 2, 0.16, 0.60), (f0, 1.00, 0.60), (f0 * 2.756, 0.40, 0.38), (f0 * 5.404, 0.10, 0.20)]
    n = int(0.75 * RATE)
    out = []
    for i in range(n):
        t = i / RATE
        s = sum(a * math.exp(-6.908 * t / t60) * math.sin(2 * math.pi * f * t) for f, a, t60 in partials)
        attack = 0.5 - 0.5 * math.cos(math.pi * min(1.0, t / 0.003))
        tail = min(1.0, (n - i) / (0.02 * RATE))       # the last 20 ms eased to silence
        out.append(s * attack * tail)
    return out


def tap():
    """A soft key press, like a phone's keyboard: a low thump (190 Hz) under a short click (1.4 kHz and
    3.1 kHz), all over in 80 ms. 1 ms attack."""
    parts = [(190.0, 0.60, 0.018), (1400.0, 0.50, 0.008), (3100.0, 0.20, 0.004)]   # (frequency, loudness, time constant in seconds)
    n = int(0.080 * RATE)
    out = []
    for i in range(n):
        t = i / RATE
        s = sum(a * math.exp(-t / tau) * math.sin(2 * math.pi * f * t) for f, a, tau in parts)
        attack = 0.5 - 0.5 * math.cos(math.pi * min(1.0, t / 0.001))
        tail = min(1.0, (n - i) / (0.010 * RATE))
        out.append(s * attack * tail)
    return out


if __name__ == "__main__":
    write("ding.wav", ding(), -14.0)                   # peaks 14 dB under full scale: about 10 dB under the voice's peaks
    write("tap.wav", tap(), -16.0)
