# Load Most Recent Image for ComfyUI

Loads the **newest image** (by modified or created timestamp) from a specified folder, with optional fallback handling and **automatic prompt extraction** from embedded ComfyUI metadata.

It also tracks a **persistent history of resolved outputs** (paths only) per workflow configuration, indexed by a `reset_counter` widget that auto-increments with every run.

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
  __init__.py                    # Node code
  web/
    js/
      LoadMostRecentImage.js     # Frontend extension to update the counter widget
```

No external Python dependencies beyond core ComfyUI and PIL (already included).

## Inputs

| Name | Type | Description |
|------|------|-------------|
| `directory` | `STRING` (required) | Folder to scan (absolute or relative, supports `~`). |
| `pattern` | `STRING` (optional) | Regex filter for filenames. Default: common image extensions. |
| `recursive` | `true`/`false` | Scan subfolders (default `false`). |
| `sort_by` | `modified`/`created` | Use modified or creation time (default `modified`). |
| `fallback_path` | `STRING` (optional) | Specific file to load if nothing is found in the directory. |
| `fallback_image` | `IMAGE` (optional) | Direct image tensor fallback. Triggers history tracking when connected. |
| `reset_counter` | `INT` (optional) | Index into the output history. Auto-increments each run. |

## Outputs

| Name | Type | Description |
|------|------|-------------|
| `image` | `IMAGE` | The loaded image as a standard ComfyUI tensor. |
| `path` | `STRING` | Full path of the loaded file (or `fallback:image_input` for tensor fallback). |
| `width` | `INT` | Image width. |
| `height` | `INT` | Image height. |
| `mtime` | `STRING` | Human-readable modified timestamp (or `N/A` for tensor fallback). |
| `positive_prompt` | `STRING` | Extracted from PNG tEXt chunk if present. |
| `negative_prompt` | `STRING` | Extracted from PNG tEXt chunk if present. |

## Fallback Chain

When the configured directory is empty:

1. **`fallback_path`** (if set): load the file at this path.
2. **`fallback_image`** (if connected): return this tensor.
3. Otherwise, raise an error.

## Output History and `reset_counter`

When `fallback_image` is connected, the node keeps a **persistent history of resolved outputs** for the current workflow configuration (directory + pattern + recursive + sort_by + fallback_path). Each run appends one entry and `reset_counter` auto-increments to `len(history)`.

State is stored at `/root/.cache/comfyui_load_most_recent_image/<key>.json` where `<key>` is an md5 hash of the configuration. Only paths are stored, never tensors or pixel data.

### Behavior

- **First run with a new tensor**: `reset_counter` becomes `1`, history starts with `[fallback::<tensor_signature>]`.
- **Subsequent runs with the same tensor**: `reset_counter` auto-increments by 1, history grows with each resolved output.
- **Tensor changes**: history resets to `[fallback::<new_tensor_signature>]`, counter becomes `1`.
- **Manual override**: you can drag `reset_counter` down to look back at a previous entry. On the next run, the widget will auto-increment again to the latest position.

The frontend extension `web/js/LoadMostRecentImage.js` updates the widget value automatically after each execution. If the widget doesn't update visually in your frontend, the backend behavior is still correct (check `[LMR]` lines in the ComfyUI logs).

## Prompt Extraction

The node extracts positive/negative prompts from the loaded image in this order:

1. **ComfyUI JSON** in the PNG `prompt` text chunk (traces `CLIPTextEncode` nodes feeding the `KSampler`).
2. **AUTOMATIC1111** `parameters` block (parses `Negative prompt:` sections).
3. **Simple prompt keys** (`prompt`, `positive`, etc.).
4. **JPEG EXIF** fallbacks (UserComment and XPComment tags).

## Caching

`IS_CHANGED` returns a unique value whenever the directory contents, fallback path, fallback image signature, or counter change. When `fallback_image` is connected, it always returns a timestamped value to ensure re-execution on every run.

## Example Use Cases

- Connect to an Upscale or Inpaint node → instantly process your latest output.
- Chain multiple: load most recent → apply variation → save → repeat.
- Review loop: load recent → preview → tweak prompts based on extracted text.
- Step backward through your iteration history while continuing to advance with the same upstream tensor.

## State Location

The persistent state JSON files live at:

```
/root/.cache/comfyui_load_most_recent_image/
```

Delete this directory to clear all histories.

Perfect companion for Save Image nodes in iterative generation.
