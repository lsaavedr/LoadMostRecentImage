import logging

import server
from aiohttp import web
from comfy_api.latest import ComfyExtension, io

from .nodes import LoadMostRecentImage
from .utils.state import clear_persistent_states

logger = logging.getLogger(__name__)


class LoadMostRecentImageExtension(ComfyExtension):
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return [LoadMostRecentImage]


async def comfy_entrypoint() -> LoadMostRecentImageExtension:
    _register_routes()
    return LoadMostRecentImageExtension()


def _register_routes() -> None:
    instance = getattr(server.PromptServer, "instance", None)
    if instance is None:
        # Nothing retries this, so the route would be missing for the rest of
        # the process and every graph load would 404 without a word about why.
        logger.warning(
            "PromptServer.instance is not available, so "
            "/load_most_recent_image/clear_history is not registered"
        )
        return

    routes = instance.routes

    @routes.post("/load_most_recent_image/clear_history")
    async def _clear_history_route(request):
        cleared = clear_persistent_states()
        # Report the real outcome: the frontend resets the iter widget either
        # way, so a silent failure leaves it claiming 1 while the old history
        # is still on disk and the next run appends to it.
        return web.json_response(
            {"status": "ok" if cleared else "error"},
            status=200 if cleared else 500,
        )


WEB_DIRECTORY = "./web"
