import asyncio
import inspect

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
