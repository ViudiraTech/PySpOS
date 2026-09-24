#
#   forkexec.py
#   真子进程 fork 执行引擎：app 跑在独立 OS 进程里，PCB 映射模拟 PID。
#
#   分层（对齐 Linux）：
#     parent：spawn() 建 PCB(remote=True，不进 EEVDF 虚拟就绪队)，
#             multiprocessing.Process 承载 payload；
#     pump 线程：只 poll 子进程存活/退出，把退出转 Zombie 并结算 CPU 时间，
#             随后交给父进程 wait 回收（僵尸语义）；
#     child：重定向 stdio → 建 syscall RPC 连接 → 跑 app 入口。
#
#   特权操作走 syscall RPC：子进程不能直接改父进程内存（与 Linux 隔离一致），
#   api.* 的写操作改为向 parent 发请求，parent 在自己的地址空间里执行并回传。
#
#   stdio：前台作业继承父终端（等价 bash fork 后继承 fd）；
#   后台作业 stdin 接 DEVNULL、stdout 中继到父 shell（等价 SIGTTIN 场景的安全简化）。
#

import multiprocessing as mp
import os
import sys
import threading
import time
import traceback

import process as proc

SYSCTL_ENV = "PYSPOS_SYSCTL_ADDR"
AUTHKEY = b"pyspos-sysctl-v1"

# POSIX 用 fork（真 fork 语义 + 免 pickle 传参）；Windows 用 spawn
try:
    _CTX = mp.get_context("fork") if os.name == "posix" else mp.get_context("spawn")
except ValueError:
    _CTX = mp.get_context()

_pump_thread = None
_listener = None
_relay_threads = {}


# --------------------------------------------------------------------------
# child 侧
# --------------------------------------------------------------------------

