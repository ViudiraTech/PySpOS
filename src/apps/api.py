'''
 *
 *      api.py
 *      App-facing RPC surface used by apps/ programs.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import base64
import os
import sys
import threading
from pathlib import Path

# Make the parent src/ directory importable
current_directory = Path.cwd()
main_dir = current_directory.parent
syscall = os.path.join(main_dir)

sys.path.append(syscall)

import printk

SYSCTL_ENV = "PYSPOS_SYSCTL_ADDR"
AUTHKEY_ENV = "PYSPOS_SYSCTL_AUTHKEY"
_conn = None
_req_id = 0
# One lock around the connection cache: several app threads may race to open
# it, and a second Client on the same address is a leaked socket.
_conn_lock = threading.Lock()
# One lock around the request-id counter: a child may issue syscalls from several
# threads, and an interleaved send would hand two replies to one waiting caller.
_req_lock = threading.Lock()


# --------------------------------------------------------------------------
# RPC transport
# --------------------------------------------------------------------------

# Split a host:port address, accepting the bracketed IPv6 form
# "[::1]:port" that a plain rsplit cannot handle.
def _split_addr(addr):
    if addr.startswith("["):
        host, _, rest = addr[1:].partition("]")
        if not rest.startswith(":"):
            raise ValueError(f"非法的监听地址: {addr}")
        return host, int(rest[1:])
    host, sep, port = addr.rpartition(":")
    if not sep:
        raise ValueError(f"非法的监听地址: {addr}")
    return host, int(port)


def _get_conn():
    global _conn
    if _conn is not None:
        return _conn
    addr = os.environ.get(SYSCTL_ENV)
    if not addr:
        return None
    try:
        from multiprocessing.connection import Client
        encoded = os.environ.get(AUTHKEY_ENV)
        if not encoded:
            return None
        authkey = base64.b64decode(encoded, validate=True)
        host, port = _split_addr(addr)
        with _conn_lock:
            if _conn is None:
                _conn = Client((host, port), authkey=authkey)
    except Exception:
        with _conn_lock:
            _conn = None
    return _conn
    addr = os.environ.get(SYSCTL_ENV)
    if not addr:
        return None
    try:
        from multiprocessing.connection import Client
        encoded = os.environ.get(AUTHKEY_ENV)
        if not encoded:
            return None
        authkey = base64.b64decode(encoded, validate=True)
        host, port = addr.rsplit(":", 1)
        _conn = Client((host, int(port)), authkey=authkey)
    except Exception:
        _conn = None
    return _conn


# Report whether this app runs as a real child process talking RPC.
def is_remote() -> bool:
    return _get_conn() is not None


# Send one syscall to the parent and return (ok, value_or_error).
# None when there is no channel, leaving the caller to run locally.
def _call(op, *args, **kwargs):
    conn = _get_conn()
    if conn is None:
        return None
    global _req_id
    with _req_lock:
        _req_id += 1
        rid = _req_id
    try:
        conn.send((rid, op, list(args), dict(kwargs)))
        got_id, payload = conn.recv()
    except Exception as e:
        return (False, f"系统调用失败: {e}")
    if got_id != rid:
        return (False, "系统调用响应序号不匹配")
    if not payload.get("ok"):
        return (False, payload.get("error", "未知错误"))
    return (True, payload.get("ret"))


# In-process body of set_rootstate: flip the live flag and, unless the
# boot trust domain is OEM-locked, persist it into bootcfg. Audited.
def _local_set_rootstate_impl(state: bool) -> bool:
    import main
    import btcfg
    import kernel
    from common.audit import audit
    try:
        if main.boot_locked:
            printk.warn("系统处于 OEM 锁定信任域，ROOT 仅为临时运行权限")
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


# In-process body of authorize_root: confirm with the user, then arm
# the one-shot flag that _local_set_rootstate consumes.
def _local_authorize_root() -> bool:
    import main
    import printk
    if not printk.confirm("允许当前应用获取 ROOT 权限？"):
        return False
    main._root_authorized = True
    return True


# In-process body of set_rootstate: elevation needs a fresh user
# confirmation and spends the one-shot authorization.
def _local_set_rootstate(state: bool) -> bool:
    import main
    if state and not getattr(main, "_root_authorized", False):
        raise PermissionError("ROOT 需要用户在父进程确认")
    main._root_authorized = False
    return _local_set_rootstate_impl(state)


# In-process body of set_lockstate: always refuses, because only an
# offline signed policy may change the bootloader lock state.
def _local_set_lockstate(state: bool) -> bool:
    printk.error("Bootloader 状态只能由离线签发的 policy 改变，ROOT/应用无权修改")
    return False


# Run a syscall through the parent when a channel exists, otherwise in
# process. A configured but dead channel fails closed, never falls back.
def _remote_or_local(op, local_impl, *args, **kwargs):
    res = _call(op, *args, **kwargs)
    if res is None:
        if os.environ.get(SYSCTL_ENV):
            printk.error("系统调用连接不可用，操作拒绝")
            return False
        return local_impl(*args, **kwargs)
    ok, val = res
    if not ok:
        printk.error(str(val))
        return False
    return val


# --------------------------------------------------------------------------
# Syscalls
# --------------------------------------------------------------------------

# API: return the system user name
def get_system_username():
    res = _call("get_system_username")
    if res is not None:
        ok, val = res
        if ok:
            return val
    import kernel
    return kernel.get_system_username()


# API: change the runtime rootstate
def set_rootstate(state: bool) -> bool:
    return _remote_or_local("set_rootstate", _local_set_rootstate, bool(state))


# API: ask the parent to confirm ROOT for the calling app
def authorize_root() -> bool:
    return _remote_or_local(
        "authorize_root", _local_authorize_root,
        app_id=os.environ.get("PYSPOS_APP_NAME", ""))


# API: change the bootloader lock state
def set_lockstate(state: bool) -> bool:
    return _remote_or_local("set_lockstate", _local_set_lockstate, bool(state))


# Read one key from bootcfg, over RPC in a child and from main.bootcfg otherwise.
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


# API: ROOT state as recorded in bootcfg
def get_rootstate_bcfg() -> bool:
    try:
        import main
        if main.boot_locked:
            return False
    except Exception:
        pass
    return bool(_get_cfg("rootstate", False))


# API: temporary runtime ROOT state
def get_rootstate() -> bool:
    res = _call("get_rootstate")
    if res is not None:
        ok, val = res
        if ok:
            return bool(val)
    try:
        import main
        return bool(main.is_root())
    except Exception:
        return False


# Report the bootloader lock state, failing closed to locked on error.
def get_lockstate() -> bool:
    try:
        import main
        import secure_boot
        return secure_boot.read_locked(main.root_dir)
    except Exception:
        return True


# Import package_core lazily so apps without packaging still start.
def _load_package_core():
    import package_core
    return package_core


# Send a package syscall over RPC and return (handled, value);
# handled=False means the caller must run the local implementation.
def _package_call(op, *args):
    result = _call(op, *args)
    if result is None:
        if os.environ.get(SYSCTL_ENV):
            raise RuntimeError("包管理 RPC 连接不可用")
        return False, None
    ok, value = result
    if not ok:
        raise RuntimeError(str(value))
    return True, value


# In-process body of the package syscalls. Install and remove also
# demand ROOT and are refused while the bootloader is locked.
def _local_package_call(op, *args):
    import main
    core = _load_package_core()
    root = main.root_dir
    if op == "pkg_list":
        return core.list_packages(root)
    if op == "pkg_info":
        return core.get_package(args[0], root)
    if op == "pkg_verify":
        return core.verify_package(args[0])
    if op == "pkg_build":
        return core.build_package(args[0], args[1])
    main.require_root("包管理安装/删除")
    if main.boot_locked:
        raise PermissionError("LOCKED 模式禁止安装或删除用户包")
    if op == "pkg_install":
        import commands
        return core.install_package(args[0], root,
                                    reserved_commands=commands.reserved_command_names())
    if op == "pkg_remove":
        return core.remove_package(args[0], root)
    raise ValueError(f"未知包管理操作: {op}")


# List the installed user packages.
def package_list():
    handled, value = _package_call("pkg_list")
    return value if handled else _local_package_call("pkg_list")


# Return the manifest of an installed package, or None.
def package_info(package_id):
    handled, value = _package_call("pkg_info", package_id)
    return value if handled else _local_package_call("pkg_info", package_id)


# Check a package directory or archive and return its manifest.
def package_verify(source):
    handled, value = _package_call("pkg_verify", source)
    return value if handled else _local_package_call("pkg_verify", source)


# Pack a package directory into an archive and return its path.
def package_build(source, output):
    handled, value = _package_call("pkg_build", source, output)
    return value if handled else _local_package_call("pkg_build", source, output)


# Install a package directory or archive (ROOT, unlocked device).
def package_install(source):
    handled, value = _package_call("pkg_install", source)
    return value if handled else _local_package_call("pkg_install", source)


# Uninstall a package by id (ROOT, unlocked device).
def package_remove(package_id):
    handled, value = _package_call("pkg_remove", package_id)
    return value if handled else _local_package_call("pkg_remove", package_id)


# API: enter the kernel main loop (not allowed in a child process)
def enter_kernel_loop():
    import kernel
    kernel.loop()


# API: exit the system (forwarded to the parent over RPC)
def exit_system():
    res = _call("exit_system")
    if res is None:
        import kernel
        kernel.exit()
    return True


# Ask the user a yes/no question on the console.
def api_confirm(prompt: str) -> bool:
    # NOTE: the kernel module never provided a confirm function, so every
    # confirmation goes through printk.confirm (historical bug fix).
    return printk.confirm(prompt)


# API: print a message
def api_info(message: str) -> None:
    printk.info(message)


# Print a success message through printk.
def api_ok(message: str) -> None:
    printk.ok(message)


# Print an error message through printk.
def api_error(message: str) -> None:
    printk.error(message)


# Print a warning message through printk.
def api_warn(message: str) -> None:
    printk.warn(message)


# Print a plain line to stdout.
def api_print(message: str) -> None:
    print(message)


# API: run a system command
def api_system(command: str) -> int:
    return os.system(command)


# API: basic arithmetic
def add(a, b):
    return a + b


# Subtract two numbers.
def subtract(a, b):
    return a - b


# Multiply two numbers.
def multiply(a, b):
    return a * b


# Divide two numbers, raising ValueError on a zero divisor.
def divide(a, b):
    if b == 0:
        raise ValueError("Cannot divide by zero.")
    return a / b


# Snapshot the simulated process table; usable from a child process.
def get_pids() -> dict:
    import process
    return {p.pid: {"comm": p.comm, "state": p.state, "ppid": p.ppid}
            for p in process.list_procs(include_done=True)}
