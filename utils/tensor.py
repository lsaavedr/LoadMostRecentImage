import hashlib
import time

import torch


def _sample_bytes(t) -> bytes:
    """Raw bytes of a strided sample, for dtypes numpy cannot represent.

    bfloat16 and the float8 family have no numpy equivalent, so `.numpy()`
    raises. Widening to float32 keeps the signature content-based and stable
    across processes, which an identity-based fallback would not be.
    """
    try:
        return t.numpy().tobytes()
    except (TypeError, NotImplementedError):
        return t.to(torch.float32).numpy().tobytes()


def tensor_signature(t) -> str:
    """Stable identifier for a fallback IMAGE tensor (changes when the tensor changes)."""
    try:
        if not isinstance(t, torch.Tensor):
            return f"id::{id(t)}"
        h = hashlib.md5()
        h.update(str(tuple(t.shape)).encode())
        h.update(str(t.dtype).encode())
        sample = t.detach().contiguous().flatten()[:: max(1, t.numel() // 64)].cpu()
        h.update(_sample_bytes(sample))
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
