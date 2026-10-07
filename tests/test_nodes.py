import os
import time

import pytest
import torch
from PIL import Image

from .. import nodes as nodes_mod
from ..nodes import LoadMostRecentImage
from ..utils import history as history_mod
from ..utils import state as pkg_state

PATTERN = r".*\.(png|jpe?g)$"


def _iter_of(out) -> int:
    return out.kwargs["ui"]["iter"][0]


@pytest.fixture()
def image_dir(tmp_path):
    d = tmp_path / "images"
    d.mkdir()
    Image.new("RGB", (4, 2), (255, 0, 0)).save(d / "a.png")
    return d


@pytest.fixture()
def empty_dir(tmp_path):
    d = tmp_path / "empty"
    d.mkdir()
    return d


@pytest.fixture()
def fallback():
    return torch.rand(1, 8, 8, 3)


@pytest.fixture()
def pkg_state_dir(tmp_path, monkeypatch):
    """Redirect the *package* state module.

    The autouse `isolated_state_dir` fixture patches top-level `utils.state`;
    `nodes` reaches its own copy through the package, so patch that one too.
    """
    d = tmp_path / "pkg_state"
    monkeypatch.setattr(pkg_state, "STATE_DIR", d)
    return d


@pytest.fixture()
def save_calls(monkeypatch):
    """Count writes to the package's persistent state."""
    calls = []
    real = history_mod.save_persistent_state

    def spy(key, state):
        calls.append(key)
        return real(key, state)

    monkeypatch.setattr(history_mod, "save_persistent_state", spy)
    return calls


def _execute(directory, **kwargs):
    return LoadMostRecentImage.execute(
        directory=str(directory), pattern=PATTERN, **kwargs
    )


def _fingerprint(**kwargs):
    return LoadMostRecentImage.fingerprint_inputs(**kwargs)


# --- happy path ----------------------------------------------------------


def test_execute_returns_image_metadata(image_dir):
    out = _execute(image_dir)

    tensor, path, w, h, mtime = out.args
    assert tuple(tensor.shape) == (1, 2, 4, 3)
    assert path == str(image_dir / "a.png")
    assert (w, h) == (4, 2)
    assert isinstance(mtime, str)


def test_execute_without_fallback_writes_no_state(image_dir, pkg_state_dir, save_calls):
    """A plain run has no history to persist, so it must not touch the disk."""
    _execute(image_dir)

    assert save_calls == []
    assert list(pkg_state_dir.glob("*.json")) == []


# --- iter semantics ------------------------------------------------------


def test_first_fallback_run_reports_len_history_plus_one(image_dir, fallback):
    out = _execute(image_dir, fallback_image=fallback)

    assert _iter_of(out) == 2  # reset_for_tensor leaves 1 entry -> 1 + 1


def test_repeat_run_reuses_entry_without_writing(
    image_dir, fallback, pkg_state_dir, save_calls
):
    first = _execute(image_dir, fallback_image=fallback)
    key = _only_key(pkg_state_dir)
    state_after_first = (pkg_state_dir / f"{key}.json").read_text()
    assert len(save_calls) == 1  # only reset_for_tensor

    second = _execute(image_dir, fallback_image=fallback)

    assert _iter_of(first) == _iter_of(second)
    # Reuse mutates nothing, so it must neither append nor rewrite the state.
    assert save_calls == [key]
    assert (pkg_state_dir / f"{key}.json").read_text() == state_after_first


def test_iter_past_history_appends_and_advances(
    image_dir, fallback, pkg_state_dir, save_calls
):
    _execute(image_dir, fallback_image=fallback)

    out = _execute(image_dir, fallback_image=fallback, iter=2)

    assert _iter_of(out) == 3
    assert len(save_calls) == 2  # reset, then the append
    key = _only_key(pkg_state_dir)
    assert len(pkg_state.load_persistent_state(key)["history"]) == 2


# --- errors --------------------------------------------------------------


def test_execute_without_images_or_fallback_raises_actionable_error(empty_dir):
    with pytest.raises(ValueError, match=r"No image matched .* in .*fallback_image"):
        _execute(empty_dir)


