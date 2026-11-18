"""Tiny file cache with time-to-live. Saves repeat downloads and tokens."""
import hashlib
import json
import re
import time

from .config import CACHE_DIR

# Bump when the shape of cached data changes, so old files are ignored.
VERSION = 6

# Seconds each kind of data stays fresh.
TTL = {
    "quote": 15 * 60,
    "history": 12 * 3600,
    "profile": 7 * 86400,
    "financials": 7 * 86400,
    "filings": 86400,
    "macro": 12 * 3600,
    "sec_map": 30 * 86400,
    "facts": 7 * 86400,
    "story": 30 * 86400,
    "news": 3600,
}


def path_for(kind, key, ext="json"):
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", key)[:60]
    digest = hashlib.sha1(key.encode()).hexdigest()[:8]
    folder = CACHE_DIR / f"v{VERSION}" / kind
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{safe}-{digest}.{ext}"


def fresh(path, kind):
    return path.exists() and (time.time() - path.stat().st_mtime) < TTL[kind]


def get_json(kind, key):
    p = path_for(kind, key)
    if fresh(p, kind):
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            return None
    return None


def put_json(kind, key, data):
    path_for(kind, key).write_text(json.dumps(data, default=str), encoding="utf-8")
    return data
