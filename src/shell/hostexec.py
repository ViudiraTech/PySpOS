#
#   shell/hostexec.py
#   宿主 Linux 程序执行：builtin/注册表都 miss 时的 fork+exec 回退。
#
#   对齐 bash 的成熟语义（另见 oils 的 ExternalProgram 与 ptyprocess 文档）：
#     - 分发顺序：builtin → 注册表 → apps/ → 包命令 → 宿主 PATH；
#     - PATH 查找：stat + 执行位（shutil.which），含 '/' 则按路径直解；
#     - 前台：子进程继承终端（全屏 vt100 程序零改造可跑），父进程在
#       wait 期间忽略 SIGINT/SIGQUIT（投递只杀子进程，不掀 shell），
#       子进程在 preexec 里把 SIGINT/SIGQUIT/SIGPIPE/SIGTSTP 复位为默认；
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
#   Windows：无 preexec_fn/pty，按普通 Popen 继承控制台尽力而为。
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


def _child_preexec():
    """子进程 exec 前：信号处置全部复位为默认（对齐 oils 的做法）。

    Python 父进程默认忽略 SIGPIPE；不复位的话管道下游提前退出时
    子进程收不到 BrokenPipe，会行为异常。只在 POSIX 下使用。
    """
    for signame in ("SIGINT", "SIGQUIT", "SIGTSTP", "SIGPIPE",
                    "SIGTTIN", "SIGTTOU"):
        signum = getattr(signal, signame, None)
        if signum is None:
            continue
        try:
            signal.signal(signum, signal.SIG_DFL)
        except Exception:
            pass


def _audit(cmdline):
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


def _spawn(argv, background, stdout_fd):
    """底层 spawn，返回 (Popen, env)。调用方负责 wait/回收。"""
    env = dict(os.environ)
    env.setdefault("TERM", "xterm-256color")
    kwargs = {"args": argv, "env": env, "close_fds": True}
    if os.name == "posix":
        kwargs["preexec_fn"] = _child_preexec
    if background:
        kwargs["stdin"] = subprocess.DEVNULL
        if stdout_fd is not None:
            kwargs["stdout"] = stdout_fd
        else:
            kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
    else:
        if stdout_fd is not None:
            kwargs["stdout"] = stdout_fd
        # 否则 stdin/stdout/stderr 全部继承：全屏程序直接拿到真终端
    return subprocess.Popen(**kwargs)


def _restore_tty():
    try:
        import ttyutil
        ttyutil.ensure_sane_tty()
    except Exception:
        pass


def _wait_foreground(popen_obj, pcb):
    """前台等待：父进程忽略 SIGINT/SIGQUIT（只杀子进程）。"""
    import process as proc
    old_handlers = {}
    if os.name == "posix":
        for signame in ("SIGINT", "SIGQUIT"):
            signum = getattr(signal, signame, None)
            if signum is None:
                continue
            try:
                old_handlers[signum] = signal.getsignal(signum)
                signal.signal(signum, signal.SIG_IGN)
            except Exception:
                pass
    try:
        code = popen_obj.wait()
    finally:
        for signum, handler in old_handlers.items():
            try:
                signal.signal(signum, handler)
            except Exception:
                pass
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


def run(tokens, background):
    """dispatch 回退位入口。找到可执行文件即处理并返回 True；
    PATH 里没有才返回 False（调用方报 127）。"""
    import printk
    if not tokens:
        return False
    path = resolve(tokens[0])
    if path is None:
        return False
    argv = [path] + list(tokens[1:])
    cmdline = " ".join(tokens)
    _audit(cmdline)

    override_fd = _STDOUT_FD_OVERRIDE
    try:
        popen_obj = _spawn(argv, background, override_fd)
    except FileNotFoundError:
        printk.error(f"{tokens[0]}: 找到但无法执行（文件消失或解释器缺失）\n")
        return True
    except PermissionError:
        printk.error(f"{tokens[0]}: 没有执行权限\n")
        return True
    except OSError as exc:
        printk.error(f"{tokens[0]}: 启动失败: {exc}\n")
        return True

    pcb = _register(cmdline, popen_obj)

    if background:
        if override_fd is None:
            # 无重定向：stdout/stderr 走管道中继回终端。
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
        import process as proc
        job = proc.new_job(cmdline, pids=[pcb.pid])
        printk.ok(f"[{job.job_id}] {pcb.pid}  {cmdline}\n")
        threading.Thread(target=_watch_background, args=(popen_obj, pcb),
                         daemon=True).start()
        return True

    _wait_foreground(popen_obj, pcb)
    return True
