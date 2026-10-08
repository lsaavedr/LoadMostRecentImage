import os
import time
from pathlib import Path

import pytest
import torch
from PIL import Image

from utils.file import (
    DEFAULT_PATTERN,
    list_images,
    load_image_with_metadata,
    pick_latest_image,
    pick_most_recent,
    pil_to_tensor,
)


@pytest.fixture
def image_dir(tmp_path):
    """Directory with 3 images, 1 text file, and 1 image in a subdirectory."""
    for name in ["a.png", "b.jpg", "d.webp"]:
        (tmp_path / name).write_bytes(b"x")
    (tmp_path / "notes.txt").write_bytes(b"x")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "nested.png").write_bytes(b"x")
    return tmp_path


@pytest.fixture
def real_image_dir(tmp_path):
    """Directory holding an actual decodable PNG."""
    Image.new("RGB", (8, 6), (0, 0, 255)).save(tmp_path / "img.png")
    return tmp_path


# --- list_images ---------------------------------------------------------


def test_list_images_matches_default_pattern(image_dir):
    names = {p.name for p in list_images(image_dir, DEFAULT_PATTERN, recursive=False)}
    assert names == {"a.png", "b.jpg", "d.webp"}


def test_list_images_excludes_non_matching_extension(image_dir):
    names = {p.name for p in list_images(image_dir, DEFAULT_PATTERN, recursive=False)}
    assert "notes.txt" not in names


def test_list_images_non_recursive_skips_subdirs(image_dir):
    names = {p.name for p in list_images(image_dir, DEFAULT_PATTERN, recursive=False)}
    assert "nested.png" not in names


def test_list_images_recursive_includes_subdirs(image_dir):
    names = {p.name for p in list_images(image_dir, DEFAULT_PATTERN, recursive=True)}
    assert "nested.png" in names


def test_list_images_empty_dir(tmp_path):
    assert list_images(tmp_path, DEFAULT_PATTERN, recursive=False) == []


def test_list_images_missing_dir(tmp_path):
    assert (
        list_images(tmp_path / "does_not_exist", DEFAULT_PATTERN, recursive=False) == []
    )


def test_list_images_file_path_is_not_a_dir(tmp_path):
    target = tmp_path / "a.png"
    target.write_bytes(b"x")
    assert list_images(target, DEFAULT_PATTERN, recursive=False) == []


def test_list_images_invalid_regex_raises(image_dir):
    with pytest.raises(ValueError, match="Invalid regex pattern"):
        list_images(image_dir, "[unclosed", recursive=False)


def test_list_images_blank_pattern_falls_back_to_default(image_dir):
    explicit = list_images(image_dir, DEFAULT_PATTERN, recursive=False)
    for blank in ("", "   "):
        assert list_images(image_dir, blank, recursive=False) == explicit


def test_list_images_pattern_is_case_insensitive(image_dir):
    (image_dir / "SHOUT.PNG").write_bytes(b"x")
    names = {p.name for p in list_images(image_dir, DEFAULT_PATTERN, recursive=False)}
    assert "SHOUT.PNG" in names


def test_list_images_custom_pattern(image_dir):
    names = {p.name for p in list_images(image_dir, r".*\.txt$", recursive=False)}
    assert names == {"notes.txt"}


# --- pick_most_recent ----------------------------------------------------


def test_pick_most_recent_by_modified(tmp_path):
    older = tmp_path / "older.png"
    newer = tmp_path / "newer.png"
    older.write_bytes(b"x")
    time.sleep(0.01)
    newer.write_bytes(b"x")

    assert pick_most_recent([older, newer], "modified") == newer


def test_pick_most_recent_by_created(tmp_path):
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    first.write_bytes(b"x")
    time.sleep(0.01)
    second.write_bytes(b"x")

    assert pick_most_recent([first, second], "created") == second


def test_pick_most_recent_breaks_ties_on_path(tmp_path):
    """Identical timestamps must resolve the same way on every launch.

    Both callers pass a set, and a set of Path iterates in hash(str) order,
    which Python randomises per process. Before the tiebreak this returned a
    different file on each start.
    """
    made = []
    for name in ("a.png", "b.png", "c.png"):
        p = tmp_path / name
        p.write_bytes(b"x")
        os.utime(p, (1_700_000_000, 1_700_000_000))
        made.append(p)

    assert pick_most_recent(set(made), "modified") == tmp_path / "c.png"
    assert pick_most_recent(made, "modified") == tmp_path / "c.png"
    assert pick_most_recent(list(reversed(made)), "modified") == tmp_path / "c.png"


