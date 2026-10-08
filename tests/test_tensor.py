import pytest
import torch

from utils.tensor import prepare_fallback_tensor, tensor_signature

# --- tensor_signature: identity ------------------------------------------


def test_signature_is_deterministic():
    t = torch.rand(1, 4, 4, 3)
    assert tensor_signature(t) == tensor_signature(t)


def test_signature_is_hex_md5_of_content():
    sig = tensor_signature(torch.zeros(1, 4, 4, 3))
    assert len(sig) == 32
    int(sig, 16)


def test_signature_changes_when_shape_changes():
    assert tensor_signature(torch.zeros(1, 4, 4, 3)) != tensor_signature(
        torch.zeros(1, 8, 8, 3)
    )


def test_signature_changes_when_dtype_changes():
    assert tensor_signature(torch.zeros(1, 4, 4, 3)) != tensor_signature(
        torch.zeros(1, 4, 4, 3, dtype=torch.float16)
    )


def test_signature_is_content_based_not_storage_based():
    """Two tensors with identical pixels must produce the same signature,
    regardless of where in memory they live. This is what lets the node keep
    its fallback history across runs when ComfyUI hands over a freshly
    allocated tensor with unchanged content."""
    assert tensor_signature(torch.ones(1, 4, 4, 3)) == tensor_signature(
        torch.ones(1, 4, 4, 3)
    )


def test_signature_handles_large_tensors():
    assert tensor_signature(torch.rand(1, 512, 512, 3))


@pytest.mark.parametrize("dtype", [torch.bfloat16, torch.float8_e4m3fn])
def test_signature_is_content_based_for_dtypes_numpy_cannot_represent(dtype):
    """bfloat16 and float8 have no numpy equivalent, so `.numpy()` raises on
    them. Narrowing to uint8 keeps the signature content-based. An
    identity-based fallback would carry a different value on every process,
    which resets the fallback history whenever ComfyUI restarts.
    """
    a = torch.ones(1, 4, 4, 3).to(dtype)
    b = torch.ones(1, 4, 4, 3).to(dtype)

    assert len(tensor_signature(a)) == 32
    assert tensor_signature(a) == tensor_signature(b)
    assert tensor_signature(a) != tensor_signature(torch.zeros(1, 4, 4, 3).to(dtype))


def test_signature_covers_every_element_not_a_sample():
    """The whole tensor is hashed, so a single-element edit in a large tensor
    is a different signature. A strided sample would miss it and let a stale
    history survive an upstream change."""
    base = torch.zeros(1, 128, 128, 3)
    edited = base.clone()
    edited[0, 1, 1, 0] = 1.0

    assert base.numel() > 64  # the edit is well inside what sampling skipped
    assert tensor_signature(base) != tensor_signature(edited)


def test_signature_ignores_tensor_layout():
    """Content decides the signature, not stride order: a non-contiguous view
    hashes the same as the contiguous copy of its own pixels, so a view
    upstream produces does not read as a changed image."""
    view = torch.rand(1, 8, 8, 6)[..., ::2]
    assert not view.is_contiguous()

    assert tensor_signature(view) == tensor_signature(view.contiguous())


def test_signature_sees_content_that_transposing_reorders():
    """Layout-independence is not layout-blindness: a transpose really does
    move pixels, and the signature has to notice."""
    base = torch.rand(1, 8, 8, 3)

    assert tensor_signature(base) != tensor_signature(base.transpose(1, 2))


def test_signature_separates_images_that_differ_below_1_0():
    """IMAGE tensors hold floats in [0, 1). Narrowing them without scaling by
    255 truncates every value to zero, which would give every image the same
    signature regardless of content."""
    dark = torch.full((1, 4, 4, 3), 0.1)
    mid = torch.full((1, 4, 4, 3), 0.6)

    assert tensor_signature(dark) != tensor_signature(mid)


@pytest.mark.parametrize(
    "value", [float("nan"), float("inf"), float("-inf"), -1.0, 5.0]
)
def test_signature_is_deterministic_for_out_of_range_values(value):
    """Values outside [0, 1] wrap rather than saturate when narrowed, and
    non-finite values become zero. None of that matters for hashing as long as
    the choice is stable: an unstable one would reset the history every run."""
    t = torch.full((1, 2, 2, 3), value)

    assert tensor_signature(t) == tensor_signature(t)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_values_read_as_black(value):
    """Non-finite values belong in no image and narrow to zero, so they collide
    with a black tensor. Recorded because it is the one way a genuine content
    change goes unnoticed."""
    assert tensor_signature(torch.full((1, 2, 2, 3), value)) == tensor_signature(
        torch.zeros(1, 2, 2, 3)
    )


