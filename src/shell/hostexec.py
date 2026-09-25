#
#   shell/hostexec.py
#   宿主 Linux 程序执行：builtin/注册表都 miss 时的 fork+exec 回退。
#
#   对齐 bash 的成熟语义（另见 oils 的 ExternalProgram 与 ptyprocess 文档）：
#     - 分发顺序：builtin → 注册表 → apps/ → 包命令 → 宿主 PATH；
#     - PATH 查找：stat + 执行位（shutil.which），含 '/' 则按路径直解；
#     - 前台：子进程继承终端（全屏 vt100 程序零改造可跑），父进程在
#       wait 期间把 SIGINT/SIGQUIT 挂空处理器（投递只杀子进程，
#       不掀 shell）；捕获型处置跨 exec 自动复位为默认，子进程天生
#       就是 SIG_DFL，不碰 preexec_fn（多线程父进程下它可能死锁）；
#       同进程组（dash 式简化，不做 tcsetpgrp 作业控制）；
#     - vt100：全程二进制直通，不解码不断行，ESC 序列原样过；
#       TERM 未设置时补 xterm-256color；
#     - 退出后 ttyutil.ensure_sane_tty() 恢复终端（防子进程改坏回显）；
#     - 后台：stdin 接 DEVNULL，stdout/stderr 二进制管道 + 中继线程
#       实时写回父终端（交互式程序请前台运行）；
#     - 进程表：PCB(kind="host", remote=True) + 复用 forkexec 的句柄表，
#       kill/jobs/fg/bg/wait/$! 全部沿用现有语义；
#     - 安全：宿主程序以 OS 用户身份跑在 PySpOS 权限模型之外，
#       每次执行写审计日志（失败不阻断执行）。
#
#   Windows：按普通 Popen 继承控制台尽力而为。
#

import os
import shutil
import signal
import subprocess
import sys
import threading
import time

_STDOUT_FD_OVERRIDE = None
_PATH_BIN_CACHE = None
_WRITE_LOCK = threading.Lock()


def set_override(fd):
    """供 dispatch 的重定向/管道：在本次 handle_command 内把子进程 stdout
    接到指定 fd。同步调用，用完即清，不跨命令。"""
    global _STDOUT_FD_OVERRIDE
    _STDOUT_FD_OVERRIDE = fd


def clear_override():
    global _STDOUT_FD_OVERRIDE
    _STDOUT_FD_OVERRIDE = None


def path_commands():
    """PATH 里可执行文件名的缓存扫描（补全用，会话内缓存）。"""
    global _PATH_BIN_CACHE
    if _PATH_BIN_CACHE is not None:
        return _PATH_BIN_CACHE
    names = set()
    try:
        path_env = os.environ.get("PATH", "")
    except Exception:
        path_env = ""
    for directory in path_env.split(os.pathsep):
        if not directory:
            continue
        try:
            entries = os.listdir(directory)
        except OSError:
            continue
        for entry in entries:
            full = os.path.join(directory, entry)
            try:
                if os.path.isfile(full) and os.access(full, os.X_OK):
                    names.add(entry)
            except OSError:
                continue
    _PATH_BIN_CACHE = sorted(names)
    return _PATH_BIN_CACHE


def resolve(name):
    """解析宿主程序：含 '/' 走路径，否则走 PATH。返回绝对路径或 None。"""
    if not name:
        return None
    if "/" in name:
        candidate = name if os.path.isabs(name) else os.path.join(os.getcwd(), name)
        try:
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return os.path.abspath(candidate)
        except OSError:
            return None
        return None
    try:
        found = shutil.which(name)
    except Exception:
        return None
    return found


def _noop_handler(signum, frame):
    return None


