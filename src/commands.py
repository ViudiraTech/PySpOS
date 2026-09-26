'''
 *
 *      commands.py
 *      Command registry with metadata, groups and PATH-style external command resolution.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import os
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

# group definitions; this order is the order help prints them in
GROUPS = [
    ("system", "系统"),
    ("file", "文件"),
    ("text", "文本处理"),
    ("process", "进程与作业"),
    ("run", "程序与执行"),
    ("config", "配置与空间"),
    ("ota", "更新与恢复"),
    ("setup", "首次开机"),
    ("app", "内置应用"),
    ("package", "用户包"),
]


# Everything the registry knows about one command: how to run it and how to describe it.
@dataclass
class CommandMeta:
    name: str
    fn: Optional[Callable] = None
    summary: str = ""
    usage: str = ""
    group: str = "system"
    aliases: List[str] = field(default_factory=list)
    takes_arg: bool = False      # whether the command takes an argument, which drives the help <cmd> hint
    external: bool = False       # True means an external PATH command from apps/


_REGISTRY: Dict[str, CommandMeta] = {}
_ALIASES: Dict[str, str] = {}


# Register a command, accepting two call shapes:
#
#   register(name, fn, summary=..., group=...)            # direct call
#   register(name, "help text")(fn)                          # the old decorator form
def register(name: str, fn=None, *, summary: str = "", usage: str = "",
             group: str = "system", aliases: Optional[List[str]] = None,
             takes_arg: bool = False):
    if isinstance(fn, str):
        # the second positional argument is the help text, so return a decorator that waits for fn
        pending_summary = fn

        # Decorator half of the legacy register(name, "help text") form.
        def deco(f):
            return register(name, f, summary=pending_summary, usage=usage,
                            group=group, aliases=aliases, takes_arg=takes_arg)
        return deco

    if fn is not None and not callable(fn):
        raise TypeError("register: fn 必须是可调用对象或帮助文本字符串")

    meta = CommandMeta(name=name, fn=fn, summary=summary or (fn.__doc__ or ""),
                       usage=usage, group=group,
                       aliases=list(aliases or []), takes_arg=takes_arg)
    _REGISTRY[name] = meta
    for a in meta.aliases:
        _ALIASES[a] = name
    return fn


# Register a name that is not a Python function, such as an app or a package.
def register_external(name: str, *, summary: str = "", group: str = "app",
                      aliases: Optional[List[str]] = None):
    meta = CommandMeta(name=name, fn=None, summary=summary, group=group,
                       aliases=list(aliases or []), external=True)
    _REGISTRY[name] = meta
    for a in meta.aliases:
        _ALIASES[a] = name


# Return the callable behind a name, or None.
def get(name: str) -> Optional[Callable]:
    real = _ALIASES.get(name, name)
    meta = _REGISTRY.get(real)
    if meta is None:
        return None
    return meta.fn


# Return the metadata behind a name, or None.
def get_meta(name: str) -> Optional[CommandMeta]:
    return _REGISTRY.get(_ALIASES.get(name, name))


# Report whether a name is registered.
def has(name: str) -> bool:
    return _ALIASES.get(name, name) in _REGISTRY


# Return the registered names mapped to their callables.
def all_commands() -> Dict[str, Callable]:
    return {k: v.fn for k, v in _REGISTRY.items() if v.fn is not None}


# Return a copy of the whole metadata table.
def all_meta() -> Dict[str, CommandMeta]:
    return dict(_REGISTRY)


# Return the registered command names, sorted.
def names() -> List[str]:
    return sorted(_REGISTRY.keys())


# Return the names and aliases to offer for tab completion.
def names_for_completion() -> List[str]:
    out = set(_REGISTRY.keys())
    out.update(_ALIASES.keys())
    return sorted(out)


# --------------------------------------------------------------------------
# help rendering
# --------------------------------------------------------------------------

# Return the display label of a group id, or the id itself when unknown.
def _group_label(gid: str) -> str:
    for k, label in GROUPS:
        if k == gid:
            return label
    return gid


# Render the grouped command list, or the detail of one topic.
def render_help(topic: Optional[str] = None) -> str:
    if topic:
        meta = get_meta(topic)
        if meta is None:
            return f"未知命令: {topic}\n"
        lines = [f"{meta.name} — {meta.summary}"]
        if meta.usage:
            lines.append(f"用法: {meta.usage}")
        if meta.aliases:
            lines.append(f"别名: {', '.join(meta.aliases)}")
        lines.append(f"分组: {_group_label(meta.group)}")
        if meta.external:
            lines.append("类型: 外部命令（PATH=apps/，fork 独立子进程执行）")
        elif meta.fn:
            lines.append(f"实现: {meta.fn.__module__}.{meta.fn.__name__}")
        return "\n".join(lines) + "\n"
    by_group: Dict[str, List[CommandMeta]] = {}
    for meta in _REGISTRY.values():
        by_group.setdefault(meta.group, []).append(meta)
    out = ["PySpOS shell 命令（按分组；help <命令> 查看详情）", ""]
    for gid, label in GROUPS:
        metas = sorted(by_group.get(gid, []), key=lambda m: m.name)
        if not metas:
            continue
        out.append(f"[{label}]")
        for m in metas:
            tag = " (外部)" if m.external else ""
            out.append(f"  {m.name:<16} {m.summary}{tag}")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


# --------------------------------------------------------------------------
# PATH-style external command resolution, with apps/ as $PATH
# --------------------------------------------------------------------------

# Return the directory that plays the role of PATH, that is apps/.
def _apps_dir() -> str:
    try:
        import main
        configured = getattr(main, "apps_dir", None)
        if configured and os.path.isdir(configured):
            return configured
        script_dir = getattr(main, "script_dir", None)
        if script_dir:
            candidate = os.path.join(script_dir, "apps")
            if os.path.isdir(candidate):
                return candidate
    except Exception:
        pass
    return os.path.join(os.getcwd(), "apps")


# Resolve an external command in PATH, currently apps/, and return its absolute path.
def resolve_external(name: str) -> Optional[str]:
    if not name or "/" in name or "\\" in name:
        return None
    cand = os.path.join(_apps_dir(), name + ".py")
    if os.path.isfile(cand):
        return cand
    return None


# library modules in apps/ are not exposed as runnable commands
LIBRARY_MODULES = {"api"}


# Scan apps/ for runnable .py apps and return their command names.
def discover_external() -> List[str]:
    d = _apps_dir()
    if not os.path.isdir(d):
        return []
    out = []
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".py") or fn.startswith("_"):
            continue
        # A directory whose name ends in .py is not an app: offering it as a
        # command produced a name that resolved to a directory and then failed.
        if not os.path.isfile(os.path.join(d, fn)):
            continue
        name = fn[:-3]
        if name in LIBRARY_MODULES:
            continue
        out.append(name)
    return out


# Return the root that installed packages are looked up under.
def _package_root(root_dir: Optional[str] = None) -> str:
    if root_dir is not None:
        return os.path.abspath(root_dir)
    try:
        import main
        return main.root_dir
    except Exception:
        return os.environ.get("PYSPOS_BOOT_ROOT", os.getcwd())


# List the entry points of every installed package, or nothing on error.
def discover_package_commands(root_dir: Optional[str] = None) -> List[dict]:
    try:
        import package_core as package_manager
        return package_manager.discover_commands(_package_root(root_dir))
    except Exception:
        return []


# Return the entry point of an installed package matching name, or None.
def resolve_package_command(name: str, root_dir: Optional[str] = None) -> Optional[dict]:
    if not name or "/" in name or "\\" in name:
        return None
    try:
        import package_core as package_manager
        return package_manager.resolve_command(name, _package_root(root_dir))
    except Exception:
        return None


# Return the names already taken by builtins, aliases and apps/.
def reserved_command_names() -> set[str]:
    names = set()
    for name, meta in _REGISTRY.items():
        # An external command is taken too: a package must not be able to claim a
        # name an app/ script or one of its aliases already answers to.
        if meta.fn is not None or meta.external:
            names.add(name)
            names.update(meta.aliases)
    names.update(discover_external())
    return names


# Register the apps/ scripts and the installed package entry points as external commands.
def register_discovered(root_dir: Optional[str] = None) -> None:
    for name in discover_external():
        if not has(name):
            register_external(name, summary="内置应用（fork 独立进程执行）")
    for target in discover_package_commands(root_dir):
        names = [target.get("name", "")] + list(target.get("aliases", []))
        if not names[0] or any(has(name) for name in names):
            continue
        register_external(names[0], summary=(
            f"用户包 {target['package_id']}@{target['version']}"),
            aliases=names[1:])
