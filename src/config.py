import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_config(path=None):
    p = Path(path or os.getenv("FILM_CONFIG") or ROOT / "config.yaml")
    cfg = yaml.safe_load(p.read_text(encoding="utf-8"))
    f = cfg["film"]
    f["max_duration_sec"] = min(int(f["max_duration_sec"]), 600)          # YouTube-film hard cap
    f["target_duration_sec"] = min(int(f["target_duration_sec"]), f["max_duration_sec"] - 30)
    cfg["schedule"]["interval_hours"] = max(1, int(cfg["schedule"]["interval_hours"]))
    return cfg
