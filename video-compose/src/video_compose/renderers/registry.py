# Implemented in task #34
_REGISTRY: dict = {}
def register(type_name, cls): _REGISTRY[type_name] = cls
def get(type_name): return _REGISTRY.get(type_name)
