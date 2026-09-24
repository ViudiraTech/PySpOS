#
#   apps/api.py
#   apps 的系统调用（syscall）接口层。
#
#   2026-09-24 改造：apps 现在跑在 fork 出来的真子进程里（见 forkexec.py），
#   子进程不能直接改父进程内存（与 Linux 的进程隔离一致），因此所有“写系统
#   状态”的操作改为走 syscall RPC：子进程 → 父进程 handler → 回传结果。
#
#   两种运行模式自动识别：
#     子进程模式：检测到 PYSPOS_SYSCTL_ADDR，连父进程 Listener 发请求；
#     同进程模式（测试/历史 open 兼容路径）：直接调用本地实现。
#   读类操作（用户名/root 状态/token）在子进程里也走 RPC，保证读到的是
#   父进程权威状态，避免子进程持有一份过期副本。
#

import os
import sys
from pathlib import Path

# 设置路径
current_directory = Path.cwd()
main_dir = current_directory.parent
syscall = os.path.join(main_dir)

sys.path.append(syscall)

import printk

SYSCTL_ENV = "PYSPOS_SYSCTL_ADDR"
AUTHKEY = b"pyspos-sysctl-v1"
_conn = None
_req_id = 0
_REQ_LOCK = None


# --------------------------------------------------------------------------
# RPC 传输
# --------------------------------------------------------------------------

def _get_conn():
    global _conn
    if _conn is not None:
        return _conn
    addr = os.environ.get(SYSCTL_ENV)
    if not addr:
        return None
    try:
        from multiprocessing.connection import Client
        host, port = addr.rsplit(":", 1)
        _conn = Client((host, int(port)), authkey=AUTHKEY)
    except Exception:
        _conn = None
    return _conn


def is_remote() -> bool:
    return _get_conn() is not None


def _call(op, *args, **kwargs):
    """发起 syscall。返回 (ok, value_or_error)。"""
    conn = _get_conn()
    if conn is None:
        return None
    global _req_id
    _req_id += 1
    rid = _req_id
    try:
        conn.send((rid, op, list(args), dict(kwargs)))
        _, payload = conn.recv()
    except Exception as e:
        return (False, f"系统调用失败: {e}")
    if not payload.get("ok"):
        return (False, payload.get("error", "未知错误"))
    return (True, payload.get("ret"))


def _local_set_rootstate(state: bool) -> bool:
    import main
    import btcfg
    import kernel
    from common.audit import audit
    try:
        if main.bootcfg.get("locked"):
            printk.warn("系统已锁定，使用临时 ROOT 方法...（重启后失效）")
            main.rootstate = state
        else:
            main.rootstate = state
            cfg = main.bootcfg
            cfg["rootstate"] = state
            btcfg.save_bootcfg_data(cfg)
        try:
            audit(main.root_dir, kernel.get_system_username(),
                  "set_rootstate", f"state={state}")
        except Exception:
            pass
        return True
    except Exception as e:
        printk.error(f"设置 rootstate 状态时出错: {e}")
        return False


def _local_set_lockstate(state: bool) -> bool:
    import main
    import btcfg
    import kernel
    from common.audit import audit
    try:
        cfg = main.bootcfg
        cfg["locked"] = state
        btcfg.save_bootcfg_data(cfg)
        try:
            audit(main.root_dir, kernel.get_system_username(),
                  "set_lockstate", f"state={state}")
        except Exception:
            pass
        return True
    except Exception as e:
        printk.error(f"设置 locked 状态时出错: {e}")
        return False


def _remote_or_local(op, local_impl, *args):
    res = _call(op, *args)
    if res is None:
        return local_impl(*args)
    ok, val = res
    if not ok:
        printk.error(str(val))
        return False
    return val


# --------------------------------------------------------------------------
# 系统调用
# --------------------------------------------------------------------------

# API: 获取系统用户名
def get_system_username():
    res = _call("get_system_username")
    if res is not None:
        ok, val = res
        if ok:
            return val
    import kernel
    return kernel.get_system_username()


# API: 调整 rootstate 状态
def set_rootstate(state: bool) -> bool:
    return _remote_or_local("set_rootstate", _local_set_rootstate, bool(state))


# API: 设置 locked 状态
def set_lockstate(state: bool) -> bool:
    return _remote_or_local("set_lockstate", _local_set_lockstate, bool(state))


def _get_cfg(key, default=None):
    res = _call("get_bootcfg")
    if res is not None:
        ok, val = res
        if ok and isinstance(val, dict):
            return val.get(key, default)
        return default
    try:
        import main
        return main.bootcfg.get(key, default)
    except Exception:
        return default


# API：返回 ROOT 状态（bcfg中）
def get_rootstate_bcfg() -> bool:
    return bool(_get_cfg("rootstate", False))


# API：返回临时 ROOT 状态
def get_rootstate() -> bool:
    res = _call("get_rootstate")
    if res is not None:
        ok, val = res
        if ok:
            return bool(val)
    try:
        import main
        return bool(main.rootstate)
    except Exception:
        return False


def get_lockstate() -> bool:
    return bool(_get_cfg("locked", True))


# unlock bootloader 专属部分
def return_token():
    res = _call("return_token")
    if res is not None:
        ok, val = res
        if ok:
            return val
    import kernel
    return kernel.token


# API: 进入内核主循环（子进程中不允许）
def enter_kernel_loop():
    import kernel
    kernel.loop()


# API: 退出系统（RPC 转发给父进程执行）
def exit_system():
    res = _call("exit_system")
    if res is None:
        import kernel
        kernel.exit()
    return True


def api_confirm(prompt: str) -> bool:
    # NOTE: kernel 模块从未提供 confirm，统一走 printk.confirm（历史 bug 修复）。
    return printk.confirm(prompt)


# API: 打印信息
def api_info(message: str) -> None:
    printk.info(message)


def api_ok(message: str) -> None:
    printk.ok(message)


def api_error(message: str) -> None:
    printk.error(message)


def api_warn(message: str) -> None:
    printk.warn(message)


def api_print(message: str) -> None:
    print(message)


# API: 执行系统命令
def api_system(command: str) -> int:
    return os.system(command)


# API: 基本数学运算
def add(a, b):
    return a + b


def subtract(a, b):
    return a - b


def multiply(a, b):
    return a * b


def divide(a, b):
    if b == 0:
        raise ValueError("Cannot divide by zero.")
    return a / b


def get_pids() -> dict:
    """返回当前模拟进程表快照（子进程可用）。"""
    import process
    return {p.pid: {"comm": p.comm, "state": p.state, "ppid": p.ppid}
            for p in process.list_procs(include_done=True)}
