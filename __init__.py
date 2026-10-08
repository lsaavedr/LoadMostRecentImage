import logging

import server
from aiohttp import web
from comfy_api.latest import ComfyExtension, io

from .nodes import LoadMostRecentImage
from .utils.file import DEFAULT_PATTERN
from .utils.history import make_state_key
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
        configs = await _requested_configs(request)

        # Clearing every configuration wiped the history of workflows the user
        # never touched: opening file B after working on A destroyed A. The
        # frontend sends the configurations of the graph it just loaded, so
        # loading B clears B and leaves A alone.
        keys = [
            make_state_key(
                c.get("directory", ""),
                c.get("pattern", DEFAULT_PATTERN),
                c.get("recursive", "false"),
                c.get("sort_by", "modified"),
            )
            for c in configs
        ]
        cleared = clear_persistent_states(keys or None)

        # Report the real outcome: the frontend resets the iter widget either
        # way, so a silent failure leaves it claiming 1 while the old history
        # is still on disk and the next run appends to it.
        return web.json_response(
            {"status": "ok" if cleared else "error"},
            status=200 if cleared else 500,
        )


async def _requested_configs(request) -> list[dict]:
    """The configurations the frontend asked us to clear.

    A body that cannot be read is treated as "clear everything", which is what
    this endpoint did before it learned to scope itself: a malformed request
    from an older frontend should not silently leave stale history behind.
    """
    try:
        payload = await request.json()
        configs = payload.get("configs")
    except (ValueError, TypeError, AttributeError) as exc:
        # aiohttp raises ContentTypeError (a ValueError) for a non-JSON body.
        logger.warning("clear_history: unreadable body, sweeping everything: %s", exc)
        return []
    if not isinstance(configs, list):
        return []
    return [c for c in configs if isinstance(c, dict)]


WEB_DIRECTORY = "./web"
