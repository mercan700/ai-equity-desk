"""Settings and paths. Everything lives in the user's home folder, never in the repo."""
import json
import os
from pathlib import Path

_NEW, _OLD = Path.home() / ".stock-trader-skills", Path.home() / ".ai-equity-desk"
HOME = Path(os.environ.get("DESK_HOME", _OLD if _OLD.exists() and not _NEW.exists() else _NEW))
CACHE_DIR = HOME / "cache"
CONFIG_FILE = HOME / "config.json"

DEFAULTS = {
    # SEC asks every client to identify itself: "Name contact@email".
    "sec_user_agent": "",
    "default_market": "US",
}


def load():
    cfg = dict(DEFAULTS)
    if CONFIG_FILE.exists():
        try:
            cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
    env_ua = os.environ.get("DESK_SEC_USER_AGENT")
    if env_ua:
        cfg["sec_user_agent"] = env_ua
    return cfg


def save(updates):
    HOME.mkdir(parents=True, exist_ok=True)
    cfg = load()
    cfg.update(updates)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return cfg
