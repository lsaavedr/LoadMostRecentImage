import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

STATE_DIR = Path(
    os.environ.get("LMRI_STATE_DIR", "/root/.cache/comfyui_load_most_recent_image")
)


def state_path(key):
    return STATE_DIR / f"{key}.json"


def load_persistent_state(key):
    try:
        p = state_path(key)
        if p.exists():
            with p.open("r", encoding="utf-8") as f:
                return json.load(f)
    except (OSError, ValueError, KeyError) as exc:
        logger.debug("load_persistent_state failed for %s: %s", key, exc)
    return {"history": [], "last_fb_sig": None, "global_counter": 0}


def save_persistent_state(key, state):
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        p = state_path(key)
        tmp = p.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(state, f)
        tmp.replace(p)
    except (OSError, TypeError, ValueError) as exc:
        logger.debug("save_persistent_state failed for %s: %s", key, exc)