def test_pick_most_recent_prefers_newer_mtime_over_path(tmp_path):
    """The path only breaks ties. `z.png` sorts last by name, so if it won
    here the tiebreak would be the primary key."""
    earlier = tmp_path / "z.png"
    later = tmp_path / "a.png"
    earlier.write_bytes(b"x")
    later.write_bytes(b"x")
    os.utime(earlier, (1_000, 1_000))
    os.utime(later, (2_000, 2_000))

    assert pick_most_recent([earlier, later], "modified") == later


def test_pick_most_recent_empty_raises():
    with pytest.raises(ValueError, match="No image files found"):
        pick_most_recent([], "modified")


@pytest.mark.parametrize("bad_sort", ["name", "", "modified ", None])
def test_pick_most_recent_invalid_sort_raises(bad_sort):
    with pytest.raises(ValueError, match="sort_by must be"):
        pick_most_recent([Path("x.png")], bad_sort)


# --- pil_to_tensor -------------------------------------------------------


def test_pil_to_tensor_rgb_values():
    t = pil_to_tensor(Image.new("RGB", (4, 3), (255, 0, 0)))
    assert t.shape == (1, 3, 4, 3)
    assert t.dtype == torch.float32
    assert torch.allclose(t[0, 0, 0], torch.tensor([1.0, 0.0, 0.0]))


def test_pil_to_tensor_normalizes_to_0_1():
    t = pil_to_tensor(Image.new("RGB", (2, 2), (128, 128, 128)))
    assert t.min() >= 0.0 and t.max() <= 1.0
    assert pytest.approx(t.max().item(), abs=0.01) == 128 / 255


@pytest.mark.parametrize(
    "mode, colour",
    [
        ("RGB", (10, 20, 30)),
        ("RGBA", (10, 20, 30, 128)),
        ("L", 128),
        ("P", None),
    ],
)
def test_pil_to_tensor_always_yields_three_channels(mode, colour):
    """RGBA, L and P are all normalised to a [B,H,W,3] RGB tensor."""
    img = Image.new("P", (2, 2)) if colour is None else Image.new(mode, (2, 2), colour)
    t = pil_to_tensor(img)
    assert t.shape == (1, 2, 2, 3)
    assert t.shape[-1] == 3


def test_pil_to_tensor_preserves_hw_order():
    """Height is dim 1 and width is dim 2, i.e. no transpose."""
    t = pil_to_tensor(Image.new("RGB", (6, 2), (0, 0, 0)))
    assert t.shape == (1, 2, 6, 3)


# --- load_image_with_metadata -------------------------------------------


def test_load_image_with_metadata(tmp_path):
    p = tmp_path / "test.png"
    Image.new("RGB", (8, 6), (0, 0, 255)).save(p)

    tensor, path_str, w, h, mtime = load_image_with_metadata(p)

    assert tensor.shape == (1, 6, 8, 3)
    assert path_str == str(p)
    assert (w, h) == (8, 6)
    assert len(mtime) == len("2025-01-01 00:00:00")


def test_load_image_with_metadata_mtime_is_formatted(tmp_path):
    p = tmp_path / "test.png"
    Image.new("RGB", (4, 4), (0, 0, 0)).save(p)

    *_, mtime = load_image_with_metadata(p)
    assert mtime.count(":") == 2
    assert mtime != "N/A"


# --- pick_latest_image ---------------------------------------------------


def test_pick_latest_image_returns_absolute_path(image_dir):
    result = pick_latest_image(str(image_dir), DEFAULT_PATTERN, recursive=False)
    assert result is not None
    assert Path(result).is_absolute()


def test_pick_latest_image_resolves_to_existing_file(real_image_dir):
    result = pick_latest_image(str(real_image_dir), DEFAULT_PATTERN, recursive=False)
    assert Path(result).exists()


def test_pick_latest_image_no_matches_returns_none(tmp_path):
    (tmp_path / "notes.txt").write_bytes(b"x")
    assert pick_latest_image(str(tmp_path), DEFAULT_PATTERN, recursive=False) is None


def test_pick_latest_image_missing_dir_returns_none(tmp_path):
    assert pick_latest_image(str(tmp_path / "nope"), DEFAULT_PATTERN, False) is None


def test_pick_latest_image_expands_user(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    Image.new("RGB", (2, 2), (0, 0, 0)).save(tmp_path / "home.png")

    result = pick_latest_image("~", DEFAULT_PATTERN, recursive=False)
    assert result is not None
    assert Path(result).name == "home.png"


def test_pick_latest_image_uses_mtime_not_creation_order(tmp_path):
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    first.write_bytes(b"x")
    time.sleep(0.01)
    second.write_bytes(b"x")
    # Re-touch first so its mtime is newest despite being created first.
    time.sleep(0.01)
    first.touch()

    assert (
        Path(pick_latest_image(str(tmp_path), DEFAULT_PATTERN, False)).name
        == "first.png"
    )
