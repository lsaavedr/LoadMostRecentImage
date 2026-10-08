import asyncio
import inspect
import pathlib

import pytest
import server
from PIL import Image

from .. import LoadMostRecentImageExtension, comfy_entrypoint
from ..nodes import LoadMostRecentImage
from ..utils import state as pkg_state
from ..utils.history import make_state_key


def test_package_exposes_entrypoint():
    """ComfyUI calls `comfy_entrypoint` on the package root and expects the extension."""
    assert inspect.iscoroutinefunction(comfy_entrypoint)

    extension = asyncio.run(comfy_entrypoint())
    assert isinstance(extension, LoadMostRecentImageExtension)


def test_extension_advertises_the_node():
    nodes = asyncio.run(LoadMostRecentImageExtension().get_node_list())

    assert nodes == [LoadMostRecentImage]


def test_comfy_entrypoint_tolerates_missing_prompt_server(monkeypatch, caplog):
    """Standalone imports (no ComfyUI server) must not break the entrypoint."""
    monkeypatch.setattr(server.PromptServer, "instance", None)

    with caplog.at_level("WARNING"):
        extension = asyncio.run(comfy_entrypoint())

    assert isinstance(extension, LoadMostRecentImageExtension)
    # Nothing retries the registration, so staying quiet here would leave the
    # frontend on a 404 for the whole session with no explanation anywhere.
    assert "clear_history is not registered" in caplog.text


def _handler():
    asyncio.run(comfy_entrypoint())
    return server.PromptServer.instance.routes.handlers[
        "/load_most_recent_image/clear_history"
    ]


class _Body:
    """Stands in for the aiohttp request, answering `json()` only."""

    def __init__(self, payload=None, boom=None):
        self._payload = payload
        self._boom = boom

    async def json(self):
        if self._boom is not None:
            raise self._boom
        return self._payload


def _key(directory, pattern=None, recursive="false", sort_by="modified"):
    """The key `execute` computes for a node with these settings.

    `pattern` defaults to the schema default, so a config dict that simply
    omits the optional widget produces the same key the node will write.
    """
    from ..utils.file import DEFAULT_PATTERN

    return make_state_key(
        directory,
        DEFAULT_PATTERN if pattern is None else pattern,
        recursive,
        sort_by,
    )


def test_clear_history_route_deletes_state(monkeypatch, tmp_path):
    monkeypatch.setattr(pkg_state, "STATE_DIR", tmp_path)

    pkg_state.save_persistent_state("k", {"history": ["a"]})
    assert pkg_state.state_path("k").exists()

    response = asyncio.run(_handler()(None))

    assert response.status == 200
    assert not pkg_state.state_path("k").exists()


def test_working_on_one_workflow_survives_opening_another(monkeypatch, tmp_path):
    """The scenario this change exists for, end to end.

    Work up a history on workflow A, then load workflow B. B's frontend posts
    only B's configuration, so A must still be there when the user goes back.
    Before this, the route swept the whole state directory and A was gone.
    """
    monkeypatch.setattr(pkg_state, "STATE_DIR", tmp_path)
    torch = pytest.importorskip("torch")
    image = Image.new("RGB", (4, 2), (255, 0, 0))
    tensor = torch.rand(1, 4, 2, 3)

    dir_a = tmp_path / "A"
    dir_a.mkdir()
    image.save(dir_a / "x.png")
    dir_b = tmp_path / "B"
    dir_b.mkdir()
    image.save(dir_b / "y.png")

    # five runs on workflow A
    for i in range(1, 6):
        LoadMostRecentImage.execute(directory=str(dir_a), fallback_image=tensor, iter=i)

    key_a = _key(str(dir_a))
    worked = len(pkg_state.load_persistent_state(key_a)["history"])
    assert worked > 1, "workflow A should have accumulated history"

    # the user opens workflow B: one run there, then its frontend posts B
    LoadMostRecentImage.execute(directory=str(dir_b), fallback_image=tensor, iter=1)
    body = _Body({"configs": [{"directory": str(dir_b)}]})
    assert asyncio.run(_handler()(body)).status == 200

    assert len(pkg_state.load_persistent_state(key_a)["history"]) == worked


def test_clear_history_only_touches_the_asked_configurations(monkeypatch, tmp_path):
    """Opening workflow B must not destroy the history of workflow A.

    This was the whole point of sending the configurations with the request:
    the endpoint used to sweep every state file, so loading a second workflow
    wiped the first one the user had been working in.
    """
    monkeypatch.setattr(pkg_state, "STATE_DIR", tmp_path)

    mine = _key("/work/uno")
    theirs = _key("/work/dos")
    pkg_state.save_persistent_state(mine, {"history": ["a"]})
    pkg_state.save_persistent_state(theirs, {"history": ["b"]})

    body = _Body({"configs": [{"directory": "/work/dos"}]})
    response = asyncio.run(_handler()(body))

    assert response.status == 200
    assert not pkg_state.state_path(theirs).exists()
    assert pkg_state.state_path(mine).exists()