@pytest.fixture()
def split_sort_dir(tmp_path):
    """Two images where mtime and ctime rank them in opposite order.

    `a.png` gets an old mtime via `utime`, then a `chmod` so its ctime becomes
    the newest -- which is what makes 'modified' and 'created' disagree.
    """
    d = tmp_path / "split"
    d.mkdir()
    Image.new("RGB", (4, 2), (255, 0, 0)).save(d / "a.png")
    Image.new("RGB", (4, 2), (0, 255, 0)).save(d / "b.png")
    time.sleep(0.05)
    os.chmod(d / "a.png", 0o600)
    stamp = 1_000_000_000_000_000_000
    os.utime(d / "a.png", ns=(stamp, stamp))

    by_mtime = max(d.iterdir(), key=lambda p: p.stat().st_mtime).name
    by_ctime = max(d.iterdir(), key=lambda p: p.stat().st_ctime).name
    if by_mtime == by_ctime:
        pytest.skip("filesystem does not separate mtime from ctime")
    return d


def test_iter_tooltip_matches_append_ordering():
    """The tooltip says the history is append-ordered and 0 is the oldest.

    That is a promise about behaviour, so pin the behaviour it describes:
    revisiting a low index must replay the earlier entry, not the newest.
    """
    schema = LoadMostRecentImage.define_schema()
    iter_input = next(i for i in schema.kwargs["inputs"] if i.args[0] == "iter")
    assert "append-ordered" in iter_input.kwargs["tooltip"]
    assert "0 is the oldest entry" in iter_input.kwargs["tooltip"]


def test_low_iter_replays_the_oldest_entry(image_dir, fallback):
    """Index 0 is the oldest entry, as the tooltip states."""
    first = _execute(image_dir, fallback_image=fallback)
    time.sleep(0.01)
    Image.new("RGB", (4, 2), (0, 255, 0)).save(image_dir / "b.png")
    _execute(image_dir, fallback_image=fallback, iter=2)

    oldest = _execute(image_dir, fallback_image=fallback, iter=0)

    assert oldest.args[0].shape[0] == first.args[0].shape[0]
    assert oldest.args[1] == first.args[1] == "fallback:image_input"


def test_execute_honours_sort_by(split_sort_dir):
    """`sort_by` reaches the image selection, not just the cache key."""
    modified = _execute(split_sort_dir, sort_by="modified")
    created = _execute(split_sort_dir, sort_by="created")

    assert modified.args[1] == str(split_sort_dir / "b.png")
    assert created.args[1] == str(split_sort_dir / "a.png")


def test_execute_sort_by_agrees_with_fingerprint(split_sort_dir):
    """The cache key must describe the image that actually comes out."""
    for sort_by, attr in (("modified", "st_mtime_ns"), ("created", "st_ctime_ns")):
        out = _execute(split_sort_dir, sort_by=sort_by)
        chosen = out.args[1]
        stamp = getattr(os.stat(chosen), attr)
        key = _fingerprint(
            directory=str(split_sort_dir), pattern=PATTERN, sort_by=sort_by
        )

        assert key.startswith(f"{chosen}::{stamp}::")


def test_execute_sort_by_honoured_with_fallback_connected(split_sort_dir, fallback):
    """Same contract on the fallback branch, which picks through history."""
    first = _execute(split_sort_dir, sort_by="created", fallback_image=fallback)
    second = _execute(
        split_sort_dir, sort_by="created", fallback_image=fallback, iter=2
    )

    assert second.args[1] == str(split_sort_dir / "a.png")
    assert first.args[1] != second.args[1]


# --- fingerprint_inputs --------------------------------------------------


def test_define_schema_is_well_formed():
    schema = LoadMostRecentImage.define_schema()

    assert schema.kwargs["node_id"] == "LoadMostRecentImage"
    assert schema.kwargs["display_name"] == "Load Most Recent Image"
    assert [o.kwargs["display_name"] for o in schema.kwargs["outputs"]] == [
        "image",
        "path",
        "width",
        "height",
        "mtime",
    ]
    assert [i.args[0] for i in schema.kwargs["inputs"]] == [
        "directory",
        "pattern",
        "recursive",
        "sort_by",
        "fallback_image",
        "iter",
    ]


