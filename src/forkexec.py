'''
 *
 *      forkexec.py
 *      Real fork/exec of app children with stdio relay and RPC.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import multiprocessing as mp
import base64
import os
import secrets
import sys
import threading
import time
import traceback

import process as proc

SYSCTL_ENV = "PYSPOS_SYSCTL_ADDR"
AUTHKEY_ENV = "PYSPOS_SYSCTL_AUTHKEY"
AUTHKEY = secrets.token_bytes(32)

# POSIX uses fork (real fork semantics, no pickling of arguments); Windows uses spawn
try:
    _CTX = mp.get_context("fork") if os.name == "posix" else mp.get_context("spawn")
except ValueError:
    _CTX = mp.get_context()

_pump_thread = None
_listener = None
_relay_threads = {}


# --------------------------------------------------------------------------
# child side
# --------------------------------------------------------------------------

# Point the child's stdio at the relay pipes.
# The relay has to be a bare os.pipe() and not multiprocessing.Pipe: the latter
# is a framed send_bytes/recv_bytes protocol that does not fit the raw byte
# stream used here. In the parent direction the length header would be fed to
# the app as user input, and in the child direction a raw text blob would be read
# as a length header, so the output thread dies silently and the output is lost.
def _relay_child_stdio(out_fd, in_fd):
    # out_fd and in_fd are the child's ends of the bare os.pipe() relay; None keeps
    # whatever this process inherited.
    out, inp = sys.stdout, sys.stdin
    try:
        if out_fd is not None:
            out = os.fdopen(out_fd, "w", encoding="utf-8", buffering=1)
            sys.stdout = out
            sys.stderr = out
        if in_fd is not None:
            inp = os.fdopen(in_fd, "r", encoding="utf-8", buffering=1)
            sys.stdin = inp
    except OSError:
        pass
    return out, inp


# Import an app file as the module __exec__ and
# run its entry point, without running it twice.
def _run_app_module(target):
    import importlib.util
    if os.path.isabs(target):
        cands = [target]
    else:
        cands = [os.path.join(os.getcwd(), "apps", target)]
        for p in sys.path:
            cands.append(os.path.join(p, "apps", target))
    mod_path = next((c for c in cands if os.path.isfile(c)), None)
    if mod_path is None:
        raise FileNotFoundError(f"app 不存在: {target}")
    # The module name is __exec__, matching the historic open command's exec semantics.
    # Apps guard their entry point in two ways:
    #   if __name__ == '__exec__': main()   runs on import, so main() must not be called again
    #   if __name__ == '__main__': ...     does not run on import, so main() has to be called
    # Hence the choice is made from the source, to avoid running the entry point twice.
    with open(mod_path, "r", encoding="utf-8") as f:
        source = f.read()
    os.environ["PYSPOS_APP_NAME"] = os.path.basename(mod_path)
    module_dir = os.path.dirname(mod_path)
    if module_dir and module_dir not in sys.path:
        sys.path.insert(0, module_dir)
    runs_on_import = '__name__ == "__exec__"' in source

    spec = importlib.util.spec_from_file_location("__exec__", mod_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["__exec__"] = mod
    spec.loader.exec_module(mod)
    if not runs_on_import:
        main_fn = getattr(mod, "main", None)
        if callable(main_fn):
            main_fn()


# Run a .spf application through parse_spf.
def _run_spf_file(path):
    import parse_spf
    parse_spf.run_spf(path)


# The real child process body; it may not touch any of the parent's memory
# state.
# parent_fds are the ends the parent holds: fork left this process with copies, so
# they have to be closed first. This is a real bug found on 2026-09-24, the
# parent closing in_w is not enough because the child still holds a write end
# and its in_r never sees EOF, so a foreground interactive app hangs in input()
# and never exits. Tests that feed a pty by hand hide this path, bypassing EOF.
def _child_main(payload, addr, src_dir, apps_dir, env, out_fd, in_fd,
                parent_fds=()):
    for fd in parent_fds:
        try:
            os.close(fd)
        except (OSError, TypeError):
            pass
    _relay_child_stdio(out_fd, in_fd)
    for p in (src_dir, apps_dir):
        if p and p not in sys.path:
            sys.path.insert(0, p)
    if addr:
        os.environ[SYSCTL_ENV] = f"{addr[0]}:{addr[1]}"
    if env:
        os.environ.update({k: str(v) for k, v in env.items()})

    code = 0
    try:
        kind, _, target = payload.partition(":")
        if kind == "app":
            _run_app_module(target)
        elif kind == "spf":
            _run_spf_file(target)
        else:
            raise ValueError(f"未知 payload 类型: {kind}")
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 0
    except EOFError:
        # 2026-09-24: a closed stdin is a normal way to end, so no traceback is dumped.
        # The apps already handle EOF one by one; this is the child-level backstop.
        try:
            sys.stdout.write("\n[输入已结束，程序退出]\n")
            sys.stdout.flush()
        except Exception:
            pass
        code = 0
    except KeyboardInterrupt:
        try:
            sys.stdout.write("\n[已中断]\n")
            sys.stdout.flush()
        except Exception:
            pass
        code = 130
    except BaseException:
        try:
            traceback.print_exc()
            sys.stdout.flush()
        except Exception:
            pass
        code = 1
    finally:
        try:
            sys.stdout.flush()
        except Exception:
            pass
        # The child shares the parent's tty. If the app changed the terminal mode (running
        # curses or a TUI, for example), os._exit skips Python's cleanup chain and the tty is
        # left in cbreak/icrnl-off, so Enter becomes ^M once we are back in the parent.
        # os._exit runs no atexit handlers, so the terminal has to be restored by hand here.
        try:
            import ttyutil
            ttyutil.ensure_sane_tty()
        except Exception:
            pass
    os._exit(code)


# --------------------------------------------------------------------------
# parent side: the pump and the syscall service
# --------------------------------------------------------------------------

# Poll every child handle, turn an exit into a zombie with its CPU time settled,
# and leave the reaping to wait.
def _pump_loop():
    while True:
        table = proc._table()
        pids = list(table.handles.keys())
        if not pids:
            time.sleep(0.05)
            continue
        for pid in pids:
            handle = table.handles.get(pid)
            pcb = table.tasks.get(pid)
            if handle is None or pcb is None:
                continue
            try:
                alive = handle.is_alive()
            except Exception:
                alive = False
            if not alive:
                try:
                    code = int(handle.exitcode or 0)
                except Exception:
                    code = 0
                table.handles.pop(pid, None)
                if pcb.state not in proc.TERMINAL_STATES:
                    wall = (time.time() - pcb.start_time) * 1000.0
                    table.child_exited(pid, exit_code=code, wall_ms=wall)
        time.sleep(0.03)


# Start the pump thread once, and start it again if it ever died.
def _ensure_pump():
    global _pump_thread
    if _pump_thread is None or not _pump_thread.is_alive():
        _pump_thread = threading.Thread(target=_pump_loop,
                                        name="pyspos-pump", daemon=True)
        _pump_thread.start()


# Parent-side implementation of the privileged operations an app may request
# over RPC.
def _sysctl_handler(op, args, kwargs):
    import main
    import btcfg
    import kernel
    import printk

    op = str(op)
    if op == "authorize_root":
        app_id = str(kwargs.get("app_id", ""))
        if app_id not in {"getroot.py", "bm.py"}:
            raise PermissionError("只有官方 ROOT 管理应用可以请求授权")
        main._root_authorized = True
        return True
    if op == "set_rootstate":
        state = bool(args[0])
        if state and not getattr(main, "_root_authorized", False):
            raise PermissionError("ROOT 需要用户在父进程确认")
        main._root_authorized = False
        if main.boot_locked:
            printk.warn("系统处于 OEM 锁定信任域，ROOT 仅为临时运行权限")
            main.rootstate = state
        else:
            main.rootstate = state
            cfg = main.bootcfg
            cfg["rootstate"] = state
            btcfg.save_bootcfg_data(cfg)
        _audit("set_rootstate", f"state={state}")
        return True
    if op == "set_lockstate":
        raise PermissionError("Bootloader 信任域只能由外部签名 policy 改变")
    if op == "get_bootcfg":
        return dict(main.bootcfg)
    if op == "get_rootstate":
        return bool(main.is_root())
    if op == "get_lockstate":
        import secure_boot
        return secure_boot.read_locked(main.root_dir)
    if op == "pkg_list":
        import package_core
        return package_core.list_packages(main.root_dir)
    if op == "pkg_info":
        import package_core
        return package_core.get_package(str(args[0]), main.root_dir)
    if op == "pkg_verify":
        import package_core
        return package_core.verify_package(str(args[0]))
    if op == "pkg_build":
        import package_core
        return package_core.build_package(str(args[0]), str(args[1]))
    if op == "pkg_install":
        import package_core
        import commands
        from common.audit import audit
        main.require_root("包安装")
        if main.boot_locked:
            raise PermissionError("LOCKED 模式禁止安装或删除用户包")
        manifest = package_core.install_package(
            str(args[0]), main.root_dir,
            reserved_commands=commands.reserved_command_names())
        commands.register_discovered(main.root_dir)
        audit(main.root_dir, "pkg", "install",
              f"id={manifest['id']} version={manifest['version']}")
        return manifest
    if op == "pkg_remove":
        import package_core
        import commands
        from common.audit import audit
        main.require_root("包删除")
        if main.boot_locked:
            raise PermissionError("LOCKED 模式禁止安装或删除用户包")
        manifest = package_core.remove_package(str(args[0]), main.root_dir)
        commands.register_discovered(main.root_dir)
        audit(main.root_dir, "pkg", "remove", f"id={manifest['id']}")
        return manifest
    if op == "get_system_username":
        return kernel.get_system_username()
    if op == "exit_system":
        threading.Thread(target=_delayed_exit, daemon=True).start()
        return True
    raise ValueError(f"未知系统调用: {op}")


# Write one audit record, and never let auditing break the operation it records.
def _audit(action, detail):
    try:
        import main
        from common.audit import audit
        audit(main.root_dir, _sysctl_handler.__name__ and "app", action, detail)
    except Exception:
        pass


# Give the RPC reply time to leave before the system shuts down.
def _delayed_exit():
    time.sleep(0.2)
    import main
    main.handle_command("shutdown")


# Answer syscall requests for one child connection until it goes away.
def _serve_client(conn):
    while True:
        try:
            msg = conn.recv()
        except (EOFError, OSError):
            break
        if msg is None:
            break
        req_id, op, args, kwargs = msg
        try:
            ret = _sysctl_handler(op, args, kwargs)
            payload = {"ok": True, "ret": ret}
        except BaseException as e:
            payload = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        try:
            conn.send((req_id, payload))
        except Exception:
            break
    try:
        conn.close()
    except Exception:
        pass


# Accept syscall connections and give each one its own answering thread.
def _sysctl_accept_loop():
    global _listener
    from multiprocessing.connection import Listener
    try:
        _listener = Listener(("127.0.0.1", 0), authkey=AUTHKEY)
    except Exception:
        _listener = None
        return
    while True:
        try:
            conn = _listener.accept()
        except Exception:
            break
        threading.Thread(target=_serve_client, args=(conn,), daemon=True).start()


# Start the syscall listener once; a failed bind is not retried.
def _ensure_listener():
    if _listener is None and not getattr(_ensure_listener, "_tried", False):
        _ensure_listener._tried = True
        threading.Thread(target=_sysctl_accept_loop, name="pyspos-sysctl",
                         daemon=True).start()
        time.sleep(0.05)


# Deliver a fatal signal to the real child: SIGKILL
# kills it, SIGTERM and SIGINT terminate it.
def _signal_backend(pcb, signum):
    handle = proc._table().handles.get(pcb.pid)
    if handle is None:
        return False, "子进程已退出或句柄失效"
    try:
        if signum == proc.SIGKILL:
            handle.kill()
            return True, "SIGKILL（已强杀）"
        if signum in (proc.SIGTERM, proc.SIGINT):
            handle.terminate()
            return True, "SIGTERM"
    except Exception as e:
        return False, f"投递失败: {e}"
    return True, "无 OS 级动作（用户态信号）"


# --------------------------------------------------------------------------
# public entry points
# --------------------------------------------------------------------------

# Relay stdin as raw bytes, pulled out so the log and tee paths can reuse it.
def _pump_in_relay(in_w, background):
    if in_w is None:
        return
    if background:
        # Background job: no stdin, so close the write
        # end at once and the child sees EOF and exits
        try:
            os.close(in_w)
        except (OSError, TypeError):
            pass
        return
    try:
        while True:
            buf = getattr(sys.stdin, "buffer", None)
            data = buf.read(1) if buf is not None else \
                sys.stdin.read(1).encode("utf-8")
            if not data:
                break
            os.write(in_w, data)
    except (OSError, ValueError, AttributeError):
        pass
    finally:
        try:
            os.close(in_w)
        except (OSError, TypeError):
            pass


# Forward the child's stdout to the parent terminal and, for foreground work,
# push the parent's stdin into the child.
# out_r and in_w are bare os.pipe() descriptors, forwarded block by block. in_w
# must be closed at once in background mode, otherwise the child blocks forever
# waiting for input, which shows up as an app that never exits.
def _relay_parent_side(out_r, in_w, background):
    # One direction of the relay: child stdout to
    # the parent terminal, then close the read end.
    def _pump_out():
        try:
            while True:
                try:
                    data = os.read(out_r, 4096)
                except (OSError, ValueError):
                    break
                if not data:
                    break
                sys.stdout.write(data.decode("utf-8", "replace"))
                sys.stdout.flush()
        except Exception:
            pass
        finally:
            try:
                os.close(out_r)
            except (OSError, TypeError):
                pass

    output_thread = threading.Thread(target=_pump_out, daemon=True)
    output_thread.start()
    threading.Thread(target=_pump_in_relay, args=(in_w, background),
                     daemon=True).start()
    return output_thread


# Run a payload in a real child and return its PCB, marked remote.
# background=True hands the child /dev/null on stdin while its output is still
# relayed to the terminal, so the shell is not blocked. log_path additionally
# tees the output to a file.
def fork_exec(payload, *, kind="app", background=False, nice=0,
              src_dir=None, apps_dir=None, env=None, log_path=None):
    _ensure_pump()
    _ensure_listener()
    if src_dir is None:
        src_dir = os.path.dirname(os.path.abspath(__file__))
    if apps_dir is None:
        apps_dir = os.path.join(src_dir, "apps")
    addr = _listener.address if _listener is not None else None

    comm = payload.split(":", 1)[-1]
    if comm.endswith(".py"):
        comm = comm[:-3]
    pcb = proc.spawn(comm, kind=kind, nice=nice, remote=True,
                     note="real child process")

    # Relays always use a bare os.pipe(): stdin and stdout are byte streams, and
    # mp.Pipe's message framing cannot carry them (see the comment on
    # _relay_child_stdio).
    #
    # 2026-09-24 fix: it used to be `use_relay = background or start=='spawn'`,
    # which meant foreground jobs on Linux (fork) skipped the relay entirely, so
    # grandchildren inherited the parent's tty and buffered streams. Two results:
    #   1. any change the child made to the terminal mode or buffers leaked into
    #      the parent shell (^M faults);
    #   2. output interleaved with the parent's prompts and could not be logged.
    # Foreground work is exactly the case that needs the relay, since the parent's
    # stdin has to reach the child's, so it is always on.
    out_fd = in_fd = None
    out_r = out_w = in_r = in_w = None
    # stdout: the child writes, the parent reads
    out_r, out_w = os.pipe()
    out_fd = out_w              # the child writes stdout here
    if background:
        # A background job has no terminal stdin: hand it /dev/null so the child
        # gets EOF at once instead of blocking in input() (that was why zzlsb hung).
        in_fd = os.open(os.devnull, os.O_RDONLY)
    else:
        # stdin: the parent writes, the child reads
        in_r, in_w = os.pipe()
        in_fd = in_r              # the child reads stdin here

    # The ends the parent holds are handed to the child to close: fork leaves the
    # child with copies, so a child still holding the write end of the stdin pipe
    # never sees EOF on its read end, which is why a foreground interactive app hung
    # in input() and would not exit.
    parent_fds = tuple(fd for fd in (out_r, in_w) if fd is not None)

    child_env = dict(env or {})
    child_env[AUTHKEY_ENV] = base64.b64encode(AUTHKEY).decode("ascii")
    handle = _CTX.Process(
        target=_child_main,
        args=(payload, addr, src_dir, apps_dir, child_env,
              out_fd, in_fd, parent_fds),
        daemon=False,
    )
    proc._table().handles[pcb.pid] = handle
    try:
        handle.start()
    except Exception as e:
        proc._table().handles.pop(pcb.pid, None)
        proc.finish(pcb.pid, 1, failed=True)
        print(f"fork_exec: 子进程启动失败: {e}")
        return pcb
    # The parent must close its own copy of the ends the child uses, otherwise:
    #   - leaving out_w open means the parent's stdout read never sees EOF after the
    #     child exits;
    #   - leaving in_r open means the child never sees EOF on stdin.
    for fd in (out_w, in_r):
        if fd is not None:
            try:
                os.close(fd)
            except (OSError, TypeError):
                pass
    if out_r is not None:
        if log_path:
            # Write to the log **and** keep printing to the terminal: for a background job,
            # `cmd > log` means keep a copy, not swallow the terminal output.
            _log_relay(out_r, log_path, echo=not background)
            if not background and in_w is not None:
                threading.Thread(target=_pump_in_relay, args=(in_w, False),
                                 daemon=True).start()
        else:
            _relay_threads[pcb.pid] = _relay_parent_side(out_r, in_w, background)
    proc._table().set_remote_signal_backend(_signal_backend)
    return pcb


# Write the child's stdout to log_path; with echo=True
# it is printed to the terminal as well, a tee.
def _log_relay(out_r, log_path, echo=False):
    # One direction of the log relay: read the child
    # stdout into the file, and echo it when asked.
    def _pump():
        try:
            with open(log_path, "ab") as f:
                while True:
                    data = os.read(out_r, 4096)
                    if not data:
                        break
                    f.write(data)
                    f.flush()
                    if echo:
                        sys.stdout.write(data.decode("utf-8", "replace"))
                        sys.stdout.flush()
        except (OSError, ValueError):
            pass
        finally:
            try:
                os.close(out_r)
            except (OSError, TypeError):
                pass
    threading.Thread(target=_pump, daemon=True).start()


# Wait for a child to end and reap it, the wait
# semantics, then drop the entry from the table.
def wait(pid, timeout=30.0):
    pcb = proc.wait_for(pid, timeout=timeout)
    output_thread = _relay_threads.pop(pid, None)
    if output_thread is not None:
        output_thread.join(timeout=1)
    if pcb is not None:
        proc.reap_children(pcb.ppid)
    return pcb
