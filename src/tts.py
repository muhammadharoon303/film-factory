"""Narration + dialogue with Piper (open-source neural TTS, runs on CPU). Builds per-scene audio, cues, SRT."""
import logging
import re
import subprocess
import sys
import wave
from pathlib import Path

import requests

from .utils import retry

log = logging.getLogger("tts")
SR = 44100
CACHE = Path.home() / ".cache" / "piper-voices"


def _fetch_voice(voice_id):
    m = re.match(r"^([a-z]{2,3})_([A-Z]{2})-(.+)-([a-z_]+)$", voice_id)
    if not m:
        raise ValueError(f"bad Piper voice id: {voice_id}")
    lang, region, name, quality = m.groups()
    base = f"https://huggingface.co/rhasspy/piper-voices/resolve/main/{lang}/{lang}_{region}/{name}/{quality}/{voice_id}"
    CACHE.mkdir(parents=True, exist_ok=True)
    onnx = CACHE / f"{voice_id}.onnx"
    for suffix, dest in ((".onnx", onnx), (".onnx.json", CACHE / f"{voice_id}.onnx.json")):
        if not dest.exists():
            r = requests.get(base + suffix, timeout=300)
            r.raise_for_status()
            dest.write_bytes(r.content)
    return str(onnx)


def _clean(text):
    text = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", text)
    text = re.sub(r"[*_#~`\"“”]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _say(model, text, out, length_scale):
    raw = Path(str(out) + ".raw.wav")
    subprocess.run([sys.executable, "-m", "piper", "--model", model, "--output_file", str(raw),
                    "--length_scale", str(length_scale)], input=text.encode("utf-8"),
                   check=True, capture_output=True, timeout=300)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-ar", str(SR), "-ac", "1",
                    "-sample_fmt", "s16", str(out)], check=True)
    raw.unlink(missing_ok=True)


def _pcm(path):
    with wave.open(str(path), "rb") as w:
        return w.readframes(w.getnframes())


def _silence(sec):
    return b"\x00\x00" * int(sec * SR)


def _write(path, pcm):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm)


def synthesize(cfg, film, work):
    v = cfg["voices"]
    narrator = _fetch_voice(v["narrator"])
    chars = [_fetch_voice(x) for x in v["characters"]] or [narrator]
    voice_of = {"NARRATOR": narrator}
    for i, c in enumerate(film["concept"]["characters"]):
        voice_of[c["name"]] = chars[i % len(chars)]
    tmp = Path(work) / "lines"
    tmp.mkdir(exist_ok=True)
    for si, scene in enumerate(film["scenes"]):
        pcm, t, cues, prev_sp = _silence(0.4), 0.4, [], None
        for li, line in enumerate(scene["lines"]):
            text = _clean(line["text"])
            if not text:
                continue
            out = tmp / f"s{si}_l{li}.wav"
            try:
                retry(lambda: _say(voice_of[line["speaker"]], text, out, v["length_scale"]),
                      attempts=2, delay=2, what=f"tts s{si}l{li}")
            except Exception as e:  # noqa: BLE001
                log.warning("skipping line: %s", e)
                continue
            data = _pcm(out)
            dur = len(data) / 2 / SR
            gap = 0.3 if line["speaker"] == prev_sp else 0.5
            cues.append({"start": t, "end": t + dur, "speaker": line["speaker"], "text": text})
            pcm += data + _silence(gap)
            t += dur + gap
            prev_sp = line["speaker"]
        pcm += _silence(0.5)
        scene["wav"] = str(Path(work) / f"scene{si}.wav")
        scene["cues"] = cues
        _write(scene["wav"], pcm)
        scene["duration"] = len(pcm) / 2 / SR
    film["scenes"] = [s for s in film["scenes"] if s["cues"]]


def cap_duration(cfg, film):
    """Drop middle scenes until total length <= max (keeps opening and ending)."""
    mx = cfg["film"]["max_duration_sec"]
    total = lambda: sum(s["duration"] for s in film["scenes"])  # noqa: E731
    while total() > mx and len(film["scenes"]) > 2:
        removed = film["scenes"].pop(len(film["scenes"]) // 2)
        log.warning("over max duration, dropped scene: %s", removed["summary"][:60])
    return total()


def _ts(sec):
    ms = int(round(sec * 1000))
    return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"


def _chunks(text, max_words=9):
    out, cur = [], []
    for w in text.split():
        cur.append(w)
        if len(cur) >= max_words or (len(cur) >= 3 and w[-1] in ".!?;:"):
            out.append(" ".join(cur))
            cur = []
    if cur:
        out.append(" ".join(cur))
    return out


def build_track(film, work):
    """Concatenate scene audio -> voice.wav and write subs.srt. Returns (voice_wav, srt_path)."""
    pcm, offset, idx, srt = b"", 0.0, 1, []
    for scene in film["scenes"]:
        data = _pcm(scene["wav"])
        for cue in scene["cues"]:
            parts = _chunks(cue["text"])
            total_chars = sum(len(p) for p in parts) or 1
            t = cue["start"]
            for p in parts:
                d = (cue["end"] - cue["start"]) * len(p) / total_chars
                srt.append(f"{idx}\n{_ts(offset + t)} --> {_ts(offset + t + d)}\n{p}\n")
                idx += 1
                t += d
        scene["offset"] = offset
        offset += len(data) / 2 / SR
        pcm += data
    voice, srt_path = Path(work) / "voice.wav", Path(work) / "subs.srt"
    _write(voice, pcm)
    srt_path.write_text("\n".join(srt), encoding="utf-8")
    return str(voice), str(srt_path), offset
