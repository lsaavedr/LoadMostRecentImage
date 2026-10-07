import importlib
import json

import pytest

import utils.state as state_mod
from utils.state import load_persistent_state, save_persistent_state, state_path


def test_state_path_uses_state_dir(isolated_state_dir):
    p = state_path("abc")
    assert p.parent == isolated_state_dir
    assert p.name == "abc.json"


# --- STATE_DIR resolution ------------------------------------------------
#
# Pins the precedence between LMRI_STATE_DIR, XDG_STATE_HOME and the XDG
# default, plus the guarantee that the resolved path is actually usable.


@pytest.fixture()
def xdg_env(monkeypatch, tmp_path):
    """Controlled HOME/XDG_STATE_HOME with no override set."""
    monkeypatch.delenv("LMRI_STATE_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    return tmp_path


def test_state_dir_falls_back_to_xdg_default(xdg_env):
    importlib.reload(state_mod)

    assert state_mod.STATE_DIR == xdg_env / ".local" / "state" / state_mod.APP_STATE_DIR
    assert state_mod.STATE_DIR.is_absolute()


def test_state_dir_honours_xdg_state_home(tmp_path, monkeypatch):
    monkeypatch.delenv("LMRI_STATE_DIR", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    importlib.reload(state_mod)

    assert state_mod.STATE_DIR == tmp_path / "xdg" / state_mod.APP_STATE_DIR


def test_state_dir_override_beats_xdg_state_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("LMRI_STATE_DIR", str(tmp_path / "override"))
    importlib.reload(state_mod)

    assert state_mod.STATE_DIR == tmp_path / "override"


def test_state_dir_expands_tilde_in_override(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("LMRI_STATE_DIR", "~/custom/state")
    importlib.reload(state_mod)

    assert state_mod.STATE_DIR == tmp_path / "custom" / "state"


def test_state_dir_never_leaves_a_literal_tilde(xdg_env):
    """`Path("~/x")` is *relative*: without expanduser() it writes to the cwd."""
    importlib.reload(state_mod)

    assert "~" not in state_mod.STATE_DIR.parts


def test_state_dir_default_actually_persists(xdg_env):
    """End to end: with a real HOME the default path must actually save."""
    importlib.reload(state_mod)

    save_persistent_state("k", {"history": ["a"]})

    expected = xdg_env / ".local" / "state" / state_mod.APP_STATE_DIR / "k.json"
    assert expected.exists(), "default STATE_DIR is not writable for this user"


def test_load_nonexistent_returns_default(isolated_state_dir):
    assert load_persistent_state("nope") == {
        "history": [],
        "last_fb_sig": None,
        "global_counter": 0,
    }


def test_save_then_load_roundtrip(isolated_state_dir):
    data = {"history": ["a"], "last_fb_sig": "s", "global_counter": 5}
    save_persistent_state("key", data)
    assert load_persistent_state("key") == data


def test_save_creates_state_dir_when_missing(isolated_state_dir):
    """STATE_DIR is created lazily by save, not at import time."""
    assert not isolated_state_dir.exists()
    save_persistent_state("key", {"history": []})
    assert isolated_state_dir.is_dir()
    assert (isolated_state_dir / "key.json").exists()


def test_save_is_atomic_no_tmp_left_behind(isolated_state_dir):
    save_persistent_state("key", {"history": []})
    assert list(isolated_state_dir.glob("*.tmp")) == []


def test_save_overwrites_existing(isolated_state_dir):
    save_persistent_state("key", {"history": ["first"], "global_counter": 1})
    save_persistent_state("key", {"history": ["second"], "global_counter": 2})
    loaded = load_persistent_state("key")
    assert loaded["history"] == ["second"]
    assert loaded["global_counter"] == 2


def test_load_corrupt_json_returns_default(isolated_state_dir):
    isolated_state_dir.mkdir(parents=True)
    (isolated_state_dir / "corrupt.json").write_text("not valid json{{{")
    assert load_persistent_state("corrupt") == {
        "history": [],
        "last_fb_sig": None,
        "global_counter": 0,
    }


def test_save_swallows_write_errors(isolated_state_dir, monkeypatch):
    """A failing write must not raise -- persistence is best-effort."""

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(state_mod.Path, "mkdir", boom)
    save_persistent_state("key", {"history": ["a"]})
    assert load_persistent_state("key") == {
        "history": [],
        "last_fb_sig": None,
        "global_counter": 0,
    }


def test_load_swallows_read_errors(isolated_state_dir, monkeypatch):
    """A corrupt/hostile file must not raise on load either."""
    save_persistent_state("key", {"history": ["a"]})

    real_open = state_mod.Path.open

    def flaky(self, *args, **kwargs):
        if args and args[0] == "r":
            raise OSError("io error")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(state_mod.Path, "open", flaky)
    assert load_persistent_state("key") == {
        "history": [],
        "last_fb_sig": None,
        "global_counter": 0,
    }


def test_saved_file_is_valid_json(isolated_state_dir):
    save_persistent_state(
        "key", {"history": ["a"], "last_fb_sig": None, "global_counter": 1}
    )
    raw = (isolated_state_dir / "key.json").read_text(encoding="utf-8")
    assert json.loads(raw)["history"] == ["a"]
