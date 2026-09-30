import time
import re
import json
import hashlib
from pathlib import Path

# Default regex matches common image extensions (case-insensitive)
DEFAULT_PATTERN = r".*\.(png|jpe?g|webp|bmp|tiff?)$"


def _list_images(directory: Path, pattern: str, recursive: bool):
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


def _pick_most_recent(files, by: str):
    if not files:
        raise ValueError("No image files found that match your pattern.")
    if by == "modified":
        key_fn = lambda p: p.stat().st_mtime
    elif by == "created":
        key_fn = lambda p: p.stat().st_ctime
    else:
        raise ValueError("sort_by must be 'modified' or 'created'")
    return max(files, key=key_fn)


def _pil_to_tensor(img):
    # Lazy imports so module import never fails on missing deps
    import numpy as np
    import torch

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


# ----------------- ComfyUI-first prompt extraction -----------------


def _safe_json_load(s):
    import json

    try:
        return json.loads(s)
    except Exception:
        return None


def _extract_from_comfy_json_blob(blob):
    """
    blob: PNG tEXt 'prompt' value (JSON). Structure is the serialized prompt, e.g.:
      { "3": {"class_type": "CLIPTextEncode", "inputs": {"text":"...","clip":[...]}}, ... }
    Return (positive, negative) by tracing CLIP encoders feeding KSampler positive/negative.
    """
    data = _safe_json_load(blob)
    if not isinstance(data, dict):
        return "", ""

    nodes = {}
    for nid, node in data.items():
        if isinstance(node, dict) and "class_type" in node and "inputs" in node:
            nodes[str(nid)] = (node["class_type"], node["inputs"])

    clip_types = {
        "CLIPTextEncode",
        "CLIPTextEncodeSDXL",
        "CLIPTextEncodeAdvanced",
        "CLIPTextEncode (Prompt)",
        "CLIPTextEncode (SDXL Prompt)",
    }
    sampler_types = {
        "KSampler",
        "KSamplerAdvanced",
        "KSampler (Efficient)",
        "KSamplerSDXL",
    }

    pos_ids, neg_ids = set(), set()
    for nid, (ctype, ninputs) in nodes.items():
        if ctype in sampler_types and isinstance(ninputs, dict):
            pos = ninputs.get("positive")
            neg = ninputs.get("negative")
            if (
                isinstance(pos, (list, tuple))
                and pos
                and isinstance(pos[0], (str, int))
            ):
                pos_ids.add(str(pos[0]))
            if (
                isinstance(neg, (list, tuple))
                and neg
                and isinstance(neg[0], (str, int))
            ):
                neg_ids.add(str(neg[0]))

    def txt_from_enc(inputs):
        texts = []
        for k in ("text", "text_g", "text_l"):
            v = inputs.get(k)
            if isinstance(v, str) and v.strip():
                texts.append(v.strip())
        return "\n".join(texts)

    def collect(ids):
        out = []
        for i in ids:
            node = nodes.get(i)
            if not node:
                continue
            ctype, inputs = node
            if ctype in clip_types and isinstance(inputs, dict):
                t = txt_from_enc(inputs)
                if t:
                    out.append(t)
        return out

    pos_texts = collect(pos_ids)
    neg_texts = collect(neg_ids)

    # Fallback: gather all encoders if no sampler wiring found
    if not pos_texts and not neg_texts:
        for nid, (ctype, ninputs) in nodes.items():
            if ctype in clip_types and isinstance(ninputs, dict):
                t = txt_from_enc(ninputs)
                if t:
                    if "neg" in str(nid).lower():
                        neg_texts.append(t)
                    else:
                        pos_texts.append(t)

    return ("\n\n".join(pos_texts).strip(), "\n\n".join(neg_texts).strip())


def _parse_a1111_block(s):
    import re

    if not isinstance(s, str) or not s.strip():
        return "", ""
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    m = re.search(r"\n?Negative prompt:\s*(.*)", s, flags=re.IGNORECASE | re.DOTALL)
    if m:
        before = s[: m.start()].strip()
        after = m.group(1)
        m2 = re.search(r"\n[A-Za-z][A-Za-z _\-\/]+:\s", "\n" + after)
        negative = after[: m2.start()].strip() if m2 else after.strip()
        return before, negative
    m3 = re.search(r"\n[A-Za-z][A-Za-z _\-\/]+:\s", s)
    if m3:
        return s[: m3.start()].strip(), ""
    return s.strip(), ""


