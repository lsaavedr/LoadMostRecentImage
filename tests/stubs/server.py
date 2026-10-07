class _Routes:
    def __init__(self):
        self.handlers = {}

    def post(self, path):
        def decorator(fn):
            self.handlers[path] = fn
            return fn

        return decorator


class PromptServer:
    class _Instance:
        def __init__(self):
            self.routes = _Routes()

    instance = _Instance()
