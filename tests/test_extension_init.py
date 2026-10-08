import asyncio
import inspect
import pathlib

import server

from .. import LoadMostRecentImageExtension, comfy_entrypoint
from ..nodes import LoadMostRecentImage
from ..utils import state as pkg_state


def test_package_exposes_entrypoint():
    """ComfyUI calls `comfy_entrypoint` on the package root and expects the extension."""
    assert inspect.iscoroutinefunction(comfy_entrypoint)

    extension = asyncio.run(comfy_entrypoint())
    assert isinstance(extension, LoadMostRecentImageExtension)


def test_extension_advertises_the_node():
    nodes = asyncio.run(LoadMostRecentImageExtension().get_node_list())

    assert nodes == [LoadMostRecentImage]


def test_comfy_entrypoint_tolerates_missing_prompt_server(monkeypatch):
    """Standalone imports (no ComfyUI server) must not break the entrypoint."""
    monkeypatch.setattr(server.PromptServer, "instance", None)

    extension = asyncio.run(comfy_entrypoint())

    assert isinstance(extension, LoadMostRecentImageExtension)


def test_clear_history_route_deletes_state(monkeypatch, tmp_path):
    monkeypatch.setattr(pkg_state, "STATE_DIR", tmp_path)

    pkg_state.save_persistent_state("k", {"history": ["a"]})
    assert pkg_state.state_path("k").exists()

    # Routes are registered inside comfy_entrypoint.
    asyncio.run(comfy_entrypoint())

    handler = server.PromptServer.instance.routes.handlers[
        "/load_most_recent_image/clear_history"
    ]
    response = asyncio.run(handler(None))

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
