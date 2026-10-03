"""Original background music synthesized procedurally with numpy (no samples, no copyright)."""
import hashlib
import wave

import numpy as np

SR = 44100
MOODS = {  # scale (semitones), root midi note, bpm
    "dark": ([0, 2, 3, 5, 7, 8, 10], 40, 52),
    "calm": ([0, 2, 4, 7, 9, 12, 14], 48, 58),
    "tense": ([0, 1, 3, 5, 7, 8, 10], 38, 66),
    "hopeful": ([0, 2, 4, 5, 7, 9, 11], 48, 64),
    "epic": ([0, 2, 3, 5, 7, 8, 11], 41, 72),
    "mysterious": ([0, 2, 3, 6, 7, 8, 11], 43, 56),
    "playful": ([0, 2, 4, 7, 9, 12, 14], 55, 84),
}


def _f(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def _tone(freq, length, attack, release, harmonics=(1.0, 0.45, 0.2)):
    t = np.arange(int(length * SR)) / SR
    sig = sum(a * (np.sin(2 * np.pi * freq * (k + 1) * t) + np.sin(2 * np.pi * freq * 1.004 * (k + 1) * t))
              for k, a in enumerate(harmonics))
    env = np.clip(np.minimum(t / attack, (length - t) / release), 0, 1)
    return (sig * env).astype(np.float32)


def _pluck(freq, length=2.5):
    t = np.arange(int(length * SR)) / SR
    return (np.exp(-t * 3.2) * (np.sin(2 * np.pi * freq * t) + 0.3 * np.sin(2 * np.pi * 2 * freq * t))).astype(np.float32)


def _add(buf, sig, start, gain, pan):
    end = min(len(buf), start + len(sig))
    if end <= start:
        return
    seg = sig[: end - start] * gain
    buf[start:end, 0] += seg * (1 - pan)
    buf[start:end, 1] += seg * pan


def synth(duration, mood, seed_text, out_path):
    scale, root, bpm = MOODS.get(mood, MOODS["mysterious"])
    rng = np.random.default_rng(int(hashlib.sha256(seed_text.encode()).hexdigest()[:8], 16))
    beat = 60 / bpm
    chord_len = beat * 8
    n = int(duration / chord_len) + 2
    buf = np.zeros((int((n * chord_len + 5) * SR), 2), dtype=np.float32)
    prog = [int(x) for x in rng.choice([0, 3, 4, 5, 2, 6], 4, replace=False)]
    for ci in range(n):
        start = int(ci * chord_len * SR)
        d = prog[ci % 4]
        notes = [root + 12 + scale[(d + k) % 7] + 12 * ((d + k) // 7) for k in (0, 2, 4)]
        for m in notes:
            _add(buf, _tone(_f(m), chord_len + 3, 2.0, 3.0), start, 0.07, float(rng.uniform(0.3, 0.7)))
        _add(buf, _tone(_f(root + scale[d] - 12), chord_len + 3, 1.5, 3.0, (1.0, 0.2)), start, 0.18, 0.5)
        for b in range(8):
            if rng.random() < 0.45:
                m = root + 24 + scale[int(rng.integers(0, 7))]
                _add(buf, _pluck(_f(m)), start + int(b * beat * SR), 0.05, float(rng.uniform(0.2, 0.8)))
    buf = buf[: int(duration * SR)]
    buf /= max(1e-6, np.abs(buf).max()) / 0.8
    fi, fo = int(3 * SR), int(4 * SR)
    buf[:fi] *= np.linspace(0, 1, fi)[:, None]
    buf[-fo:] *= np.linspace(1, 0, fo)[:, None]
    with wave.open(str(out_path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((buf * 32767).astype("<i2").tobytes())
    return str(out_path)


def pick_mood(cfg, film):
    m = cfg["music"]["mood"]
    return film["concept"].get("music_mood", "mysterious") if m == "auto" else m