def _make_catchable(signums):
    """把 SIG_IGN 换成可捕获的处理器，返回需要还原的旧值。

    exec 会把「捕获型」处理器复位成 SIG_DFL，但 SIG_IGN 会跨 exec
    保留下来。所以要让子进程拿到默认处置，父进程这边就不能用
    SIG_IGN，得挂处理器：子进程 exec 之后自动就是 SIG_DFL。

    这么绕是为了彻底不碰 preexec_fn —— CPython 明确说它在多线程
    父进程里可能死锁，而 PySpOS 的 shell 进程是有常驻线程的。
    """
    saved = {}
    for signum in signums:
        try:
            if signal.getsignal(signum) is signal.SIG_IGN:
                saved[signum] = signal.SIG_IGN
                signal.signal(signum, _noop_handler)
        except Exception:
            pass
    return saved


def _restore_signals(saved):
    for signum, handler in saved.items():
        try:
            signal.signal(signum, handler)
        except Exception:
            pass


def audit_cmd(cmdline):
    try:
        import main
        import kernel
        from common.audit import audit
        actor = kernel.get_system_username()
        audit(main.root_dir, actor, "host.exec", cmdline)
    except Exception:
        pass


def _register(cmdline, popen_obj):
    """进进程表 + 句柄表（复用 forkexec 的远程信号后端）。"""
    import process as proc
    try:
        shell_pid = proc.current_shell_pid()
    except Exception:
        shell_pid = 0
    pcb = proc.spawn(cmdline, kind="host", remote=True, ppid=shell_pid)
    try:
        proc._table().handles[pcb.pid] = popen_obj
        proc._table().mark_last_bg(pcb.pid)
    except Exception:
        pass
    return pcb


def _pump_to_terminal(src_fd):
    """二进制中继：vt100 转义原样过，不解码。"""
    try:
        dst = sys.stdout.buffer
    except Exception:
        return
    while True:
        try:
            chunk = os.read(src_fd, 65536)
        except OSError:
            break
        if not chunk:
            break
        try:
            with _WRITE_LOCK:
                dst.write(chunk)
                dst.flush()
        except Exception:
            break
    try:
        os.close(src_fd)
    except OSError:
        pass


def _spawn(argv, background, stdout_fd, stdin_fd=None, stderr_fd=None,
             merge_stderr=False, env_extra=None):
    env = dict(os.environ)
    if env_extra:
        env.update({k: str(v) for k, v in env_extra.items()})
    env.setdefault("TERM", "xterm-256color")
    kwargs = {"args": argv, "env": env, "close_fds": True,
              "restore_signals": True}
    if background:
        kwargs["stdin"] = subprocess.DEVNULL if stdin_fd is None else stdin_fd
        if stdout_fd is not None:
            kwargs["stdout"] = stdout_fd
        else:
            kwargs["stdout"] = subprocess.PIPE
        if stderr_fd is not None:
            kwargs["stderr"] = stderr_fd
        elif merge_stderr and stdout_fd is not None:
            kwargs["stderr"] = subprocess.STDOUT
        else:
            kwargs["stderr"] = subprocess.PIPE
        if os.name == "posix":
            kwargs["start_new_session"] = True
    else:
        if stdin_fd is not None:
            kwargs["stdin"] = stdin_fd
        if stdout_fd is not None:
            kwargs["stdout"] = stdout_fd
        if stderr_fd is not None:
            kwargs["stderr"] = stderr_fd
        elif merge_stderr:
            kwargs["stderr"] = subprocess.STDOUT
    saved = ()
    if os.name == "posix":
        saved = _make_catchable((signal.SIGINT, signal.SIGQUIT))
    try:
        return subprocess.Popen(**kwargs)
    finally:
        _restore_signals(saved)


def _restore_tty():
    try:
        import ttyutil
        ttyutil.ensure_sane_tty()
    except Exception:
        pass


def _wait_foreground(popen_obj, pcb):
    import process as proc
    old_handlers = {}
    if os.name == "posix":
        for signame in ("SIGINT", "SIGQUIT"):
            signum = getattr(signal, signame, None)
            if signum is None:
                continue
            try:
                old_handlers[signum] = signal.getsignal(signum)
                signal.signal(signum, _noop_handler)
            except Exception:
                pass
    try:
        code = popen_obj.wait()
    finally:
        _restore_signals(old_handlers)
        _restore_tty()
    if code is None:
        code = 0
    norm = code if code >= 0 else 128 - code
    try:
        proc.finish(pcb.pid, exit_code=norm)
    except Exception:
        pass
    return norm


