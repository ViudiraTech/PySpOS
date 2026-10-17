"""Child-side access to the host syscall channel, for apps/ programs.

A GUI app runs as a real child process, so the system state it displays lives in
the parent. This is the one place that knows how to reach it, so each app does
not repeat the same import dance and error shape.

It lives in the SDK rather than in apps/ on purpose: launchApp puts src/ on a
desktop child's PYTHONPATH but not src/apps/, so `import hostapi` would fail
there while `from vortexglass.host import ...` always resolves.
"""


# Find the syscall module however this interpreter was launched: the main shell
# and pytest have src/apps on the path, desktop children spawned with python -m
# only have src/, where apps/ is a namespace package.
def api_module():
    try:
        import api
        return api
    except ImportError:
        pass
    try:
        from apps import api as apps_api
        return apps_api
    except ImportError:
        return None


# True when this app is a real child holding a live host channel.
def is_remote():
    module = api_module()
    return module is not None and module.is_remote()


# Call one host op and return (ok, value_or_reason). A missing channel is
# reported the same way a refused call is, so a view can render the reason
# instead of raising out of its paint loop.
def call(op, *args, **kwargs):
    module = api_module()
    if module is None:
        return False, "本机 syscall 模块不可用"
    if not module.is_remote():
        return False, "不在宿主通道上（请从桌面或 shell 启动）"
    try:
        result = module._call(op, *args, **kwargs)
    except Exception as exc:
        return False, f"调用失败: {exc}"
    if result is None:
        return False, "宿主通道不可用"
    return result
