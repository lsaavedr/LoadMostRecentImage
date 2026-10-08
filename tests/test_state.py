import importlib
import json

import pytest

import utils.state as state_mod
from utils.state import (
    clear_persistent_states,
    load_persistent_state,
    save_persistent_state,
    state_path,
)


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
    }


def test_save_then_load_roundtrip(isolated_state_dir):
    data = {"history": ["a"], "last_fb_sig": "s"}
    save_persistent_state("key", data)
    assert load_persistent_state("key") == data


def test_save_creates_state_dir_when_missing(isolated_state_dir):
    """STATE_DIR is created lazily by save, not at import time."""
    assert not isolated_state_dir.exists()
    save_persistent_state("key", {"history": []})
    assert isolated_state_dir.is_dir()
    assert (isolated_state_dir / "key.json").exists()


def test_save_overwrites_existing(isolated_state_dir):
    save_persistent_state("key", {"history": ["first"]})
    save_persistent_state("key", {"history": ["second"]})
    assert load_persistent_state("key")["history"] == ["second"]


def test_load_corrupt_json_returns_default(isolated_state_dir):
    isolated_state_dir.mkdir(parents=True)
    (isolated_state_dir / "corrupt.json").write_text("not valid json{{{")
    assert load_persistent_state("corrupt") == {
        "history": [],
        "last_fb_sig": None,
    }


def test_save_swallows_write_errors(isolated_state_dir, monkeypatch, caplog):
    """A failing write must not raise -- persistence is best-effort.

    But "best-effort" may not mean "silent": a full disk or a state directory
    that lost its permissions leaves the user with a history that quietly stops
    persisting, which is worth a warning.
    """

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(state_mod.Path, "mkdir", boom)
    with caplog.at_level("WARNING"):
        save_persistent_state("key", {"history": ["a"]})
    assert load_persistent_state("key") == {
        "history": [],
        "last_fb_sig": None,
    }
    assert "save_persistent_state failed" in caplog.text


def test_load_swallows_read_errors(isolated_state_dir, monkeypatch, caplog):
    """A corrupt/hostile file must not raise on load either, and must say so."""
    save_persistent_state("key", {"history": ["a"]})

    real_open = state_mod.Path.open

    def flaky(self, *args, **kwargs):
        if args and args[0] == "r":
            raise OSError("io error")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(state_mod.Path, "open", flaky)
    with caplog.at_level("WARNING"):
        assert load_persistent_state("key") == {
            "history": [],
            "last_fb_sig": None,
        }
    assert "load_persistent_state failed" in caplog.text


def test_saved_file_is_valid_json(isolated_state_dir):
    save_persistent_state("key", {"history": ["a"], "last_fb_sig": None})
    raw = (isolated_state_dir / "key.json").read_text(encoding="utf-8")
    assert json.loads(raw)["history"] == ["a"]


# --- clear_persistent_states ---------------------------------------------


def test_clear_persistent_states_deletes_json_files(isolated_state_dir):
    save_persistent_state("k1", {"history": []})
    save_persistent_state("k2", {"last_fb_sig": "s2"})
    assert len(list(isolated_state_dir.glob("*.json"))) == 2

    clear_persistent_states()

    assert list(isolated_state_dir.glob("*.json")) == []
    assert load_persistent_state("k1") == {"history": [], "last_fb_sig": None}


def test_clear_persistent_states_deletes_orphaned_tmp(isolated_state_dir):
    """A write interrupted mid-dump leaves a staged file that nothing else removes."""
    save_persistent_state("k1", {"history": ["/a.png"]})
    staged = state_path("k2").with_suffix(".tmp")
    staged.write_text('{"history": ["/b.png"')  # truncated by a crash

    clear_persistent_states()

    assert not staged.exists()


def test_save_leaves_no_tmp_on_success(isolated_state_dir):
    save_persistent_state("k1", {"history": ["/a.png"]})

    assert list(isolated_state_dir.glob("*.tmp")) == []


def test_clear_persistent_states_ignores_missing_dir():
    # No-op when the directory doesn't exist yet.
    with pytest.raises(FileNotFoundError):
        state_mod.STATE_DIR.unlink()
    clear_persistent_states()


def test_clear_persistent_states_swallows_errors(monkeypatch, caplog):
    """This runs on every graph reload, so a failure is worth saying out loud:
    otherwise the user reloads, sees an empty history, and has no idea the
    reset never landed."""

    def boom(*args, **kwargs):
        raise OSError("io error")

    monkeypatch.setattr(state_mod.Path, "glob", boom)
    with caplog.at_level("WARNING"):
        assert clear_persistent_states() is False
    assert "clear_persistent_states failed" in caplog.text


def test_clear_persistent_states_reports_success(isolated_state_dir):
    """The route answers from this return value, so success has to be an
    explicit True and not merely the absence of an exception."""
    assert clear_persistent_states() is True
