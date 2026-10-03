"""Orchestrator. `python -m src.main --check` = is a film due?   `python -m src.main` = make + upload one film."""
import argparse
import logging
import os
import sys
import traceback
from pathlib import Path

from . import state as st
from .config import ROOT, load_config
from .utils import retry

log = logging.getLogger("main")


def pipeline(cfg, state, rec, work):
    from . import images, llm, music, render, story, tts, youtube

    def stage(name):
        rec["stage"] = name
        st.save(state)
        log.info("=== stage: %s", name)

    prev = [v["title"] for v in state["videos"] if v.get("title")][-30:]
    stage("story")
    film = retry(lambda: story.build_film(cfg, prev), attempts=2, delay=10, what="story")
    meta = story.build_metadata(cfg, film)
    rec["title"] = meta["title"]
    llm.unload()

    stage("voice")
    tts.synthesize(cfg, film, work)
    tts.cap_duration(cfg, film)
    voice, srt, total = tts.build_track(film, work)
    rec["duration_sec"] = round(total)
    log.info("film length %.0fs, %d scenes", total, len(film["scenes"]))

    stage("images")
    images.generate_shots(cfg, film, work)
    thumb = images.make_thumbnail(cfg, film, meta, work)
    images.unload()

    stage("music")
    mus = music.synth(total + 2, music.pick_mood(cfg, film), meta["title"], Path(work) / "music.wav") \
        if cfg["music"]["enabled"] else None

    stage("render")
    mp4 = render.render(cfg, film, voice, mus, srt, total, work)

    stage("upload")
    when = youtube.publish_at(cfg, st.now_utc())
    vid = retry(lambda: youtube.upload(cfg, meta, mp4, thumb, when),
                attempts=cfg["retry"]["upload_attempts"], delay=20, what="upload")
    rec.update(status="uploaded", youtube_id=vid, url=f"https://youtu.be/{vid}", publish_at=when, stage="done")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--config")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config(args.config)
    state = st.load()
    slot = st.decide(cfg, state, force=os.getenv("FORCE") == "1")

    if args.check:
        due = slot is not None
        print(f"slot={st.current_slot(cfg)} due={due}")
        if os.getenv("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a") as f:
                f.write(f"due={'true' if due else 'false'}\n")
        return 0
    if slot is None:
        print("nothing due")
        return 0

    st.mark_stale(state)
    rec = st.new_record(slot)
    state["videos"].append(rec)
    st.save(state)
    st.git_push("film-factory: attempt started [skip ci]")     # counted even if the runner dies hard

    work = ROOT / "output" / f"slot{slot}_{rec['started'].replace(':', '')}"
    work.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(work / "run.log")
    logging.getLogger().addHandler(fh)
    try:
        pipeline(cfg, state, rec, work)
        code = 0
    except Exception as e:  # noqa: BLE001
        log.error("RUN FAILED at stage %s: %s\n%s", rec.get("stage"), e, traceback.format_exc())
        rec.update(status="failed", error=f"[{rec.get('stage')}] {e}"[:300])
        code = 1
    st.save(state)
    summ = os.getenv("GITHUB_STEP_SUMMARY")
    if summ:
        Path(summ).write_text(f"**{rec['status']}** - {rec.get('title', '')} {rec.get('url', '')} {rec.get('error', '')}\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
