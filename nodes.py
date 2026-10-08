import logging
import time
from pathlib import Path

from comfy_api.latest import io

from .utils.file import (
    DEFAULT_PATTERN,
    list_images,
    load_image_with_metadata,
    pick_latest_image,
    pick_most_recent,
)
from .utils.history import HistoryState, is_fallback_marker, make_state_key
from .utils.tensor import prepare_fallback_tensor, tensor_signature

logger = logging.getLogger(__name__)


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
                io.Image.Input("fallback_image", optional=True),
                io.Int.Input(
                    "iter",
                    default=1,
                    min=0,
                    max=1000000,
                    step=1,
                    tooltip="Position in the fallback_image history, which gains one entry per run.\n"
                    "The history is append-ordered, so 0 is the oldest entry: the tensor\n"
                    "as it was when it last changed. It starts at 1, just past that entry,\n"
                    "so the first run records the newest matching image. An index at or\n"
                    "past the end records the newest image as a new entry, and after each\n"
                    "run this widget moves to the new end.\n"
                    "Changing the fallback_image tensor resets the history.",
                    optional=True,
                ),
            ],
            outputs=[
                io.Image.Output(display_name="image"),
                io.String.Output(display_name="path"),
                io.Int.Output(display_name="width"),
                io.Int.Output(display_name="height"),
                io.String.Output(display_name="mtime"),
            ],
        )

    @classmethod
    def fingerprint_inputs(cls, **kwargs):
        try:
            directory = (kwargs.get("directory") or "").strip()
            pattern = (kwargs.get("pattern") or DEFAULT_PATTERN).strip()
            recursive = (kwargs.get("recursive") or "false") == "true"
            sort_by = (kwargs.get("sort_by") or "modified").strip()
            fallback_image = kwargs.get("fallback_image")
            iter = int(kwargs.get("iter") or 0)

            fb_id = (
                tensor_signature(fallback_image)
                if fallback_image is not None
                else "none"
            )

            if fallback_image is not None:
                return f"fallback_image::{fb_id}::rst::{iter}::{time.time_ns()}"

            dir_path = Path(directory).expanduser()

            files = list_images(dir_path, pattern, recursive)
            files = list({p.resolve() for p in files if p.exists()})

            if not files:
                try:
                    return f"empty::{dir_path.resolve()}::{dir_path.stat().st_mtime_ns}::rst::{iter}"
                except OSError:
                    return f"empty::{dir_path}::{time.time_ns()}::rst::{iter}"

            latest = pick_most_recent(files, sort_by)
            ts = (
                latest.stat().st_mtime_ns
                if sort_by == "modified"
                else latest.stat().st_ctime_ns
            )
            return f"{latest}::{ts}::rst::{iter}"
        except Exception:
            # Deliberately broad: this function must be total. ComfyUI calls it
            # to decide whether it can reuse a cached result, so the only safe
            # failure mode is "return a fresh key". Raising would break the
            # execution loop, not just this node. The log keeps it diagnosable.
            logger.exception("fingerprint_inputs failed; using a fresh cache key")
            return time.time_ns()

    @classmethod
    def execute(
        cls,
        directory,
        pattern=DEFAULT_PATTERN,
        recursive="false",
        sort_by="modified",
        fallback_image=None,
        iter=1,
    ) -> io.NodeOutput:
        user_idx = max(0, int(iter))

        key = make_state_key(directory, pattern, recursive, sort_by)
        state = HistoryState.load(key)

        if fallback_image is not None:
            current_sig = tensor_signature(fallback_image)

            if current_sig != state.last_fb_sig or not state.history:
                state.reset_for_tensor(current_sig)
                result = prepare_fallback_tensor(fallback_image)

                assert result is not None
                return io.NodeOutput(*result, ui={"iter": [len(state.history) + 1]})

            if user_idx < len(state.history):
                entry = state.history[user_idx]
            else:
                entry = state.pick_new_entry(
                    lambda: pick_latest_image(
                        directory, pattern, recursive == "true", sort_by
                    ),
                    current_sig,
                )
                state.append_entry(entry, current_sig)

            result = (
                prepare_fallback_tensor(fallback_image)
                if is_fallback_marker(entry)
                else load_image_with_metadata(Path(entry))
            )

            assert result is not None
            return io.NodeOutput(*result, ui={"iter": [len(state.history) + 1]})

        # `fallback_image is None` here: the branch above returns on every path.
        picked = pick_latest_image(directory, pattern, recursive == "true", sort_by)
        if picked is None:
            raise ValueError(
                f"No image matched {pattern!r} in {directory!r}. "
                "Connect the optional fallback_image input, or loosen the pattern."
            )

        result = load_image_with_metadata(Path(picked))
        return io.NodeOutput(*result, ui={"iter": [len(state.history) + 1]})
