#
#   commands.py
#   命令注册表（带元数据 + 分组 + PATH 外部命令解析 + Tab 补全数据源）。
#
#   借鉴 bash / zsh / just-bash 的成熟做法：
#     - 元数据驱动：summary/usage/group/aliases/completer 全部声明式，
#       help 由注册表自动生成，新增命令不必再手写长帮助列表；
#     - 分组展示：help 输出按 group 归类（系统/文件/进程/OTA/配置/引导），
#       help <cmd> 输出单命令详情；
#     - PATH 解析：apps/ 作为外部命令目录（等价 $PATH），命令名直接可执行
#       （gettoken 而非 open gettoken），命中后进 forkexec 真子进程；
#     - 惰性加载：外部命令不预先 import，调用时才 fork。
#

import os
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

# 分组定义（顺序即 help 展示顺序）
GROUPS = [
    ("system", "系统"),
    ("file", "文件"),
    ("process", "进程与作业"),
    ("run", "程序与执行"),
    ("config", "配置与空间"),
    ("ota", "更新与恢复"),
    ("setup", "首次开机"),
    ("app", "内置应用"),
    ("package", "用户包"),
]


@dataclass
class CommandMeta:
    name: str
    fn: Optional[Callable] = None
    summary: str = ""
    usage: str = ""
    group: str = "system"
    aliases: List[str] = field(default_factory=list)
    takes_arg: bool = False      # 是否有参数形态（决定 help <cmd> 提示）
    external: bool = False       # True=PATH 外部命令（apps/）


_REGISTRY: Dict[str, CommandMeta] = {}
_ALIASES: Dict[str, str] = {}


def register(name: str, fn=None, *, summary: str = "", usage: str = "",
             group: str = "system", aliases: Optional[List[str]] = None,
             takes_arg: bool = False):
    """注册命令，兼容两种调用形态：

      register(name, fn, summary=..., group=...)            # 直接注册
      register(name, "帮助文本")(fn)                          # 历史装饰器形态
    """
    if isinstance(fn, str):
        # 第二个位置参数是 help 文本 → 返回装饰器等 fn 传进来
        pending_summary = fn

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


def register_external(name: str, *, summary: str = "", group: str = "app",
                      aliases: Optional[List[str]] = None):
    meta = CommandMeta(name=name, fn=None, summary=summary, group=group,
                       aliases=list(aliases or []), external=True)
    _REGISTRY[name] = meta
    for a in meta.aliases:
        _ALIASES[a] = name


def get(name: str) -> Optional[Callable]:
    real = _ALIASES.get(name, name)
    meta = _REGISTRY.get(real)
    if meta is None:
        return None
    return meta.fn


def get_meta(name: str) -> Optional[CommandMeta]:
    return _REGISTRY.get(_ALIASES.get(name, name))


def has(name: str) -> bool:
    return _ALIASES.get(name, name) in _REGISTRY


def all_commands() -> Dict[str, Callable]:
    return {k: v.fn for k, v in _REGISTRY.items() if v.fn is not None}


def all_meta() -> Dict[str, CommandMeta]:
    return dict(_REGISTRY)


def names() -> List[str]:
    return sorted(_REGISTRY.keys())


def names_for_completion() -> List[str]:
    out = set(_REGISTRY.keys())
    out.update(_ALIASES.keys())
    return sorted(out)


# --------------------------------------------------------------------------
# help 渲染
# --------------------------------------------------------------------------

def _group_label(gid: str) -> str:
    for k, label in GROUPS:
        if k == gid:
            return label
    return gid


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
# PATH 外部命令解析（apps/ 作为 $PATH）
# --------------------------------------------------------------------------

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


def resolve_external(name: str) -> Optional[str]:
    """在 PATH（当前为 apps/）里解析外部命令；命中返回绝对路径。"""
    if not name or "/" in name or "\\" in name:
        return None
    cand = os.path.join(_apps_dir(), name + ".py")
    if os.path.isfile(cand):
        return cand
    return None


# apps/ 里的库模块：不对外暴露为可执行命令
LIBRARY_MODULES = {"api"}


def discover_external() -> List[str]:
    """扫描 apps/ 里的可执行 app（.py），返回命令名列表。"""
    d = _apps_dir()
    if not os.path.isdir(d):
        return []
    out = []
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".py") or fn.startswith("_"):
            continue
        name = fn[:-3]
        if name in LIBRARY_MODULES:
            continue
        out.append(name)
    return out


def _package_root(root_dir: Optional[str] = None) -> str:
    if root_dir is not None:
        return os.path.abspath(root_dir)
    try:
        import main
        return main.root_dir
    except Exception:
        return os.environ.get("PYSPOS_BOOT_ROOT", os.getcwd())


def discover_package_commands(root_dir: Optional[str] = None) -> List[dict]:
    try:
        import package_core as package_manager
        return package_manager.discover_commands(_package_root(root_dir))
    except Exception:
        return []


def resolve_package_command(name: str, root_dir: Optional[str] = None) -> Optional[dict]:
    if not name or "/" in name or "\\" in name:
        return None
    try:
        import package_core as package_manager
        return package_manager.resolve_command(name, _package_root(root_dir))
    except Exception:
        return None


def reserved_command_names() -> set[str]:
    names = set()
    for name, meta in _REGISTRY.items():
        if meta.fn is not None:
            names.add(name)
            names.update(meta.aliases)
    names.update(discover_external())
    return names


def register_discovered(root_dir: Optional[str] = None) -> None:
    """把 apps/ 和已安装包的入口注册为外部命令。"""
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
