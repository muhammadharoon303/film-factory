"""ffmpeg assembly: Ken-Burns shots with fade transitions -> concat -> mix voice+music -> burn subtitles."""
import logging
import subprocess
from pathlib import Path

log = logging.getLogger("render")


def _run(cmd, cwd):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError("ffmpeg failed: " + r.stderr[-800:])


def _motion(i, n):
    c = "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
    return [f"z='1.0+0.15*on/{n}':{c}",
            f"z='1.15-0.15*on/{n}':{c}",
            f"z='1.12':x='(iw-iw/zoom)*on/{n}':y='(ih-ih/zoom)/2'",
            f"z='1.12':x='(iw-iw/zoom)*(1-on/{n})':y='(ih-ih/zoom)/2'"][i % 4]


def render(cfg, film, voice_wav, music_wav, srt, total_sec, work):
    r = cfg["render"]
    W, H, fps, fade = r["width"], r["height"], r["fps"], r["fade_sec"]
    work = str(Path(work).resolve())
    clips, t, prev_frame, k = [], 0.0, 0, 0
    for scene in film["scenes"]:
        per = scene["duration"] / len(scene["shots"])
        for shot in scene["shots"]:
            t += per
            end_frame = round(t * fps)                 # cumulative rounding => zero drift vs audio
            n = max(2, end_frame - prev_frame)
            prev_frame = end_frame
            dur = n / fps
            clip = f"clip_{k:03}.mp4"
            vf = (f"scale=1920:1080:flags=lanczos,zoompan={_motion(k, n)}:d={n}:s={W}x{H}:fps={fps},"
                  f"fade=t=in:st=0:d={fade},fade=t=out:st={max(0, dur - fade):.3f}:d={fade},format=yuv420p")
            _run(["ffmpeg", "-y", "-loglevel", "error", "-i", shot["image"], "-vf", vf, "-frames:v", str(n),
                  "-r", str(fps), "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", clip], work)
            clips.append(clip)
            k += 1
            log.info("clip %d/%d", k, sum(len(s["shots"]) for s in film["scenes"]))
    Path(work, "list.txt").write_text("".join(f"file '{c}'\n" for c in clips))
    _run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", "list.txt",
          "-c", "copy", "silent.mp4"], work)

    inputs = ["-i", "silent.mp4", "-i", voice_wav]
    if cfg["music"]["enabled"] and music_wav:
        inputs += ["-i", music_wav]
        fc = (f"[2:a]volume={cfg['music']['volume']}[m];"
              "[1:a][m]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[mix];"
              "[mix]loudnorm=I=-16:TP=-1.5:LRA=11[a]")
    else:
        fc = "[1:a]loudnorm=I=-16:TP=-1.5:LRA=11[a]"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", fc]
    if r["subtitles"]:
        style = (f"FontName={r['subtitle_font']},FontSize={r['subtitle_size']},PrimaryColour=&H00FFFFFF,"
                 "OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=0,MarginV=24,Alignment=2")
        cmd += ["-vf", f"subtitles={Path(srt).name}:force_style='{style}'"]
    cmd += ["-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
            "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "-shortest", "final.mp4"]
    _run(cmd, work)
    return str(Path(work) / "final.mp4")
