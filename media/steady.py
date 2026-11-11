"""Measure how words move between frames in a stretch of video, to a fraction of a pixel.
Read only; needs numpy and ffmpeg. Usage: python media/steady.py <video> <t0> <t1> <x:y:w:h> [label]
It tracks one patch of the picture (a block of text). For each pair of neighbouring frames it finds how far the
patch moved up/down and left/right (FFT cross-correlation of the row and column profiles, refined to 1/50 px).
A still shot gives 0. A smooth glide gives a steady small number. A shiver gives steps that jump back and forth.
Prints: total travel, the largest single-frame jump, and the SHIVER = how far the position strays from a smooth path."""
import subprocess
import sys

import numpy as np

video, t0, t1, crop = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), sys.argv[4]
label = sys.argv[5] if len(sys.argv) > 5 else ""
x, y, w, h = (int(v) for v in crop.split(":"))
cmd = ["ffmpeg", "-v", "error", "-ss", f"{t0}", "-t", f"{t1 - t0}", "-i", video,
       "-vf", f"crop={w}:{h}:{x}:{y},format=gray", "-f", "rawvideo", "-"]
raw = subprocess.run(cmd, capture_output=True).stdout
n = len(raw) // (w * h)
fr = np.frombuffer(raw[: n * w * h], dtype=np.uint8).reshape(n, h, w).astype(np.float64)

UP = 50


def shift_1d(a, b):
    """How far profile b is shifted against profile a, in samples (positive = b moved toward larger index)."""
    a = a - a.mean()
    b = b - b.mean()
    m = len(a)
    win = np.hanning(m)
    A, Bf = np.fft.rfft(a * win), np.fft.rfft(b * win)
    cross = np.conj(A) * Bf
    big = np.zeros(m * UP // 2 + 1, dtype=complex)
    big[: len(cross)] = cross
    cc = np.fft.irfft(big, m * UP)
    lim = 6 * UP                                   # look within +/- 6 px
    cand = np.concatenate([cc[:lim], cc[-lim:]])
    k = int(np.argmax(cand))
    return (k if k < lim else k - 2 * lim) / UP


dys, dxs = [], []
for i in range(1, n):
    a, b = 255 - fr[i - 1], 255 - fr[i]
    dys.append(shift_1d(a.mean(axis=1), b.mean(axis=1)))
    dxs.append(shift_1d(a.mean(axis=0), b.mean(axis=0)))
dys, dxs = np.array(dys), np.array(dxs)


def report(name, d):
    pos = np.concatenate([[0.0], np.cumsum(d)])
    t = np.arange(len(pos))
    fit = np.polyval(np.polyfit(t, pos, 3), t)      # a smooth path (still, steady or easing)
    res = pos - fit
    back = int(np.sum(np.sign(d[1:]) * np.sign(d[:-1]) < 0))   # times the motion reverses direction
    print("  %-10s travel %+7.2f px | biggest one-frame jump %.2f px | SHIVER rms %.3f px, peak-to-peak %.2f px | reverses %d times in %d frames"
          % (name, pos[-1], np.abs(d).max(), res.std(), res.max() - res.min(), back, len(d)))


print("%s  %.1f-%.1f s  patch %s  (%d frames)" % (label, t0, t1, crop, n))
report("up/down", dys)
report("left/right", dxs)
print("  first 24 up/down steps:", " ".join("%+.2f" % v for v in dys[:24]))
