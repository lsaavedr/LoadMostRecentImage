# Load Most Recent Image for ComfyUI

![Lint, format and tests](https://github.com/lsaavedr/LoadMostRecentImage/actions/workflows/tests.yml/badge.svg)

Loads the **newest image** from a specified folder, with optional fallback
handling.

It also keeps a **persistent history of resolved outputs** (paths only) per
workflow configuration, which the `iter` widget advances through.

Ideal for:

- Iterative workflows: "take my last output and upscale/inpaint it".
- Quickly testing new checkpoints/LoRAs on your most recent generation.
- Building review or comparison chains without manual file selection.
- Stepping back through past outputs while continuing to advance.

## Installation

### Manual

1. Copy the `LoadMostRecentImage/` folder into your `ComfyUI/custom_nodes/` directory.
2. Restart ComfyUI or reload custom nodes.

Nothing to install by hand: `aiohttp`, `numpy`, `pillow` and `torch` are all
already in ComfyUI's requirements.

### Development

Requires Python 3.12 or newer (the floor is set by `numpy`), and `uv`.

```bash
git clone <repo-url>
cd LoadMostRecentImage
uv sync --locked
```

## Project Structure

```
LoadMostRecentImage/
├── __init__.py                  # Entry point: registers the extension and its routes
├── nodes.py                     # Node implementation (LoadMostRecentImage class)
├── utils/
│   ├── file.py                  # Image discovery, loading, and tensor conversion
│   ├── history.py               # Persistent history state management
│   ├── state.py                 # JSON state persistence (atomic writes)
│   └── tensor.py                # Tensor signature and fallback preparation
├── web/node/
│   ├── LoadMostRecentImage.js           # Registers the extension with ComfyUI
│   └── LoadMostRecentImage.extension.js # The extension itself (widget sync, history reset)
├── tests/                       # Python suite; a package, so it imports the plugin
│   │                             as `LoadMostRecentImage.*`, the way ComfyUI does
│   ├── conftest.py              # Fixtures (isolated state dir per test)
│   ├── stubs/                   # Stubs for comfy_api and server (neither on PyPI)
│   ├── test_extension_init.py   # Entrypoint, route registration
│   ├── test_file.py
│   ├── test_history.py
│   ├── test_nodes.py            # execute(), fingerprint_inputs(), define_schema()
│   ├── test_python_compat.py    # Parses every source against the minimum Python
│   ├── test_state.py
│   └── test_tensor.py
├── tests-js/                    # Web extension suite (node:test)
├── .github/workflows/tests.yml  # CI
├── .prettierrc                  # Formatting rules for the JS
├── package.json                 # npm scripts: test, format, format:check
├── pyproject.toml               # Metadata, dependencies, ruff/coverage/pytest config
└── uv.lock                      # Locked dependency versions
```

## Dependencies

- **Runtime**: `aiohttp`, `numpy`, `pillow`, `torch` (the last three ship with ComfyUI)
- **Dev**: `pytest`, `pytest-cov`, `ruff`
- **Web**: `prettier`, for `npm run format:check`

## Running Tests

```bash
uv run pytest      # 154 tests
npm test           # 24 tests, with 100% coverage enforced
npm run format:check
```

Both suites enforce 100% line, branch and function coverage of the plugin's own
source, and fail if it drops. The Python suite runs in an isolated state
directory; the JS suite stubs ComfyUI's `app` and `graph`.

Coverage is measured over `nodes.py`, `__init__.py` and `utils/` — not just
`utils/`, because the node modules load under the `LoadMostRecentImage.*`
package name and would otherwise go unmeasured.

## Inputs

| Name | Type | Description |
|------|------|-------------|
| `directory` | `STRING` (required) | Folder to scan (absolute or relative, supports `~`). |
| `pattern` | `STRING` (optional) | Regex filter for filenames. Default: common image extensions. |
| `recursive` | `true`/`false` | Scan subfolders (default `false`). |
| `sort_by` | `modified`/`created` | Which timestamp decides "newest" (default `modified`). See below. |
| `fallback_image` | `IMAGE` (optional) | Direct image tensor fallback. Triggers history tracking when connected. |
| `iter` | `INT` (optional) | Position in the output history. Starts at 1. |

## Outputs

| Name | Type | Description |
|------|------|-------------|
| `image` | `IMAGE` | The loaded image as a standard ComfyUI tensor. |
| `path` | `STRING` | Full path of the loaded file, or `fallback:image_input` for tensor fallback. |
| `width` | `INT` | Image width. |
| `height` | `INT` | Image height. |
| `mtime` | `STRING` | Human-readable modified timestamp, or `N/A` for tensor fallback. |

## Fallback Chain

When the configured directory holds no matching image:

1. **`fallback_image`** (if connected): return this tensor.
2. Otherwise, raise a `ValueError` naming the pattern and directory.

## Output History and `iter`

When `fallback_image` is connected, the node keeps a **persistent history of
resolved outputs** for the current workflow configuration (directory + pattern
+ recursive + sort_by). Each run appends one entry.

The history is **append-ordered**, so `iter` 0 is the *oldest* entry: the
`fallback_image` tensor as it was when it last changed. The widget **starts at
1**, just past that entry, so the counts below run upward without a jump.

| Event | `iter` becomes | history |
|---|---|---|
| starts at | 1 | — |
| First run with a new tensor | 2 | `[fallback::<sig>]` |
| Next run, same tensor | 3 | `[fallback::<sig>, /path/img.png]` |
| `iter` dragged back to 0 | 3 | unchanged — the entry is replayed, not appended |
| `fallback_image` changes | 2 | `[fallback::<new_sig>]` |

After each run the node writes `len(history) + 1` back to the widget, so
queueing again records the next entry. Dragging `iter` back replays an older
entry without growing the history; the widget returns to the end afterwards.

History entries are either:

- `fallback::<tensor_signature>` — the current `fallback_image` tensor
- `/abs/path/to/file.png` — an image picked from the directory

Only paths are stored, never tensors or pixel data.

The tensor signature is a hash of shape, dtype and the whole tensor narrowed to
one byte per element, so it is stable across processes and across freshly
allocated tensors with unchanged content. Narrowing to uint8 reads every
element at a quarter of the bytes a float32 copy would move, and it is the one
representation every dtype can reach: bfloat16 and the float8 family have no
numpy equivalent, so `.numpy()` raises on them. The original dtype is still
part of the hash, so a narrowed bfloat16 cannot collide with a float32.

## `sort_by`

`modified` uses `st_mtime`. `created` uses `st_ctime`.

On Linux, `st_ctime` is **not** a creation time: it is the inode change time,
which moves when a file is renamed, chmod'd, or hard-linked. A true birth time
would need `statx`, which this node does not use. If you want "the image I
just generated", leave this on `modified`.

When several files share the same timestamp, the **path** decides, so the
choice is stable across restarts. Without that tiebreak the node returned a
different image on every launch, since the candidates are deduplicated through
a set whose iteration order Python randomises per process. Ties are routine
after an `rsync -t`, a `git checkout` of images, or on a filesystem with
one-second timestamps.

## Caching

`fingerprint_inputs` (ComfyUI's input-cache hook) keys on the newest matching
file and its timestamp, or on the `fallback_image` signature plus `iter`.
While a `fallback_image` is connected it also folds in a timestamp, so the node
re-executes on every queue rather than being served from cache.

The key always describes the image the node actually returns — switching
`sort_by` re-runs the node and changes which file is picked, rather than
invalidating the cache to produce the same result.

## State Location

State lives in a per-node JSON file, one per workflow configuration, named by
an md5 of `directory + pattern + recursive + sort_by`. The directory is
resolved in this order:

1. `$LMRI_STATE_DIR`, if set
2. `$XDG_STATE_HOME/comfyui_load_most_recent_image/`
3. `~/.local/state/comfyui_load_most_recent_image/`

```bash
export LMRI_STATE_DIR=/path/to/custom/state/dir
```

There is one file per configuration and nothing prunes them; reloading the
workflow clears all of them, which is why they do not accumulate in practice.

## History Is Cleared on Workflow Reload

Loading a workflow is a new session, so the frontend posts to
`/load_most_recent_image/clear_history`, which deletes every persisted state
file and resets `iter` to 1. A node whose history you want to survive needs the
workflow to stay open.

The route answers `500` with `{"status": "error"}` if the sweep did not
finish — a read-only state directory, for instance — and the frontend warns in
the browser console, because `fetch` does not throw on an HTTP error status.
The widget still resets to `1` either way, so after a failed clear the history
on disk is older than the widget suggests and the next run appends to it.

The route is a no-op if ComfyUI's `PromptServer` is not present, so importing
the package outside ComfyUI does not fail. Nothing retries the registration,
so that case logs a warning naming the path that will not respond.

## Known Limitations

- History entries are absolute paths and are not pruned. If an image is deleted
  and you drag `iter` onto that entry, the node raises `FileNotFoundError`.
- `created` means inode-change time on Linux, not creation time.
- `fingerprint_inputs` falls back to a timestamp on any error, so an
  unreadable directory re-runs the node rather than failing.
- A `pattern` is matched against the filename only, so a pattern containing a
  `/` never matches, not even with `recursive` on. Match on the name and use
  `recursive` to widen the search.
- A failed `clear_history` resets `iter` to 1 without resetting the history on
  disk; see above.

## CI

`.github/workflows/tests.yml` runs on push and pull requests to `master`, and
on manual dispatch:

- **`Python 3.12` / `Python 3.14`** — matrixed legs: `uv sync --locked`, ruff,
  then pytest with the coverage gate
- **`Web extension`** — Node 24: `npm ci`, `npm run format:check`, then `npm test`

Both run on `ubuntu-26.04`, pinned rather than `ubuntu-latest` so the image
change is a commit instead of a surprise. A run is titled with its HEAD commit
message, so pushing several commits at once produces one run named after the
last of them.

## Example Use Cases

- Connect to an Upscale or Inpaint node → instantly process your latest output.
- Chain multiple: load most recent → apply variation → save → repeat.
- Step backward through your iteration history while continuing to advance with
  the same upstream tensor.