def _extract_prompts(img):
    info = getattr(img, "info", {}) or {}

    # 1) ComfyUI JSON in PNG text
    blob = info.get("prompt")
    if isinstance(blob, str) and blob.strip():
        pos, neg = _extract_from_comfy_json_blob(blob)
        if pos or neg:
            return pos, neg

    # 2) AUTOMATIC1111-style "parameters" blob
    params = info.get("parameters") or info.get("Parameters")
    if isinstance(params, str) and params.strip():
        pos, neg = _parse_a1111_block(params)
        if pos or neg:
            return pos, neg

    # 3) Simple prompt keys
    for k in ("prompt", "Positive", "positive"):
        v = info.get(k)
        if isinstance(v, str) and v.strip():
            pos = v.strip()
            neg = ""
            for nk in ("negative", "Negative", "negative_prompt", "Negative prompt"):
                nv = info.get(nk)
                if isinstance(nv, str) and nv.strip():
                    neg = nv.strip()
                    break
            return pos, neg

    # 4) JPEG EXIF fallbacks
    try:
        exif = img.getexif()
    except Exception:
        exif = None
    if exif:
        uc = exif.get(0x9286)
        if isinstance(uc, bytes):
            uc = uc[8:] if len(uc) >= 8 else uc
            try:
                uc = uc.decode("utf-8", errors="ignore")
            except Exception:
                uc = ""
        if isinstance(uc, str) and uc.strip():
            pos, neg = _parse_a1111_block(uc)
            if pos or neg:
                return pos, neg

        xpc = exif.get(0x9C9C)
        if isinstance(xpc, bytes):
            try:
                xpc = xpc.decode("utf-16le", errors="ignore").rstrip("\x00")
            except Exception:
                xpc = ""
        if isinstance(xpc, str) and xpc.strip():
            pos, neg = _parse_a1111_block(xpc)
            if pos or neg:
                return pos, neg

    return "", ""


# ----------------- Node -----------------

_STATE_DIR = Path("/root/.cache/comfyui_load_most_recent_image")
_STATE_DIR.mkdir(parents=True, exist_ok=True)


def _state_key(directory, pattern, recursive, sort_by, fallback_path):
    h = hashlib.md5()
    h.update(str(directory).encode())
    h.update(str(pattern).encode())
    h.update(str(recursive).encode())
    h.update(str(sort_by).encode())
    h.update(str(fallback_path).encode())
    return h.hexdigest()


def _state_path(key):
    return _STATE_DIR / f"{key}.json"


