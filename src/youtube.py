"""YouTube Data API v3 upload (resumable) with scheduled publishing + thumbnail."""
import logging
import os
import time
from datetime import timedelta

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials

log = logging.getLogger("youtube")
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def _service():
    creds = Credentials(None, refresh_token=os.environ["YT_REFRESH_TOKEN"],
                        token_uri="https://oauth2.googleapis.com/token",
                        client_id=os.environ["YT_CLIENT_ID"], client_secret=os.environ["YT_CLIENT_SECRET"],
                        scopes=SCOPES)
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def publish_at(cfg, now):
    p = cfg["publish"]
    if p["mode"] != "scheduled":
        return None
    t = now.replace(hour=p["hour_utc"], minute=p.get("minute_utc", 0), second=0, microsecond=0)
    if t < now + timedelta(minutes=p.get("min_lead_minutes", 60)):
        t += timedelta(days=1)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def upload(cfg, meta, video_path, thumb_path, when):
    yt = _service()
    desc = meta["description"] + "\n\n" + " ".join(meta["hashtags"]) + "\n\n" + cfg["channel"]["disclosure_text"]
    status = {"selfDeclaredMadeForKids": bool(cfg["youtube"]["made_for_kids"]),
              "containsSyntheticMedia": bool(cfg["youtube"]["contains_synthetic_media"])}
    if when:
        status.update(privacyStatus="private", publishAt=when)
    else:
        status["privacyStatus"] = cfg["publish"]["immediate_privacy"]
    body = {"snippet": {"title": meta["title"], "description": desc[:4900], "tags": meta["tags"],
                        "categoryId": str(cfg["youtube"]["category_id"])},
            "status": status}
    media = MediaFileUpload(video_path, mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp, fails = None, 0
    while resp is None:
        try:
            _, resp = req.next_chunk()
        except HttpError as e:
            if e.resp.status in (500, 502, 503, 504) and fails < 6:
                fails += 1
                time.sleep(2 ** fails)
                continue
            raise
    vid = resp["id"]
    log.info("uploaded video %s", vid)
    if cfg["youtube"]["set_thumbnail"] and thumb_path:
        try:
            yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(thumb_path, mimetype="image/jpeg")).execute()
        except Exception as e:  # noqa: BLE001  (needs a verified channel; never fail the run for this)
            log.warning("thumbnail not set: %s", e)
    return vid
