import json
from unittest.mock import Mock

import pytest

from utils.history import (
    HistoryState,
    is_fallback_marker,
    make_fallback_marker,
    make_state_key,
)
from utils.state import save_persistent_state, state_path

# --- make_state_key ------------------------------------------------------


def test_make_state_key_is_deterministic():
    args = ("/tmp/imgs", ".*", "false", "modified")
    assert make_state_key(*args) == make_state_key(*args)


def test_make_state_key_is_hex_md5():
    key = make_state_key("/tmp/imgs", ".*", "false", "modified")
    assert len(key) == 32
    int(key, 16)  # raises if not hex


@pytest.mark.parametrize(
    "index, value",
    [
        (0, "/tmp/other"),
        (1, ".*\\.png$"),
        (2, "true"),
        (3, "created"),
    ],
)
def test_make_state_key_changes_with_every_field(index, value):
    base = ["/tmp/imgs", ".*", "false", "modified"]
    variant = list(base)
    variant[index] = value
    assert make_state_key(*base) != make_state_key(*variant)


@pytest.mark.parametrize(
    "left, right",
    [
        (("ab", "c", "", ""), ("a", "bc", "", "")),
        (
            ("/tmp/imgs", ".*", "false", "modified"),
            ("/tmp/imgs.*falsemodified", "", "", ""),
        ),
        (("", "ab", "cd", "ef"), ("", "abcd", "ef", "")),
        (("aa", "", "", ""), ("", "aa", "", "")),
        # A separator alone would not be enough: the delimiter can appear
        # inside a field, which is why the length prefix is what matters.
        (("a:b", "c", "", ""), ("a", "b:c", "", "")),
        (("::", "", "", ""), ("", ":", "", "")),
    ],
)
def test_make_state_key_fields_cannot_collide(left, right):
    """Fields are length-prefixed, so no two splits of the same bytes collide."""
    assert make_state_key(*left) != make_state_key(*right)


# --- fallback markers ----------------------------------------------------


def test_is_fallback_marker_true():
    assert is_fallback_marker(make_fallback_marker("sig"))


@pytest.mark.parametrize("entry", ["", "/path/img.png", "fallback", "FALLBACK::sig"])
def test_is_fallback_marker_false(entry):
    assert not is_fallback_marker(entry)


def test_is_fallback_marker_is_prefix_based_not_exact():
    """An empty signature still counts as a marker: the check is ``startswith``."""
    assert is_fallback_marker("fallback::")


def test_make_fallback_marker_embeds_signature():
    assert make_fallback_marker("deadbeef") == "fallback::deadbeef"


# --- HistoryState.load / save -------------------------------------------


def test_load_missing_key_returns_empty_state():
    state = HistoryState.load("key_that_was_never_saved")
    assert state.history == []
    assert state.last_fb_sig is None


def test_save_and_load_roundtrip():
    HistoryState(key="k", history=["a", "b"], last_fb_sig="sig").save()

    loaded = HistoryState.load("k")
    assert loaded.history == ["a", "b"]
    assert loaded.last_fb_sig == "sig"


def test_state_keys_are_isolated():
    HistoryState(key="k1", history=["a"]).save()
    HistoryState(key="k2", history=["b", "c"]).save()

    assert HistoryState.load("k1").history == ["a"]
    assert HistoryState.load("k2").history == ["b", "c"]


def test_save_preserves_the_key():
    state = HistoryState(key="my_key")
    state.save()
    assert HistoryState.load("my_key").key == "my_key"


# --- reset_for_tensor ----------------------------------------------------


def test_reset_for_tensor_seeds_single_marker():
    state = HistoryState(key="k", history=["old", "older"], last_fb_sig="old")
    state.reset_for_tensor("newsig")

    assert state.history == ["fallback::newsig"]
    assert state.last_fb_sig == "newsig"


def test_reset_for_tensor_persists():
    state = HistoryState(key="k")
    state.reset_for_tensor("sig")
    assert HistoryState.load("k").history == ["fallback::sig"]


# --- append_entry --------------------------------------------------------


def test_append_entry_grows_history():
    state = HistoryState(key="k")
    state.reset_for_tensor("sig")

    state.append_entry("/path/img.png", "sig")

    assert state.history == ["fallback::sig", "/path/img.png"]
    assert len(state.history) == 2


def test_append_entry_returns_none():
    """The new entry count is `len(history)`, so there is nothing to return."""
    state = HistoryState(key="k")

    assert state.append_entry("/path/img.png", "sig") is None


def test_append_entry_persists():
    state = HistoryState(key="k")
    state.append_entry("/path/img.png", "sig")

    loaded = HistoryState.load("k")
    assert loaded.history == ["/path/img.png"]
    assert loaded.last_fb_sig == "sig"


# --- pick_new_entry ------------------------------------------------------


def test_pick_new_entry_uses_picker_result():
    picker = Mock(return_value="/found/img.png")
    assert HistoryState(key="k").pick_new_entry(picker, "sig") == "/found/img.png"
    picker.assert_called_once_with()


def test_pick_new_entry_falls_back_to_marker_when_picker_returns_none():
    assert HistoryState(key="k").pick_new_entry(lambda: None, "sig") == "fallback::sig"


def test_pick_new_entry_does_not_mutate_state():
    state = HistoryState(key="k")
    state.pick_new_entry(lambda: "/found/img.png", "sig")
    assert state.history == []


# --- realistic node flow -------------------------------------------------


def test_history_accumulates_across_runs():
    """Two runs after a tensor reset append one entry each."""
    state = HistoryState.load("flow")
    state.reset_for_tensor("sig")

    state.append_entry("/a.png", "sig")
    state.append_entry("/b.png", "sig")

    reloaded = HistoryState.load("flow")
    assert reloaded.history == ["fallback::sig", "/a.png", "/b.png"]


def test_tensor_change_resets_previous_history():
    state = HistoryState.load("flow2")
    state.reset_for_tensor("sig1")
    state.append_entry("/a.png", "sig1")

    state.reset_for_tensor("sig2")
    assert state.history == ["fallback::sig2"]
    assert state.last_fb_sig == "sig2"


def test_load_ignores_legacy_global_counter():
    """State files written before the field was dropped must still load."""
    save_persistent_state(
        "legacy",
        {
            "history": ["/a.png", "/b.png"],
            "last_fb_sig": "sig",
            "global_counter": 2,
        },
    )

    state = HistoryState.load("legacy")

    assert state.history == ["/a.png", "/b.png"]
    assert state.last_fb_sig == "sig"
    assert not hasattr(state, "global_counter")

    state.append_entry("/c.png", "sig")
    reloaded = HistoryState.load("legacy")
    assert reloaded.history == ["/a.png", "/b.png", "/c.png"]
    assert "global_counter" not in json.loads(state_path("legacy").read_text())
