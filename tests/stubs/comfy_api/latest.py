class _Input:
    def __init__(self, *args, **kwargs):
        pass


class _Output:
    def __init__(self, *args, **kwargs):
        pass


class String:
    Input = _Input


class Combo:
    Input = _Input


class Image:
    Input = _Input


class Int:
    Input = _Input


class Schema:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class NodeOutput:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


class ComfyNode:
    pass


class ComfyExtension:
    pass


io = type("io", (), {
    "Schema": Schema,
    "NodeOutput": NodeOutput,
    "ComfyNode": ComfyNode,
    "ComfyExtension": ComfyExtension,
    "String": String,
    "Combo": Combo,
    "Image": Image,
    "Int": Int,
})()