def _watch_background(popen_obj, pcb):
    """后台回收：退出即转僵尸，走现有 jobs/reap 语义。"""
    import process as proc
    started = time.time()
    try:
        code = popen_obj.wait()
    except Exception:
        return
    if code is None:
        code = 0
    norm = code if code >= 0 else 128 - code
    try:
        proc.child_exited(pcb.pid, exit_code=norm,
                          wall_ms=(time.time() - started) * 1000.0)
    except Exception:
        pass


def _start_relay(popen_obj):
    # dup 出来再关原件：fd 所有权归中继线程，避免和 Popen 析构抢关。
    for stream in (popen_obj.stdout, popen_obj.stderr):
        if stream is None:
            continue
        try:
            dup_fd = os.dup(stream.fileno())
        except OSError:
            continue
        try:
            stream.close()
        except Exception:
            pass
        threading.Thread(target=_pump_to_terminal, args=(dup_fd,),
                         daemon=True).start()


def spawn_host(argv, background=False, stdout_fd=None, stdin_fd=None,
               stderr_fd=None, merge_stderr=False, env_extra=None):
    """起一个宿主进程并进进程表。返回 (Popen, PCB)，不等待。

    background 且 stdout/stderr 落到 PIPE 时自动起中继线程。
    调用方负责 wait_host 或 track_bg。
    """
    popen_obj = _spawn(argv, background, stdout_fd, stdin_fd, stderr_fd,
                       merge_stderr, env_extra)
    cmdline = " ".join(argv)
    pcb = _register(cmdline, popen_obj)
    if background and (popen_obj.stdout is not None
                       or popen_obj.stderr is not None):
        _start_relay(popen_obj)
    return popen_obj, pcb


def wait_host(popen_obj, pcb):
    """前台等待，返回规范化退出码。"""
    return _wait_foreground(popen_obj, pcb)


def track_bg(popen_obj, pcb, cmdline):
    """后台登记：进 jobs 表、打印作业行、起回收线程。"""
    import process as proc
    job = proc.new_job(cmdline, pids=[pcb.pid])
    import printk
    printk.ok(f"[{job.job_id}] {pcb.pid}  {cmdline}\n")
    threading.Thread(target=_watch_background, args=(popen_obj, pcb),
                     daemon=True).start()
    return job


def run_status(tokens, background, stdout_fd=None, stdin_fd=None,
               stderr_fd=None, merge_stderr=False, env_extra=None):
    """找到可执行文件即处理，返回 (handled, status)。

    PATH 里没有返回 (False, 127)，调用方报 127。
    """
    import printk
    if not tokens:
        return False, 127
    path = resolve(tokens[0])
    if path is None:
        return False, 127
    argv = [path] + list(tokens[1:])
    cmdline = " ".join(tokens)
    audit_cmd(cmdline)

    if stdout_fd is None:
        stdout_fd = _STDOUT_FD_OVERRIDE
    try:
        popen_obj, pcb = spawn_host(
            argv, background=background, stdout_fd=stdout_fd,
            stdin_fd=stdin_fd, stderr_fd=stderr_fd,
            merge_stderr=merge_stderr, env_extra=env_extra)
    except FileNotFoundError:
        printk.error(f"{tokens[0]}: 找到但无法执行（文件消失或解释器缺失）\n")
        return True, 126
    except PermissionError:
        printk.error(f"{tokens[0]}: 没有执行权限\n")
        return True, 126
    except OSError as exc:
        printk.error(f"{tokens[0]}: 启动失败: {exc}\n")
        return True, 1

    if background:
        track_bg(popen_obj, pcb, cmdline)
        return True, 0
    return True, wait_host(popen_obj, pcb)


def run(tokens, background):
    """dispatch 回退位入口。找到可执行文件即处理并返回 True；
    PATH 里没有才返回 False（调用方报 127）。"""
    handled, _ = run_status(tokens, background)
    return handled