def test_clear_history_keys_match_what_execute_computes(monkeypatch, tmp_path):
    """The route derives keys the same way `execute` does.

    If the two ever disagreed the route would delete a file the node never
    wrote, and the history it was meant to reset would survive -- so the key is
    built by the same function, and this pins that the round trip works for the
    non-default values too.
    """
    monkeypatch.setattr(pkg_state, "STATE_DIR", tmp_path)

    config = {
        "directory": "/work/tres",
        "pattern": r".*\.png$",
        "recursive": "true",
        "sort_by": "created",
    }
    written = _key(
        config["directory"], config["pattern"], config["recursive"], config["sort_by"]
    )
    pkg_state.save_persistent_state(written, {"history": ["a"]})

    response = asyncio.run(_handler()(_Body({"configs": [config]})))

    assert response.status == 200
    assert not pkg_state.state_path(written).exists()


def test_clear_history_defaults_absent_widget_values(monkeypatch, tmp_path):
    """A node missing an optional widget sends no value for it.

    The defaults have to be `execute`'s defaults, or the computed key would
    name a file the node never wrote and the real history would survive.
    """
    monkeypatch.setattr(pkg_state, "STATE_DIR", tmp_path)

    pkg_state.save_persistent_state(_key("/work/cuatro"), {"history": ["a"]})

    body = _Body({"configs": [{"directory": "/work/cuatro"}]})

    assert asyncio.run(_handler()(body)).status == 200
    assert not pkg_state.state_path(_key("/work/cuatro")).exists()


def test_clear_history_with_no_nodes_sweeps_everything(monkeypatch, tmp_path):
    """A graph with no LoadMostRecentImage node has no configurations to name.

    Falling back to a full sweep keeps the pre-existing behaviour for that case
    instead of leaving history that no loaded graph claims.
    """
    monkeypatch.setattr(pkg_state, "STATE_DIR", tmp_path)
    pkg_state.save_persistent_state("k", {"history": ["a"]})

    response = asyncio.run(_handler()(_Body({"configs": []})))

    assert response.status == 200
    assert not pkg_state.state_path("k").exists()


def test_clear_history_sweeps_everything_on_an_unreadable_body(
    monkeypatch, tmp_path, caplog
):
    """An older frontend posts no body at all.

    Reading it fails, and the response must not be "fine, nothing cleared" --
    that would look like a reset while quietly leaving stale history behind.
    """
    monkeypatch.setattr(pkg_state, "STATE_DIR", tmp_path)
    pkg_state.save_persistent_state("k", {"history": ["a"]})

    body = _Body(boom=ValueError("not json"))
    with caplog.at_level("WARNING"):
        response = asyncio.run(_handler()(body))

    assert response.status == 200
    assert not pkg_state.state_path("k").exists()
    assert "sweeping everything" in caplog.text


@pytest.mark.parametrize("payload", [{}, {"configs": "nope"}, {"configs": ["x", 3]}])
def test_clear_history_ignores_a_body_it_cannot_use(monkeypatch, tmp_path, payload):
    """Whatever the shape, the sweep either happens or it does not -- it never
    half-deletes."""
    monkeypatch.setattr(pkg_state, "STATE_DIR", tmp_path)
    pkg_state.save_persistent_state("k", {"history": ["a"]})

    response = asyncio.run(_handler()(_Body(payload)))

    assert response.status == 200
    assert not pkg_state.state_path("k").exists()


def test_clear_history_route_reports_a_failed_sweep(monkeypatch, tmp_path):
    """A clear that did not happen must not answer 200.

    The frontend resets the iter widget whether or not this succeeds, so an
    unconditional ok leaves the widget at 1 while the old history is still
    persisted and the next run appends to it instead of starting clean.
    """
    monkeypatch.setattr(pkg_state, "STATE_DIR", tmp_path)
    # Seeded on purpose: an empty directory never attempts a delete, so the
    # sweep would succeed for the wrong reason and the patch would be dead.
    pkg_state.save_persistent_state("k", {"history": ["a"]})
    asyncio.run(comfy_entrypoint())

    def boom(self, **kwargs):
        raise OSError("Read-only file system")

    monkeypatch.setattr(pathlib.Path, "unlink", boom)
    handler = server.PromptServer.instance.routes.handlers[
        "/load_most_recent_image/clear_history"
    ]
    response = asyncio.run(handler(None))

    assert response.status == 500
    assert pkg_state.state_path("k").exists()