def _relay_child_stdio(out_fd, in_fd):
    """把子进程的 stdio 接到中继管道上。

    中继必须用裸 `os.pipe()` 而非 `multiprocessing.Pipe`：后者是
    send_bytes/recv_bytes 的**消息帧协议**（4 字节长度头 + 负载），
    和这里 `os.fdopen(...).print()` 的裸字节流语义不兼容——
    父进程 recv_bytes 会把裸文本当成长度头，直接 EOF，
    输出线程静默死掉、子进程输出全丢；反方向 stdin 也会把
    长度头当成用户输入喂给 app。
    """
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
    # 以 __exec__ 作为模块名：与历史 open 命令的 exec 语义一致。
    # apps 的守卫有两种写法：
    #   `if __name__ == "__exec__": main()`  → import 时即执行，不能再调 main()
    #   `if __name__ == "__main__": ...`     → import 不执行，需要显式调 main()
    # 因此按源码判断，避免重复执行。
    with open(mod_path, "r", encoding="utf-8") as f:
        source = f.read()
    runs_on_import = '__name__ == "__exec__"' in source

    spec = importlib.util.spec_from_file_location("__exec__", mod_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["__exec__"] = mod
    spec.loader.exec_module(mod)
    if not runs_on_import:
        main_fn = getattr(mod, "main", None)
        if callable(main_fn):
            main_fn()


def _run_spf_file(path):
    import parse_spf
    parse_spf.run_spf(path)


def _child_main(payload, addr, src_dir, apps_dir, env, out_fd, in_fd,
                parent_fds=()):
    """真子进程主体。运行在独立进程，不得引用 parent 的任何内存状态。

    parent_fds 是父进程持有的那几端（stdout 管的读端、stdin 管的写端），
    本进程因为 fork 同样持有它们的副本，**必须先关掉**。

    这是 2026-09-24 实测到的一个真 bug：父进程关掉自己的 in_w 并不够，
    子进程自己手里还捏着一个写端，于是它的 in_r 永远等不到 EOF——前台
    交互式 app 会一直挂在 input() 上不退出。pty 手动喂输入的测试会掩盖
    这条路径，因为它绕过了 EOF。
    """
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
        # 2026-09-24：stdin 关闭是正常终止路径，不该喷 traceback。
        # apps 内部也已逐个处理 EOF；这里是子进程级的兜底防线。
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
        # 子进程与父进程共享同一个 tty。若 app 改过终端模式（尤其跑过
        # curses/TUI），os._exit 会跳过 Python 的清理链，tty 就留在
        # cbreak/icrnl-off 状态——回到父进程后回车就变成 `^M`。
        # os._exit 不跑 atexit，所以这里必须显式恢复。
        try:
            import ttyutil
            ttyutil.ensure_sane_tty()
        except Exception:
            pass
    os._exit(code)


# --------------------------------------------------------------------------
# parent 侧 pump / syscall 服务
# --------------------------------------------------------------------------

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


def _ensure_pump():
    global _pump_thread
    if _pump_thread is None or not _pump_thread.is_alive():
        _pump_thread = threading.Thread(target=_pump_loop,
                                        name="pyspos-pump", daemon=True)
        _pump_thread.start()


def _sysctl_handler(op, args, kwargs):
    """parent 侧特权操作实现（RPC 目标）。"""
    import main
    import btcfg
    import kernel
    import printk

    op = str(op)
    if op == "set_rootstate":
        state = bool(args[0])
        if main.bootcfg.get("locked"):
            printk.warn("系统已锁定，使用临时 ROOT 方法...（重启后失效）")
            main.rootstate = state
        else:
            main.rootstate = state
            cfg = main.bootcfg
            cfg["rootstate"] = state
            btcfg.save_bootcfg_data(cfg)
        _audit("set_rootstate", f"state={state}")
        return True
    if op == "set_lockstate":
        state = bool(args[0])
        cfg = main.bootcfg
        cfg["locked"] = state
        btcfg.save_bootcfg_data(cfg)
        _audit("set_lockstate", f"state={state}")
        return True
    if op == "get_bootcfg":
        return dict(main.bootcfg)
    if op == "get_rootstate":
        return bool(main.rootstate or main.bootcfg.get("rootstate", False))
    if op == "get_lockstate":
        return bool(main.bootcfg.get("locked"))
    if op == "return_token":
        return kernel.token
    if op == "get_system_username":
        return kernel.get_system_username()
    if op == "exit_system":
        threading.Thread(target=_delayed_exit, daemon=True).start()
        return True
    raise ValueError(f"未知系统调用: {op}")


def _audit(action, detail):
    try:
        import main
        from common.audit import audit
        audit(main.root_dir, _sysctl_handler.__name__ and "app", action, detail)
    except Exception:
        pass


def _delayed_exit():
    time.sleep(0.2)
    import main
    main.handle_command("shutdown")


def _serve_client(conn):
    """为一个子进程连接提供 syscall 应答循环。"""
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


def _ensure_listener():
    if _listener is None and not getattr(_ensure_listener, "_tried", False):
        _ensure_listener._tried = True
        threading.Thread(target=_sysctl_accept_loop, name="pyspos-sysctl",
                         daemon=True).start()
        time.sleep(0.05)


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
# 公共入口
# --------------------------------------------------------------------------

def _pump_in_relay(in_w, background):
    """stdin 中继（裸 os.pipe 字节流）。抽出来供 log/tee 路径复用。"""
    if in_w is None:
        return
    if background:
        # 后台作业：不给 stdin，立刻关闭写端 → 子进程读到 EOF 正常退出
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


def _relay_parent_side(out_r, in_w, background):
    """把子进程 stdout 转发到父终端；前台作业额外把父 stdin 灌进子进程。

    out_r / in_w 都是裸 os.pipe() 的 fd（整数），逐块 read/write 转发。
    关键：in_w 必须在后台模式下**立刻关闭**，否则子进程读 stdin 会一直
    阻塞等输入（表现成 zzlsb 之类交互 app 挂死不退）。
    """
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

    threading.Thread(target=_pump_out, daemon=True).start()
    threading.Thread(target=_pump_in_relay, args=(in_w, background),
                     daemon=True).start()


def fork_exec(payload, *, kind="app", background=False, nice=0,
              src_dir=None, apps_dir=None, env=None, log_path=None):
    """在真子进程执行 payload，返回 PCB（remote=True）。

    background=True → stdin 接 /dev/null，输出中继到当前终端（不阻塞 shell）。
    log_path      → 额外把输出落盘（后台作业常用）。
    """
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

    # 中继一律用裸 os.pipe()：stdin/stdout 是字节流，不能用 mp.Pipe 的
    # 消息帧协议（详见 _relay_child_stdio 的注释）。
    #
    # 2026-09-24 修复：原先 `use_relay = background or start=="spawn"`，
    # 于是 Linux(fork) 下的**前台作业完全不走中继**，孙进程直接继承父进程
    # 的 tty 与 Python 缓冲流。两个后果：
    #   1. 子进程对终端模式/缓冲的任何改动会污染父进程 shell（^M 类故障）；
    #   2. 输出与父进程提示交错、且无法落盘。
    # 前台交互恰恰最需要中继——父 stdin 要能灌进子 stdin，所以恒为 True。
    out_fd = in_fd = None
    out_r = out_w = in_r = in_w = None
    # stdout：子进程写 → 父进程读
    out_r, out_w = os.pipe()
    out_fd = out_w              # child 写 stdout
    if background:
        # 后台作业无终端 stdin：直接给 /dev/null，子进程立刻拿到 EOF，
        # 不会卡在 input() 上（这正是 zzlsb 挂死不退的根因）。
        in_fd = os.open(os.devnull, os.O_RDONLY)
    else:
        # stdin ：父进程写 → 子进程读
        in_r, in_w = os.pipe()
        in_fd = in_r              # child 读 stdin

    # 父进程持有的那两端要交给子进程去关掉：fork 会让子进程继承它们的副本，
    # 子进程若自己捏着 stdin 管的写端，它的读端就永远等不到 EOF
    # （前台交互式 app 挂在 input() 上退不掉的根因）。
    parent_fds = tuple(fd for fd in (out_r, in_w) if fd is not None)

    handle = _CTX.Process(
        target=_child_main,
        args=(payload, addr, src_dir, apps_dir, env or {},
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
    # 父进程必须关掉自己那份「子进程用的端」，否则：
    #   - out_w 不关 → 子进程退出后父进程读 stdout 永远等不到 EOF；
    #   - in_r 不关 → 子进程读 stdin 永远等不到 EOF。
    for fd in (out_w, in_r):
        if fd is not None:
            try:
                os.close(fd)
            except (OSError, TypeError):
                pass
    if out_r is not None:
        if log_path:
            # 落盘 **同时** 继续输出到终端：后台作业 `cmd > log` 的语义是
            # 「存一份副本」，不是「把终端输出吞掉」。
            _log_relay(out_r, log_path, echo=not background)
            if not background and in_w is not None:
                threading.Thread(target=_pump_in_relay, args=(in_w, False),
                                 daemon=True).start()
        else:
            _relay_parent_side(out_r, in_w, background)
    proc._table().set_remote_signal_backend(_signal_backend)
    return pcb


def _log_relay(out_r, log_path, echo=False):
    """把子进程 stdout 落盘；echo=True 时同时继续输出到终端（tee）。"""
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


def wait(pid, timeout=30.0):
    """等待子进程结束并回收（wait 语义：结束后从表中移除）。"""
    pcb = proc.wait_for(pid, timeout=timeout)
    if pcb is not None:
        proc.reap_children(pcb.ppid)
    return pcb
