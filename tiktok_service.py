import asyncio
import logging
import os
import tempfile

from yt_dlp import YoutubeDL

log = logging.getLogger(__name__)

def _fetch_sync(video_url: str, max_count: int) -> list[dict]:
    with tempfile.TemporaryDirectory() as tmp:
        opts = {
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
            "getcomments": True,
            "outtmpl": os.path.join(tmp, "%(id)s.%(ext)s"),
            "extractor_args": {"tiktok": {"max_comments": [str(max_count)]}},
        }
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(video_url, download=False) or {}

    raw = info.get("comments") or []
    out = []
    for c in raw[:max_count]:
        cid = str(c.get("id") or c.get("comment_id") or "")
        if not cid:
            continue
        out.append({
            "id": cid,
            "author": c.get("author") or c.get("user") or "unknown",
            "text": c.get("text") or "",
        })
    return out

async def fetch_comments(video_url: str, max_count: int = 30) -> list[dict]:
    try:
        return await asyncio.to_thread(_fetch_sync, video_url, max_count)
    except Exception as e:
        log.warning("yt-dlp fetch failed for %s: %s", video_url, e)
        return []