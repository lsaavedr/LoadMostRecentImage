import pytest

import utils.state as state_mod


@pytest.fixture(autouse=True)
def isolated_state_dir(tmp_path, monkeypatch):
    """Redirect the plugin's persistent-state dir into a tmp dir for every test.

    Without this, tests that touch HistoryState would read and write the real
    state directory under the user's home.
    """
    state_dir = tmp_path / "state"
    monkeypatch.setattr(state_mod, "STATE_DIR", state_dir)
    return state_dir