def test_fingerprint_tracks_latest_file_and_iter(image_dir):
    first = _fingerprint(directory=str(image_dir), pattern=PATTERN, iter=1)
    time.sleep(0.01)
    Image.new("RGB", (2, 2), (0, 255, 0)).save(image_dir / "b.png")
    second = _fingerprint(directory=str(image_dir), pattern=PATTERN, iter=1)

    assert str(image_dir / "a.png") in first
    assert str(image_dir / "b.png") in second
    # `iter` is part of the key, so bumping it invalidates the cache.
    assert _fingerprint(directory=str(image_dir), pattern=PATTERN, iter=2) != first
    assert first.endswith("::rst::1")


def test_fingerprint_distinguishes_created_from_modified(image_dir):
    """`sort_by=created` must key off ctime, not mtime."""
    target = image_dir / "a.png"
    stamp = 1_000_000_000_000_000_000
    os.utime(target, ns=(stamp, stamp))
    mtime, ctime = target.stat().st_mtime_ns, target.stat().st_ctime_ns
    if mtime == ctime:
        pytest.skip("filesystem does not separate mtime from ctime")

    created = _fingerprint(directory=str(image_dir), pattern=PATTERN, sort_by="created")
    modified = _fingerprint(
        directory=str(image_dir), pattern=PATTERN, sort_by="modified"
    )

    assert created.startswith(f"{target}::{ctime}::")
    assert modified.startswith(f"{target}::{mtime}::")


def test_fingerprint_with_fallback_image_is_always_unique(image_dir, fallback):
    """A connected fallback makes the key time-based so ComfyUI always re-runs."""
    a = _fingerprint(directory=str(image_dir), pattern=PATTERN, fallback_image=fallback)
    time.sleep(0.01)
    b = _fingerprint(directory=str(image_dir), pattern=PATTERN, fallback_image=fallback)

    assert a.startswith("fallback_image::")
    assert b.startswith("fallback_image::")
    assert a != b


def test_fingerprint_on_empty_dir_uses_dir_mtime(empty_dir):
    """An empty dir still needs a stable key, derived from the dir's own mtime."""
    sig = _fingerprint(directory=str(empty_dir), pattern=PATTERN)

    assert (
        sig == f"empty::{empty_dir.resolve()}::{empty_dir.stat().st_mtime_ns}::rst::0"
    )


def test_fingerprint_on_missing_dir_falls_back_to_clock(tmp_path):
    """`stat()` on a nonexistent dir raises OSError; the fingerprint must survive."""
    missing = tmp_path / "nope"

    sig = _fingerprint(directory=str(missing), pattern=PATTERN)

    assert sig.startswith(f"empty::{missing}::")


def test_fingerprint_swallows_invalid_regex(image_dir):
    assert isinstance(_fingerprint(directory=str(image_dir), pattern="*bad["), int)


def test_fingerprint_swallows_any_exception_type(image_dir, monkeypatch):
    """The cache key must be total: no exception type may escape.

    A raise here breaks ComfyUI's execution loop, not just this node, so the
    except clause stays broad on purpose. Ruff's BLE001 tolerates it because the
    handler logs with `logger.exception`.
    """

    def boom(*args, **kwargs):
        raise OverflowError("not in any enumerated list")

    monkeypatch.setattr(nodes_mod, "list_images", boom)

    assert isinstance(_fingerprint(directory=str(image_dir)), int)


def test_fingerprint_logs_why_it_degraded(image_dir, monkeypatch, caplog):
    def boom(*args, **kwargs):
        raise OverflowError("boom")

    monkeypatch.setattr(nodes_mod, "list_images", boom)

    with caplog.at_level("ERROR"):
        _fingerprint(directory=str(image_dir))

    assert "fingerprint_inputs failed" in caplog.text


def test_fingerprint_defaults_every_argument(image_dir):
    assert isinstance(_fingerprint(directory=str(image_dir)), str)


# --- helpers -------------------------------------------------------------


def _only_key(state_dir):
    """Return the single persisted state's key (filename without .json)."""
    files = list(state_dir.glob("*.json"))
    assert len(files) == 1, f"expected exactly one state file, got {files}"
    return files[0].stem
