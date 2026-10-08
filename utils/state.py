import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

APP_STATE_DIR = "comfyui_load_most_recent_image"


def _default_state_dir() -> Path:
    """Resolve where to persist state, most specific source first.

    1. ``LMRI_STATE_DIR`` -- explicit override for tests and odd setups.
    2. ``$XDG_STATE_HOME/<app>`` -- the XDG home for data that persists
       between runs (distinct from ``$XDG_CACHE_HOME``, which is disposable).
    3. ``~/.local/state/<app>`` -- the XDG default.

    The per-app subdirectory keeps this node from colliding with any other
    tool that respects the XDG spec.
    """
    override = os.environ.get("LMRI_STATE_DIR")
    if override:
        return Path(override).expanduser()

    root = os.environ.get("XDG_STATE_HOME") or "~/.local/state"
    return Path(root).expanduser() / APP_STATE_DIR


STATE_DIR = _default_state_dir()


def state_path(key):
    return STATE_DIR / f"{key}.json"


def load_persistent_state(key):
    try:
        p = state_path(key)
        if p.exists():
            with p.open("r", encoding="utf-8") as f:
                return json.load(f)
    except (OSError, ValueError, KeyError) as exc:
        logger.warning("load_persistent_state failed for %s: %s", key, exc)
    return {"history": [], "last_fb_sig": None}


def clear_persistent_states() -> bool:
    """Delete every persisted state file (called when the UI reloads).

    Also sweeps `*.tmp`: `save_persistent_state` stages into one before
    renaming, so a write interrupted mid-dump leaves a partial file behind.

    Returns whether the sweep actually finished. A caller cannot otherwise tell
    a reset from a failed one, and the caller here is an HTTP route whose only
    other signal is the widget moving back to 1 regardless.
    """
    try:
        for pattern in ("*.json", "*.tmp"):
            for p in STATE_DIR.glob(pattern):
                p.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("clear_persistent_states failed: %s", exc)
        return False
    return True


def save_persistent_state(key, state):
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        p = state_path(key)
        tmp = p.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(state, f)
        tmp.replace(p)
    except (OSError, TypeError, ValueError) as exc:
        logger.warning("save_persistent_state failed for %s: %s", key, exc)
