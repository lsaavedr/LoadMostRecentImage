import ast
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# ComfyUI runs on whatever Python the user has, not the one pinned for dev.
# This is the floor: `numpy` declares `Requires-Python: >=3.12`.
MIN_PYTHON = (3, 12)


def _plugin_sources() -> list[Path]:
    return [
        PROJECT_ROOT / "__init__.py",
        PROJECT_ROOT / "nodes.py",
        *sorted((PROJECT_ROOT / "utils").glob("*.py")),
    ]


@pytest.mark.parametrize(
    "source", _plugin_sources(), ids=lambda p: p.relative_to(PROJECT_ROOT).as_posix()
)
def test_source_parses_on_minimum_python(source):
    """Guard against syntax newer than MIN_PYTHON (e.g. PEP 758 bare `except A, B`).

    Dev and CI run 3.14, where that syntax is valid, so nothing else would
    catch it -- but it is a SyntaxError for users on older ComfyUI setups,
    and it would break the node at import time.
    """
    tree = ast.parse(source.read_text(encoding="utf-8"), feature_version=MIN_PYTHON)

    assert tree is not None
