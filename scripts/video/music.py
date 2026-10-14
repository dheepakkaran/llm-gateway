#!/usr/bin/env python3
"""Original background music for the video, synthesised with numpy (step 2b).

Calm, modern tech-ambient: warm pad chords (Cmaj9 - G6 - Am9 - Fmaj9),
a soft plucked arpeggio from scene 3, a gentle beat during the demo, a
light delay/reverb, then a fade-out. No samples, so no copyright issues.
Usage: music.py <seconds> <out.wav>
"""
import sys
import wave

import numpy as np

SR = 44100
BPM = 92
BEAT = 60 / BPM
BAR = 4 * BEAT
rng = np.random.default_rng(7)

CHORDS = [  # MIDI notes
    [48, 55, 59, 62, 64],   # Cmaj9
    [43, 50, 55, 59, 64],   # G6
    [45, 52, 55, 59, 60],   # Am9
    [41, 48, 52, 55, 57],   # Fmaj9 (add 9 = G on top)
]
ROOTS = [36, 31, 33, 29]


def hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def env(n, a, r):
    e = np.ones(n)
    ai, ri = int(a * SR), int(r * SR)
    e[:ai] = np.linspace(0, 1, ai) ** 2
    e[-ri:] *= np.linspace(1, 0, ri) ** 1.5
    return e


def pad_note(f, dur):
    n = int(dur * SR)
    t = np.arange(n) / SR
    sig = np.zeros(n)
    for det in (-0.06, 0.0, 0.07):           # three detuned voices (cents-ish)
        ff = f * 2 ** (det / 12)
        for k, amp in ((1, 1.0), (2, 0.32), (3, 0.12), (4, 0.05)):
            sig += amp * np.sin(2 * np.pi * ff * k * t + rng.uniform(0, 6.28))
    trem = 1 + 0.06 * np.sin(2 * np.pi * 0.22 * t)
    return sig * trem * env(n, 1.1, 1.4)


def pluck(f, dur=0.9):
    n = int(dur * SR)
    t = np.arange(n) / SR
    s = np.sin(2 * np.pi * f * t) + 0.35 * np.sin(2 * np.pi * 2 * f * t) + 0.1 * np.sin(2 * np.pi * 3 * f * t)
    return s * np.exp(-t * 5.5) * env(n, 0.004, 0.2)


def kick():
    n = int(0.45 * SR)
    t = np.arange(n) / SR
    f = 46 + 70 * np.exp(-t * 28)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 9)


def hat():
    n = int(0.09 * SR)
    t = np.arange(n) / SR
    return rng.standard_normal(n) * np.exp(-t * 60)


def add(buf, sig, at, gain):
    i = int(at * SR)
    j = min(len(buf), i + len(sig))
    if i < len(buf):
        buf[i:j] += gain * sig[: j - i]


def lowpass(x, cutoff):
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    X *= 1 / np.sqrt(1 + (f / cutoff) ** 4)
    return np.fft.irfft(X, len(x))


def highpass(x, cutoff):
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    X *= 1 / np.sqrt(1 + (cutoff / np.maximum(f, 1)) ** 4)
    return np.fft.irfft(X, len(x))


def render(seconds, demo=(32.5, 67.0), arp_from=11.0):
    n = int((seconds + 3) * SR)
    pads, bass, arp, drums = (np.zeros(n) for _ in range(4))
    bars = int(seconds / BAR) + 2
    for b in range(bars):
        t0 = b * BAR
        ch = CHORDS[b % 4]
        for m in ch:
            add(pads, pad_note(hz(m), BAR + 1.2), t0, 0.11)
        add(bass, pad_note(hz(ROOTS[b % 4]), BAR + 0.6), t0, 0.22)
        if t0 >= arp_from - BAR:
            seq = [ch[1] + 12, ch[2] + 12, ch[3] + 12, ch[4] + 12, ch[3] + 12, ch[2] + 12, ch[4] + 12, ch[3] + 24]
            for i, m in enumerate(seq):
                add(arp, pluck(hz(m)), t0 + i * BEAT / 2, 0.08 if t0 < demo[0] else 0.1)
        if demo[0] - BAR <= t0 < demo[1]:
            for beat in range(4):
                if beat in (0, 2):
                    add(drums, kick(), t0 + beat * BEAT, 0.55)
                add(drums, hat(), t0 + beat * BEAT + BEAT / 2, 0.05)
    pads = lowpass(pads, 1800)
    bass = lowpass(bass, 260)
    arp = lowpass(arp, 4200)
    drums = highpass(lowpass(drums, 9000), 35)
    mix = pads + bass + arp + drums
    # stereo: slightly different delays left/right for width, plus a soft reverb tail
    L, R = mix.copy(), mix.copy()
    for d, g in ((0.113, 0.28), (0.197, 0.2), (0.311, 0.14), (0.471, 0.09)):
        k = int(d * SR)
        L[k:] += g * mix[:-k]
        k2 = int((d * 1.13) * SR)
        R[k2:] += g * mix[:-k2]
    st = np.stack([L, R], 1)[: int(seconds * SR)]
    fi, fo = int(1.5 * SR), int(3.5 * SR)
    st[:fi] *= np.linspace(0, 1, fi)[:, None]
    st[-fo:] *= np.linspace(1, 0, fo)[:, None] ** 1.6
    st /= np.max(np.abs(st)) / 0.6        # leaves headroom; background level
    return st


if __name__ == "__main__":
    secs, out = float(sys.argv[1]), sys.argv[2]
    st = render(secs)
    pcm = (np.clip(st, -1, 1) * 32767).astype("<i2")
    with wave.open(out, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    print(f"wrote {out}: {secs:.1f}s")
