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


def test_signature_changes_when_data_changes():
    t = torch.zeros(1, 4, 4, 3)
    before = tensor_signature(t)
    t[0, 0, 0, 0] = 1.0
    assert tensor_signature(t) != before


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
    assert torch.equal(torch.ones(1, 4, 4, 3), torch.ones(1, 4, 4, 3))
    assert tensor_signature(torch.ones(1, 4, 4, 3)) == tensor_signature(
        torch.ones(1, 4, 4, 3)
    )


def test_signature_is_stable_for_the_same_storage():
    """Re-reading the same tensor object is stable too."""
    t = torch.ones(1, 4, 4, 3)
    assert tensor_signature(t) == tensor_signature(t)


def test_signature_handles_large_tensors():
    assert tensor_signature(torch.rand(1, 512, 512, 3))


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
