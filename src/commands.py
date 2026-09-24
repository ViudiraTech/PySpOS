#
#   commands.py
#   命令注册表：替代 main.py 里 COMMANDS 字典 + if/elif 混用的分发。
#   兼容策略：main.py 的历史命令保持不动；新增命令走本注册表，
#   main.handle_command 会优先查注册表，未命中再走历史分支。
#
from typing import Callable, Dict

_REGISTRY: Dict[str, Callable] = {}
_HELP: Dict[str, str] = {}


def register(name: str, help_text: str = ""):
    def deco(fn: Callable):
        _REGISTRY[name] = fn
        _HELP[name] = help_text or fn.__doc__ or ""
        return fn
    return deco


def get(name: str):
    return _REGISTRY.get(name)


def all_commands() -> Dict[str, Callable]:
    return dict(_REGISTRY)


def help_text(name: str) -> str:
    return _HELP.get(name, "")
