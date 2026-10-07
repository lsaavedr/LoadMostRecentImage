import server
from aiohttp import web
from comfy_api.latest import ComfyExtension, io

from .nodes import LoadMostRecentImage
from .utils.state import clear_persistent_states


class LoadMostRecentImageExtension(ComfyExtension):
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return [LoadMostRecentImage]


async def comfy_entrypoint() -> LoadMostRecentImageExtension:
    _register_routes()
    return LoadMostRecentImageExtension()


def _register_routes() -> None:
    instance = getattr(server.PromptServer, "instance", None)
    if instance is None:
        return

    routes = instance.routes

    @routes.post("/load_most_recent_image/clear_history")
    async def _clear_history_route(request):
        clear_persistent_states()
        return web.json_response({"status": "ok"})


WEB_DIRECTORY = "./web"
