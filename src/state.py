"""Persistent state + human-readable log, stored in the repo (data/)."""
import json
import logging
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
STATE_FILE = DATA / "state.json"
LOG_MD = DATA / "VIDEO_LOG.md"
log = logging.getLogger("state")


def now_utc():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"videos": []}


def save(state):
    DATA.mkdir(exist_ok=True)
    state["videos"] = state["videos"][-300:]
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_markdown(state)


def _cell(x):
    return str(x or "").replace("|", "/").replace("\n", " ")[:120]


def _write_markdown(state):
    rows = ["# Video log", "",
            "| Started (UTC) | Slot | Status | Title | YouTube | Publish at | Length | Error |",
            "|---|---|---|---|---|---|---|---|"]
    for v in reversed(state["videos"]):
        url = v.get("url", "")
        rows.append("| {} | {} | {} | {} | {} | {} | {} | {} |".format(
            v.get("started"), v.get("slot"), v.get("status"), _cell(v.get("title")),
            f"[link]({url})" if url else "", v.get("publish_at") or "",
            f'{v.get("duration_sec", "")}s' if v.get("duration_sec") else "", _cell(v.get("error"))))
    LOG_MD.write_text("\n".join(rows) + "\n", encoding="utf-8")


def current_slot(cfg, now=None):
    now = now or now_utc()
    anchor = datetime.fromisoformat(cfg["schedule"]["anchor_utc"].replace("Z", "+00:00"))
    return int((now - anchor) // timedelta(hours=cfg["schedule"]["interval_hours"]))


def decide(cfg, state, force=False):
    """Return the slot to produce, or None if nothing is due."""
    slot = current_slot(cfg)
    recs = [r for r in state["videos"] if r.get("slot") == slot]
    if force:
        return slot
    if any(r["status"] == "uploaded" for r in recs):
        return None
    failures = [r for r in recs if r["status"] in ("failed", "started")]
    if len(failures) >= cfg["schedule"]["max_attempts_per_slot"]:
        return None
    return slot


def mark_stale(state):
    for r in state["videos"]:
        if r["status"] == "started":
            r["status"] = "failed"
            r["error"] = "interrupted (runner timeout/cancel)"


def new_record(slot):
    return {"started": iso(now_utc()), "slot": slot, "status": "started", "stage": "init"}


def git_push(msg):
    """Best-effort commit+push of data/ (only inside GitHub Actions)."""
    if not os.getenv("GITHUB_ACTIONS"):
        return
    for cmd in (["git", "add", "data"], ["git", "commit", "-m", msg],
                ["git", "pull", "--rebase", "--autostash"], ["git", "push"]):
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        if r.returncode and cmd[1] != "commit":
            log.warning("%s -> %s", " ".join(cmd), r.stderr.strip()[:200])
