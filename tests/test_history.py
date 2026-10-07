from unittest.mock import Mock

import pytest

from utils.history import (
    HistoryState,
    is_fallback_marker,
    make_fallback_marker,
    make_state_key,
)

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


def test_make_state_key_fields_are_not_separated():
    """Documents current behaviour: fields are hashed with no separator, so two
    different field splits can collide onto the same key. Recorded because it
    means a directory ending in a suffix could share state with another config."""
    assert make_state_key("ab", "c", "", "") == make_state_key("a", "bc", "", "")


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
    assert state.global_counter == 0


def test_save_and_load_roundtrip():
    HistoryState(
        key="k", history=["a", "b"], last_fb_sig="sig", global_counter=2
    ).save()

    loaded = HistoryState.load("k")
    assert loaded.history == ["a", "b"]
    assert loaded.last_fb_sig == "sig"
    assert loaded.global_counter == 2


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
    state = HistoryState(
        key="k", history=["old", "older"], last_fb_sig="old", global_counter=9
    )
    state.reset_for_tensor("newsig")

    assert state.history == ["fallback::newsig"]
    assert state.last_fb_sig == "newsig"
    assert state.global_counter == 1


def test_reset_for_tensor_persists():
    state = HistoryState(key="k")
    state.reset_for_tensor("sig")
    assert HistoryState.load("k").history == ["fallback::sig"]


# --- append_entry --------------------------------------------------------


def test_append_entry_grows_history_and_counter():
    state = HistoryState(key="k")
    state.reset_for_tensor("sig")

    assert state.append_entry("/path/img.png", "sig") == 2
    assert state.history == ["fallback::sig", "/path/img.png"]
    assert state.global_counter == 2


def test_append_entry_counter_tracks_length():
    state = HistoryState(key="k")
    for i in range(3):
        assert state.append_entry(f"/img{i}.png", "sig") == i + 1
    assert state.global_counter == len(state.history)


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
    assert reloaded.global_counter == 3


def test_tensor_change_resets_previous_history():
    state = HistoryState.load("flow2")
    state.reset_for_tensor("sig1")
    state.append_entry("/a.png", "sig1")

    state.reset_for_tensor("sig2")
    assert state.history == ["fallback::sig2"]
    assert state.last_fb_sig == "sig2"