def _load_persistent_state(key):
    try:
        p = _state_path(key)
        if p.exists():
            with p.open("r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {"history": [], "last_fb_sig": None, "global_counter": 0}


def _save_persistent_state(key, state):
    try:
        p = _state_path(key)
        tmp = p.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(state, f)
        tmp.replace(p)
    except Exception:
        pass


def _tensor_signature(t):
    """Stable identifier for a fallback IMAGE tensor (changes when the tensor changes)."""
    try:
        import hashlib
        import torch

        if not isinstance(t, torch.Tensor):
            return f"id::{id(t)}"
        h = hashlib.md5()
        h.update(str(tuple(t.shape)).encode())
        h.update(str(t.dtype).encode())
        sample = (
            t.detach()
            .contiguous()
            .flatten()[:: max(1, t.numel() // 64)]
            .cpu()
            .numpy()
            .tobytes()
        )
        h.update(sample)
        h.update(bytes(t.data_ptr() if hasattr(t, "data_ptr") else b""))
        return h.hexdigest()
    except Exception:
        try:
            return f"id::{id(t)}::{getattr(t, 'shape', '?')}"
        except Exception:
            return time.time_ns()


from comfy_api.latest import ComfyExtension, io


# ----------------- V3 Node -----------------


class LoadMostRecentImage(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="LoadMostRecentImage",
            display_name="Load Most Recent Image",
            category="image/loaders",
            inputs=[
                io.String.Input("directory", default="", multiline=False),
                io.String.Input(
                    "pattern",
                    default=DEFAULT_PATTERN,
                    multiline=False,
                    tooltip="Python regex pattern to match filenames (case-insensitive). Examples:\n.*\\.(png|jpg|jpeg|webp)$\n^2025.*\\.png$\\n.*(cat|kitten).*\\.webp$",
                    optional=True,
                ),
                io.Combo.Input(
                    "recursive",
                    options=["false", "true"],
                    default="false",
                    optional=True,
                ),
                io.Combo.Input(
                    "sort_by",
                    options=["modified", "created"],
                    default="modified",
                    optional=True,
                ),
                io.String.Input(
                    "fallback_path", default="", multiline=False, optional=True
                ),
                io.Image.Input("fallback_image", optional=True),
                io.Int.Input(
                    "iter",
                    default=0,
                    min=0,
                    max=1000000,
                    step=1,
                    tooltip="Index into the fallback_image history. The history grows automatically:\n"
                    "0 = latest entry (added on each run if the tensor did not change)\n"
                    "N = Nth entry of the history (0-based)\n"
                    "If the counter exceeds the history length, a new entry is appended and returned.\n"
                    "When the fallback_image tensor changes, the history resets and a new run begins.",
                    optional=True,
                ),
            ],
            outputs=[
                io.Image.Output(display_name="image"),
                io.String.Output(display_name="path"),
                io.Int.Output(display_name="width"),
                io.Int.Output(display_name="height"),
                io.String.Output(display_name="mtime"),
                io.String.Output(display_name="positive_prompt"),
                io.String.Output(display_name="negative_prompt"),
            ],
            hidden=[
                io.Hidden.unique_id,
                io.Hidden.extra_pnginfo,
            ],
        )

    @classmethod
    def fingerprint_inputs(cls, **kwargs):
        try:
            directory = (kwargs.get("directory") or "").strip()
            pattern = (kwargs.get("pattern") or DEFAULT_PATTERN).strip()
            recursive = (kwargs.get("recursive") or "false") == "true"
            sort_by = (kwargs.get("sort_by") or "modified").strip()
            fallback_path = (kwargs.get("fallback_path") or "").strip()
            fallback_image = kwargs.get("fallback_image")
            iter = int(kwargs.get("iter") or 0)

            fb_id = (
                _tensor_signature(fallback_image)
                if fallback_image is not None
                else "none"
            )

            if fallback_image is not None:
                return f"fallback_image::{fb_id}::rst::{iter}::{time.time_ns()}"

            dir_path = Path(directory).expanduser()

            files = _list_images(dir_path, pattern, recursive)
            files = list({p.resolve() for p in files if p.exists()})

            if not files:
                if fallback_path:
                    fp = Path(fallback_path).expanduser()
                    if fp.exists() and fp.is_file():
                        try:
                            return (
                                f"fallback::{fp}::{fp.stat().st_mtime_ns}::rst::{iter}"
                            )
                        except Exception:
                            pass
                try:
                    return f"empty::{dir_path.resolve()}::{dir_path.stat().st_mtime_ns}::rst::{iter}"
                except Exception:
                    return f"empty::{dir_path}::{time.time_ns()}::rst::{iter}"

            latest = _pick_most_recent(files, sort_by)
            ts = (
                latest.stat().st_mtime_ns
                if sort_by == "modified"
                else latest.stat().st_ctime_ns
            )
            return f"{latest}::{ts}::rst::{iter}"
        except Exception:
            return time.time_ns()

    @classmethod
    def _load_path(cls, p: Path):
        from PIL import Image

        img = Image.open(p)
        img.load()
        tensor = _pil_to_tensor(img)
        h, w = int(tensor.shape[1]), int(tensor.shape[2])
        ts = time.localtime(p.stat().st_mtime)
        mtime_str = time.strftime("%Y-%m-%d %H:%M:%S", ts)
        try:
            pos, neg = _extract_prompts(img)
        except Exception:
            pos, neg = "", ""
        return (tensor, str(p), w, h, mtime_str, pos, neg)

    @classmethod
    def _load_fallback_path(cls, fallback_path: str):
        p = Path(fallback_path).expanduser()
        if not p.exists() or not p.is_file():
            raise ValueError(f"fallback_path does not exist or is not a file: {p}")
        return cls._load_path(p)

    @classmethod
    def _load_fallback_image(cls, fallback_image):
        import torch

        t = fallback_image
        if t is None:
            raise ValueError("No images found and no fallback_image provided.")
        if not isinstance(t, torch.Tensor) or t.ndim != 4:
            raise ValueError("fallback_image must be a tensor of shape [B,H,W,C].")
        t = t[:1, ...]
        h, w = int(t.shape[1]), int(t.shape[2])
        return (t, "fallback:image_input", w, h, "N/A", "", "")

    @classmethod
    def execute(
        cls,
        directory,
        pattern=DEFAULT_PATTERN,
        recursive="false",
        sort_by="modified",
        fallback_path="",
        fallback_image=None,
        iter=0,
    ) -> io.NodeOutput:
        unique_id = cls.hidden.unique_id
        extra_pnginfo = cls.hidden.extra_pnginfo

        def _patch_workflow_counter(new_value):
            try:
                if unique_id is None or extra_pnginfo is None:
                    return
                if not isinstance(extra_pnginfo, list) or not extra_pnginfo:
                    return
                if (
                    not isinstance(extra_pnginfo[0], dict)
                    or "workflow" not in extra_pnginfo[0]
                ):
                    return
                workflow = extra_pnginfo[0]["workflow"]
                uid = (
                    unique_id[0] if isinstance(unique_id, (list, tuple)) else unique_id
                )
                for node in workflow.get("nodes", []):
                    if str(node.get("id")) == str(uid):
                        wv = node.get("widgets_values") or []
                        for i, v in enumerate(wv):
                            if (
                                isinstance(v, int)
                                and node.get("widgets", [{}])[i].get("name") == "iter"
                            ):
                                wv[i] = int(new_value)
                                break
                        node["widgets_values"] = wv
                        break
            except Exception:
                pass

        def _pick_from_directory():
            dir_path = Path(directory).expanduser()
            files = _list_images(dir_path, pattern, recursive == "true")
            files = list({p.resolve() for p in files})
            if not files:
                return None
            return str(_pick_most_recent(files, sort_by))

        def _load_from_directory_or_fallback():
            picked = _pick_from_directory()
            if picked is not None:
                return cls._load_path(Path(picked))
            if fallback_path.strip():
                return cls._load_fallback_path(fallback_path)
            return cls._load_fallback_image(fallback_image)

        key = _state_key(directory, pattern, recursive, sort_by, fallback_path)
        state = _load_persistent_state(key)

        history_paths = state.get("history", [])
        last_fb_sig = state.get("last_fb_sig")
        global_counter = state.get("global_counter", len(history_paths))
        user_idx = max(0, int(iter))

        import sys

        print(
            f"[LMR] rc={iter} ui={user_idx} gc={global_counter} hl={len(history_paths)} fb={fallback_image is not None}",
            file=sys.stderr,
            flush=True,
        )

        def _save_history(new_history, new_fb_sig, new_gc):
            state["history"] = new_history
            state["last_fb_sig"] = new_fb_sig
            state["global_counter"] = new_gc
            _save_persistent_state(key, state)

        if fallback_image is not None:
            current_fb_sig = _tensor_signature(fallback_image)

            if current_fb_sig != last_fb_sig:
                marker = f"fallback::{current_fb_sig}"
                history_paths = [marker]
                _save_history(history_paths, current_fb_sig, 1)
                _patch_workflow_counter(1)
                result = cls._load_fallback_image(fallback_image)
                return io.NodeOutput(*result, ui={"iter": [1]})

            if not history_paths:
                marker = f"fallback::{current_fb_sig}"
                history_paths = [marker]
                _save_history(history_paths, current_fb_sig, 1)
                _patch_workflow_counter(1)
                result = cls._load_fallback_image(fallback_image)
                return io.NodeOutput(*result, ui={"iter": [1]})

            if user_idx < len(history_paths):
                entry = history_paths[user_idx]
            else:
                picked = _pick_from_directory()
                if picked is None:
                    if fallback_path.strip():
                        entry = f"fallback_path::{fallback_path}"
                    else:
                        entry = f"fallback::{current_fb_sig}"
                else:
                    entry = picked

            history_paths.append(entry)
            new_gc = len(history_paths)
            _save_history(history_paths, current_fb_sig, new_gc)
            _patch_workflow_counter(new_gc)

            if entry.startswith("fallback::"):
                result = cls._load_fallback_image(fallback_image)
            elif entry.startswith("fallback_path::"):
                result = cls._load_fallback_path(entry[len("fallback_path::") :])
            else:
                result = cls._load_path(Path(entry))

            return io.NodeOutput(*result, ui={"iter": [new_gc]})

        _save_history(history_paths, last_fb_sig, global_counter)
        _patch_workflow_counter(global_counter)
        result = _load_from_directory_or_fallback()
        return io.NodeOutput(*result, ui={"iter": [global_counter]})


class LoadMostRecentImageExtension(ComfyExtension):
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return [LoadMostRecentImage]

    async def comfy_entrypoint(self):
        return self
