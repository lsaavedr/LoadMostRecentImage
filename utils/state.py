import json
from pathlib import Path

STATE_DIR = Path("/root/.cache/comfyui_load_most_recent_image")
STATE_DIR.mkdir(parents=True, exist_ok=True)


def state_path(key):
    return STATE_DIR / f"{key}.json"


def load_persistent_state(key):
    try:
        p = state_path(key)
        if p.exists():
            with p.open("r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {"history": [], "last_fb_sig": None, "global_counter": 0}


def save_persistent_state(key, state):
    try:
        p = state_path(key)
        tmp = p.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(state, f)
        tmp.replace(p)
    except Exception:
        pass
