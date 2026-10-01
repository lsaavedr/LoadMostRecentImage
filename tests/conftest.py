import sys
from pathlib import Path

import pytest

# `comfy_api` ships with ComfyUI, not PyPI. The stub lets tests import the
# package root (which does `from comfy_api.latest import ...`).
sys.path.insert(0, str(Path(__file__).parent / "stubs"))


@pytest.fixture(autouse=True)
def isolated_state_dir(tmp_path, monkeypatch):
    """Redirect the plugin's persistent-state dir into a tmp dir for every test.

    Without this, tests that touch HistoryState would read/write the real
    /root/.cache/comfyui_load_most_recent_image directory.
    """
    import utils.state as state_mod

    state_dir = tmp_path / "state"
    monkeypatch.setattr(state_mod, "STATE_DIR", state_dir)
    return state_dir
