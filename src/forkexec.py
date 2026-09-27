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
from multiprocessing.connection import wait as wait_connections
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
_pump_lock = threading.Lock()
_pump_reader, _pump_writer = mp.Pipe(duplex=False)
_pump_pending = False
_watched_children = {}
_relay_threads = {}
_input_relays = {}
# One RPC endpoint per child, keyed by its pid, holding the Listener to close
# once the child is gone.
_child_servers = {}

# The only apps allowed to ask the parent for ROOT authorisation.
ROOT_APPS = {"getroot.py", "bm.py"}


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
        # None is a plain sys.exit() and stays success. Any other non-int code is a
        # message rather than a status, and reporting it as 0 would turn a failed
        # child into a successful one, so it keeps a non-zero exit status.
        if e.code is None:
            code = 0
        elif isinstance(e.code, int):
            code = e.code
        else:
            try:
                sys.stdout.write(f"{e.code}\n")
                sys.stdout.flush()
            except Exception:
                pass
            code = 1
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

# Wait on process sentinels and a registration pipe; an idle shell never polls.
# Keep the owning table and PCB so a reset/PID reuse cannot settle the wrong task.
def _pump_loop():
    global _pump_pending
    while True:
        with _pump_lock:
            children = dict(_watched_children)
        sentinels = {handle.sentinel: (pcb.pid, table, pcb, handle)
                     for handle, (table, pcb) in children.items()}
        ready = wait_connections([_pump_reader, *sentinels])
        if _pump_reader in ready:
            with _pump_lock:
                _pump_reader.recv_bytes()
                _pump_pending = False
        for sentinel in ready:
            if sentinel is _pump_reader:
                continue
            pid, table, pcb, handle = sentinels[sentinel]
            handle.join()
            code = int(handle.exitcode or 0)
            # Release terminal ownership before publishing the child's exit.
            _finish_input_relay(pcb.pid)
            with _pump_lock:
                _watched_children.pop(handle, None)
            if table.handles.get(pid) is handle:
                table.handles.pop(pid, None)
                _close_child_server(pid)
                if table.tasks.get(pid) is pcb and pcb.state not in proc.TERMINAL_STATES:
                    wall = (time.time() - pcb.start_time) * 1000.0
                    table.child_exited(pid, exit_code=code, wall_ms=wall)


def _watch_child(table, pcb, handle):
    global _pump_pending
    with _pump_lock:
        _watched_children[handle] = (table, pcb)
        if not _pump_pending:
            _pump_writer.send_bytes(b"wake")
            _pump_pending = True
    _ensure_pump()


# Start the pump thread once, and start it again if it ever died.
def _ensure_pump():
    global _pump_thread
    with _pump_lock:
        if _pump_thread is None or not _pump_thread.is_alive():
            _pump_thread = threading.Thread(target=_pump_loop,
                                            name="pyspos-pump", daemon=True)
            _pump_thread.start()


# Parent-side implementation of the privileged operations an app may request
# over RPC.
# app_id is the identity the parent bound to this connection when it launched the
# child, never a value the caller supplied, so an app cannot claim to be another
# one. It is empty only on a channel with no bound identity.
def _sysctl_handler(op, args, kwargs, app_id=""):
    import main
    import btcfg
    import kernel
    import printk

    op = str(op)
    if op == "authorize_root":
        claimed = str(kwargs.get("app_id", ""))
        if not app_id:
            # Without a parent-bound identity the shared RPC key only proves the
            # caller is one of our children, never which one, so the claim is not
            # evidence and the request is refused.
            raise PermissionError("无法确认调用方身份，拒绝 ROOT 授权")
        if claimed and claimed != app_id:
            raise PermissionError(f"应用身份不匹配（声称 {claimed}，实际 {app_id}），拒绝 ROOT 授权")
        if app_id not in ROOT_APPS:
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
        import kernel
        from common.audit import audit
        # The record has to name the real source: the request came from the child
        # the shell runs as this user, so a hardcoded placeholder would make every
        # RPC record look like the same unidentified caller.
        audit(main.root_dir, kernel.get_system_username(), action, detail)
    except Exception:
        pass


# Give the RPC reply time to leave before the system shuts down.
def _delayed_exit():
    time.sleep(0.2)
    import main
    main.handle_command("shutdown")


# Answer syscall requests for one child connection until it goes away.
# app_id is the identity the parent bound to this endpoint when it launched the
# child, so the handler can tell who is really asking.
def _serve_client(conn, app_id=""):
    while True:
        try:
            msg = conn.recv()
        except (EOFError, OSError):
            break
        if msg is None:
            break
        req_id, op, args, kwargs = msg
        try:
            ret = _sysctl_handler(op, args, kwargs, app_id=app_id)
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


# Open an RPC endpoint for one child and answer its calls with app_id as the
# caller's identity. The endpoint is bound before the child is started, so the
# child never races the accept thread, and a failed bind is not retried.
def _serve_child_server(app_id):
    from multiprocessing.connection import Listener
    try:
        listener = Listener(("127.0.0.1", 0), authkey=AUTHKEY)
    except Exception:
        return None
    addr = listener.address

    def accept_loop():
        while True:
            try:
                conn = listener.accept()
            except Exception:
                break
            threading.Thread(target=_serve_client, args=(conn, app_id),
                             daemon=True).start()

    threading.Thread(target=accept_loop, name="pyspos-sysctl",
                     daemon=True).start()
    return listener, addr


# Close the RPC endpoint of a child that has ended, so a long-running shell does
# not accumulate one listening socket per app it ever ran.
def _close_child_server(pid):
    listener = _child_servers.pop(pid, None)
    if listener is None:
        return
    try:
        listener.close()
    except Exception:
        pass


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

