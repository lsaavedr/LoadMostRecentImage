import re
import time
import numpy as np
import torch
from pathlib import Path
from typing import Optional
from PIL import Image

# Default regex matches common image extensions (case-insensitive)
DEFAULT_PATTERN = r".*\.(png|jpe?g|webp|bmp|tiff?)$"


def list_images(directory: Path, pattern: str, recursive: bool):
    if not directory.exists() or not directory.is_dir():
        return []

    pattern = pattern.strip()
    if not pattern:
        regex_pattern = DEFAULT_PATTERN
    else:
        regex_pattern = pattern

    try:
        regex = re.compile(regex_pattern, re.IGNORECASE)
    except re.error as e:
        raise ValueError(f"Invalid regex pattern '{pattern}': {e}")

    glob_pattern = "**/*" if recursive else "*"
    candidates = directory.rglob(glob_pattern) if recursive else directory.glob("*")

    return [p for p in candidates if p.is_file() and regex.search(p.name)]


def pick_most_recent(files, by: str):
    if not files:
        raise ValueError("No image files found that match your pattern.")

    if by != "modified" and by != "created":
        raise ValueError("sort_by must be 'modified' or 'created'")

    return max(
        files,
        key=lambda p: p.stat().st_mtime if by == "modified" else p.stat().st_ctime,
    )


def pil_to_tensor(img):
    if img.mode not in ("RGB", "RGBA", "L"):
        img = img.convert("RGB")
    if img.mode == "RGBA":
        img = img.convert("RGB")
    if img.mode == "L":
        img = img.convert("RGB")

    arr = np.asarray(img, dtype=np.float32) / 255.0  # H,W,3

    if arr.ndim == 2:
        arr = arr[:, :, None]

    t = torch.from_numpy(arr).unsqueeze(0)  # [1,H,W,C]

    return t


def load_image_with_metadata(path: Path) -> tuple:
    """Load image at path and return (tensor, path_str, w, h, mtime_str)."""
    img = Image.open(path)
    img.load()

    tensor = pil_to_tensor(img)
    h, w = int(tensor.shape[1]), int(tensor.shape[2])

    ts = time.localtime(path.stat().st_mtime)
    mtime_str = time.strftime("%Y-%m-%d %H:%M:%S", ts)

    return (tensor, str(path), w, h, mtime_str)


def pick_latest_image(directory: str, pattern: str, recursive: bool) -> Optional[str]:
    """Find the most recent image path, or None if no images found."""
    dir_path = Path(directory).expanduser()
    files = list_images(dir_path, pattern, recursive)
    files = list({p.resolve() for p in files if p.exists()})

    if not files:
        return None

    return str(pick_most_recent(files, "modified"))
