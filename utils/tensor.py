import hashlib
import time

import torch


def _content_bytes(t) -> bytes:
    """Every element of the tensor, one byte each.

    Narrowing reads every element at a quarter of the bytes a float32 copy
    moves, and it is also the representation every dtype can reach: bfloat16
    and the float8 family have no numpy equivalent, so `.numpy()` raises on
    them. Hashing those bytes keeps the signature content-based and identical
    across devices and torch versions, which an identity-based fallback would
    not be.

    IMAGE tensors live in [0, 1], so the values are scaled by 255 first.
    `.to(torch.uint8)` truncates rather than scales, and without the scaling a
    whole float image collapses onto a single value.

    `float()` comes first and is a no-op for the float32 tensors ComfyUI
    hands over. For the narrower dtypes it is what makes `mul` available at
    all: the float8 family has no `mul` kernel on CPU.
    """
    scaled = t.detach().contiguous().float().mul(255.0)
    return scaled.to(torch.uint8).cpu().numpy().tobytes()


def tensor_signature(t) -> str:
    """Stable identifier for a fallback IMAGE tensor.

    Hashes shape, dtype and the full content. Two tensors differ unless every
    element is equal to within a single 8-bit step, so a one-element edit is
    still a different signature.
    """
    try:
        if not isinstance(t, torch.Tensor):
            return f"id::{id(t)}"
        h = hashlib.md5()
        h.update(str(tuple(t.shape)).encode())
        h.update(str(t.dtype).encode())
        h.update(_content_bytes(t))
        return h.hexdigest()
    except (AttributeError, TypeError, ValueError, RuntimeError, KeyError, OSError):
        try:
            return f"id::{id(t)}::{getattr(t, 'shape', '?')}"
        except (AttributeError, TypeError, ValueError, RuntimeError, KeyError, OSError):
            return str(time.time_ns())


def prepare_fallback_tensor(tensor):
    """Validate and prepare a fallback IMAGE tensor.

    Returns (tensor, path, w, h, mtime) tuple or None if tensor is None.
    """
    if tensor is None:
        return None

    if not isinstance(tensor, torch.Tensor) or tensor.ndim != 4:
        raise ValueError("fallback_image must be a tensor of shape [B,H,W,C].")

    t = tensor[:1, ...]
    h, w = int(t.shape[1]), int(t.shape[2])

    return (t, "fallback:image_input", w, h, "N/A")
