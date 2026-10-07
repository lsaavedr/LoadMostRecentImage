class _Input:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


class _Output:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


class String:
    Input = _Input
    Output = _Output


class Combo:
    Input = _Input
    Output = _Output


class Image:
    Input = _Input
    Output = _Output


class Int:
    Input = _Input
    Output = _Output


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


io = type(
    "io",
    (),
    {
        "Schema": Schema,
        "NodeOutput": NodeOutput,
        "ComfyNode": ComfyNode,
        "ComfyExtension": ComfyExtension,
        "String": String,
        "Combo": Combo,
        "Image": Image,
        "Int": Int,
    },
)()
