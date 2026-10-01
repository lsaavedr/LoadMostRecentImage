# Load Most Recent Image for ComfyUI

Loads the **newest image** (by modified or created timestamp) from a specified folder, with optional fallback handling.

It also tracks a **persistent history of resolved outputs** (paths only) per workflow configuration, indexed by an `iter` widget that auto-increments with every run.

Ideal for:

- Iterative workflows: "take my last output and upscale/inpaint it".
- Quickly testing new checkpoints/LoRAs on your most recent generation.
- Building review or comparison chains without manual file selection.
- Stepping back through past outputs while continuing to advance.

## Installation

1. Copy the `LoadMostRecentImage/` folder into your `ComfyUI/custom_nodes/` directory.
2. Restart ComfyUI or reload custom nodes.

The directory contains:

```
LoadMostRecentImage/
  __init__.py                    # Entry point: imports and registers the node
  nodes.py                       # Node implementation (helpers, LoadMostRecentImage class)
  web/
    node/
      LoadMostRecentImage.js     # Frontend extension to update the iter widget and trigger partial execution
```

No external Python dependencies beyond core ComfyUI and PIL (already included).

## Inputs

| Name | Type | Description |
|------|------|-------------|
| `directory` | `STRING` (required) | Folder to scan (absolute or relative, supports `~`). |
| `pattern` | `STRING` (optional) | Regex filter for filenames. Default: common image extensions. |
| `recursive` | `true`/`false` | Scan subfolders (default `false`). |
| `sort_by` | `modified`/`created` | Use modified or creation time (default `modified`). |
| `fallback_image` | `IMAGE` (optional) | Direct image tensor fallback. Triggers history tracking when connected. |
| `iter` | `INT` (optional) | Index into the output history. Auto-increments each run. |

## Outputs

| Name | Type | Description |
|------|------|-------------|
| `image` | `IMAGE` | The loaded image as a standard ComfyUI tensor. |
| `path` | `STRING` | Full path of the loaded file, or `fallback:image_input` for tensor fallback. |
| `width` | `INT` | Image width. |
| `height` | `INT` | Image height. |
| `mtime` | `STRING` | Human-readable modified timestamp, or `N/A` for tensor fallback. |

## Fallback Chain

When the configured directory is empty:

1. **`fallback_image`** (if connected): return this tensor.
2. Otherwise, raise an error.

## Output History and `iter`

When `fallback_image` is connected, the node keeps a **persistent history of resolved outputs** for the current workflow configuration (directory + pattern + recursive + sort_by). Each run appends one entry and `iter` auto-increments to `len(history)`.

State is stored at `/root/.cache/comfyui_load_most_recent_image/<key>.json`, where `<key>` is an md5 hash of the configuration. Only paths are stored, never tensors or pixel data.

History entries can be:

- `fallback::<tensor_signature>` — the current `fallback_image` input tensor.
- `/abs/path/to/file.png` — an image file picked from the directory.

### Behavior

- **First run with a new tensor**: `iter` becomes `1`, history starts with `[fallback::<tensor_signature>]`.
- **Subsequent runs with the same tensor**: `iter` auto-increments by 1, history grows with each resolved output.
- **Tensor changes**: history resets to `[fallback::<new_tensor_signature>]`, counter becomes `1`.
- **Manual override**: you can drag `iter` down to look back at a previous entry. On the next run, the widget will auto-increment again to the latest position.

The frontend extension `web/node/LoadMostRecentImage.js` updates the widget value automatically after each execution, and uses ComfyUI's partial execution API to re-run only this node (not the whole workflow) when `iter` is changed manually — so the connected `PreviewImage` (or any downstream node) updates live without re-running the full pipeline.

If the widget doesn't update visually in your frontend, the backend behavior is still correct (check `[LMR]` lines in the ComfyUI logs).

## Caching

`IS_CHANGED` returns a unique value whenever the directory contents, fallback path, fallback image signature, or counter change. When `fallback_image` is connected, it always returns a timestamped value to ensure re-execution on every run.

## Example Use Cases

- Connect to an Upscale or Inpaint node → instantly process your latest output.
- Chain multiple: load most recent → apply variation → save → repeat.
- Step backward through your iteration history while continuing to advance with the same upstream tensor.

## State Location

The persistent state JSON files live at:

```
/root/.cache/comfyui_load_most_recent_image/
```

Delete this directory to clear all histories.
