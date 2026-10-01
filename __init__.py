from .nodes import LoadMostRecentImage
from comfy.api.comfy_extension import ComfyExtension
from comfy.api.comfy_node import ComfyNode


class LoadMostRecentImageExtension(ComfyExtension):
    async def get_node_list(self) -> list[type[ComfyNode]]:
        return [LoadMostRecentImage]


async def comfy_entrypoint() -> LoadMostRecentImageExtension:
    return LoadMostRecentImageExtension()


WEB_DIRECTORY = "./web"