@pytest.mark.parametrize("value", [-1.0, 0.5, 1.0, 5.0])
def test_out_of_range_values_stay_distinguishable_from_black(value):
    assert tensor_signature(torch.full((1, 2, 2, 3), value)) != tensor_signature(
        torch.zeros(1, 2, 2, 3)
    )


def test_signature_distinguishes_bfloat16_from_its_float32_widening():
    """The dtype is part of the hash, so a cast cannot collide with a real f32."""
    assert tensor_signature(torch.ones(1, 4, 4, 3).bfloat16()) != tensor_signature(
        torch.ones(1, 4, 4, 3)
    )


def test_signature_handles_empty_tensor():
    assert tensor_signature(torch.empty(0))


def test_signature_does_not_mutate_input():
    t = torch.rand(1, 4, 4, 3)
    t_clone = t.clone()
    tensor_signature(t)
    assert torch.equal(t, t_clone)


# --- tensor_signature: non-tensors and failures ---------------------------


@pytest.mark.parametrize("value", ["hello", None, 42, b"bytes", [1, 2, 3]])
def test_non_tensor_signature_uses_identity(value):
    assert tensor_signature(value) == f"id::{id(value)}"


def test_non_tensor_signature_is_stable():
    obj = object()
    assert tensor_signature(obj) == tensor_signature(obj)


def test_non_tensor_signature_differs_per_object():
    assert tensor_signature(object()) != tensor_signature(object())


def test_tensor_like_object_never_reaches_the_hash_path():
    """Non-tensors short-circuit on the isinstance check, so a broken object
    cannot trigger the exception fallback at all."""

    class Broken:
        shape = "bad"
        dtype = "bad"

        def detach(self):
            raise RuntimeError("boom")

    broken = Broken()
    assert tensor_signature(broken) == f"id::{id(broken)}"


def test_tensor_raising_on_shape_degrades_to_timestamp():
    """When both the hash and the id/shape fallback fail, return a timestamp."""

    class BadShapeTensor(torch.Tensor):
        @property
        def shape(self):
            raise RuntimeError("bad shape")

    result = tensor_signature(BadShapeTensor())
    assert result.isdigit()


# --- prepare_fallback_tensor --------------------------------------------


def test_prepare_fallback_tensor_returns_first_image_only():
    result = prepare_fallback_tensor(torch.rand(4, 8, 6, 3))
    assert result is not None

    tensor, path, w, h, mtime = result
    assert tensor.shape == (1, 8, 6, 3)
    assert path == "fallback:image_input"
    assert (w, h) == (6, 8)
    assert mtime == "N/A"


def test_prepare_fallback_tensor_slices_batch():
    batch = torch.rand(3, 8, 6, 3)
    result = prepare_fallback_tensor(batch)
    assert result is not None
    assert torch.equal(result[0], batch[:1])


def test_prepare_fallback_tensor_none_returns_none():
    assert prepare_fallback_tensor(None) is None


@pytest.mark.parametrize(
    "bad",
    [
        torch.rand(4, 4, 3),  # 3 dims
        torch.rand(4, 4),  # 2 dims
        torch.rand(4),  # 1 dim
        torch.tensor(1.0),  # 0 dims
    ],
)
def test_prepare_fallback_tensor_rejects_wrong_rank(bad):
    with pytest.raises(ValueError, match=r"shape \[B,H,W,C\]"):
        prepare_fallback_tensor(bad)


class ArrayLike:
    """Duck-types enough of a tensor to be 4-D, but isn't a torch.Tensor."""

    ndim = 4
    shape = (1, 4, 4, 3)


@pytest.mark.parametrize("bad", ["not a tensor", 42, [1, 2, 3, 4], ArrayLike()])
def test_prepare_fallback_tensor_rejects_non_tensor(bad):
    with pytest.raises(ValueError, match="fallback_image"):
        prepare_fallback_tensor(bad)


def test_prepare_fallback_tensor_supports_single_channel():
    result = prepare_fallback_tensor(torch.rand(1, 4, 4, 1))
    assert result is not None
    assert result[2:4] == (4, 4)
