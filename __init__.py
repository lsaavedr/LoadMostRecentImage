from .nodes import LoadMostRecentImage
from comfy_api.latest import ComfyExtension, io


class LoadMostRecentImageExtension(ComfyExtension):
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return [LoadMostRecentImage]


async def comfy_entrypoint() -> LoadMostRecentImageExtension:
    return LoadMostRecentImageExtension()


WEB_DIRECTORY = "./web"