# Relay only ready bytes while the child lives; never leave a reader at the prompt.
def _pump_in_relay(in_w, background, sentinel=None, stopped=None):
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
        stream = sys.stdin
        try:
            input_fd = stream.fileno()
        except (OSError, ValueError, AttributeError):
            input_fd = None
        console_line = []
        while True:
            if stopped is not None and stopped.is_set():
                break
            if input_fd is not None and os.name == "posix" and sentinel is not None:
                ready = wait_connections((sentinel, input_fd))
                if sentinel in ready or (stopped is not None and stopped.is_set()):
                    break
                if input_fd not in ready:
                    continue
                # BufferedReader.read(1) can prefetch a whole future shell line.
                # Read one kernel byte so all unread typeahead stays on the TTY.
                data = os.read(input_fd, 1)
            elif os.name == "nt" and input_fd is not None and stream.isatty():
                import msvcrt
                if not msvcrt.kbhit():
                    if stopped is not None:
                        stopped.wait(0.02)
                    continue
                char = msvcrt.getwch()
                if char in ("\x00", "\xe0"):
                    msvcrt.getwch()
                    continue
                if char == "\b":
                    if console_line:
                        console_line.pop()
                        sys.stdout.write("\b \b")
                        sys.stdout.flush()
                    continue
                if char == "\x1a" and not console_line:
                    break
                sys.stdout.write("\n" if char == "\r" else char)
                sys.stdout.flush()
                if char != "\r":
                    console_line.append(char)
                    continue
                # Windows emits UTF-16 surrogate pairs as separate console keys.
                line = "".join(console_line).encode("utf-16-le", "surrogatepass").decode("utf-16-le")
                data = (line + "\n").encode("utf-8")
                console_line.clear()
            else:
                buf = getattr(stream, "buffer", None)
                data = buf.read(1) if buf is not None else stream.read(1).encode("utf-8")
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


# Cancel and join the child's input pump before the shell can read again.
def _finish_input_relay(pid):
    relay = _input_relays.pop(pid, None)
    if relay:
        thread, stopped = relay
        stopped.set()
        if thread is not threading.current_thread():
            thread.join(timeout=1)


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
    return [output_thread]


# Run a payload in a real child and return its PCB, marked remote.
# background=True hands the child /dev/null on stdin while its output is still
# relayed to the terminal, so the shell is not blocked. log_path additionally
# tees the output to a file.
def fork_exec(payload, *, kind="app", background=False, nice=0,
              src_dir=None, apps_dir=None, env=None, log_path=None, ppid=0):
    if src_dir is None:
        src_dir = os.path.dirname(os.path.abspath(__file__))
    if apps_dir is None:
        apps_dir = os.path.join(src_dir, "apps")

    comm = payload.split(":", 1)[-1]
    if comm.endswith(".py"):
        comm = comm[:-3]
    pcb = proc.spawn(comm, kind=kind, nice=nice, remote=True, ppid=ppid,
                     note="real child process")

    # A private RPC endpoint per child: the shared key only proves the caller is
    # one of our children, so the app identity has to be bound here, on the
    # parent's side, from the payload this parent itself launched.
    app_id = os.path.basename(payload.split(":", 1)[-1]) or comm
    endpoint = _serve_child_server(app_id)
    if endpoint is None:
        addr = None
    else:
        listener, addr = endpoint
        _child_servers[pcb.pid] = listener

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
    table = proc._table()
    try:
        handle.start()
    except Exception as e:
        proc._table().handles.pop(pcb.pid, None)
        proc.finish(pcb.pid, 1, failed=True)
        # The pipes and the /dev/null stand-in are already open, so the failure
        # path owns them: nothing else can reach them and the parent would leak a
        # descriptor per failed launch for the rest of the shell's life. out_fd and
        # in_fd alias out_w and in_r, so each end is closed exactly once.
        for fd in tuple(dict.fromkeys(
                f for f in (out_r, out_w, in_r, in_w, in_fd) if f is not None)):
            try:
                os.close(fd)
            except (OSError, TypeError):
                pass
        _close_child_server(pcb.pid)
        print(f"fork_exec: 子进程启动失败: {e}")
        return pcb
    table.handles[pcb.pid] = handle
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
            _relay_threads[pcb.pid] = _log_relay(out_r, log_path, echo=not background)
        else:
            _relay_threads[pcb.pid] = _relay_parent_side(out_r, in_w, background)
    if not background and in_w is not None:
        stopped = threading.Event()
        thread = threading.Thread(target=_pump_in_relay,
                                  args=(in_w, False, handle.sentinel, stopped),
                                  name=f"pyspos-input-{pcb.pid}", daemon=True)
        _input_relays[pcb.pid] = (thread, stopped)
        thread.start()
    _watch_child(table, pcb, handle)
    proc._table().set_remote_signal_backend(_signal_backend)
    return pcb


# Write the child's stdout to log_path; with echo=True
# it is printed to the terminal as well, a tee. The relay thread is returned so
# wait() can join it before it reports the child as finished.
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
    thread = threading.Thread(target=_pump, daemon=True)
    thread.start()
    return [thread]


# Wait for a child to end and reap it, the wait
# semantics, then drop the entry from the table.
# The output relays are joined here, so everything the child wrote has reached
# the terminal and the log before wait() returns. The input relay is cancelled
# and joined too, so an exited app cannot consume the next shell command.
def wait(pid, timeout=30.0):
    pcb = proc.wait_for(pid, timeout=timeout)
    if pcb is None:
        return None
    _finish_input_relay(pid)
    for thread in _relay_threads.pop(pid, []):
        try:
            thread.join(timeout=1)
        except RuntimeError:
            pass
    _close_child_server(pid)
    if pcb is not None:
        proc.reap_children(pcb.ppid)
    return pcb
