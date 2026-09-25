'''
 *
 *      hostexec.py
 *      Host Linux program execution fallback for shell commands.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''
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


# Set the temporary stdout fd used by dispatch for this command only.
def set_override(fd):
    global _STDOUT_FD_OVERRIDE
    _STDOUT_FD_OVERRIDE = fd


# Clear the temporary stdout fd after one command.
def clear_override():
    global _STDOUT_FD_OVERRIDE
    _STDOUT_FD_OVERRIDE = None


# Return a session-cached list of executable names found on PATH.
def path_commands():
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


# Resolve a program to an absolute executable path, or return None if absent.
def resolve(name):
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


# Provide a no-op signal handler while the shell waits for a child.
def _noop_handler(signum, frame):
    return None


# Replace ignored signals with catchable handlers and return their saved values.
# After exec, the child resets to SIG_DFL; preexec_fn is avoided because it can
# deadlock in this multithreaded parent.
def _make_catchable(signums):
    saved = {}
    for signum in signums:
        try:
            if signal.getsignal(signum) is signal.SIG_IGN:
                saved[signum] = signal.SIG_IGN
                signal.signal(signum, _noop_handler)
        except Exception:
            pass
    return saved


# Restore handlers from a saved signal map, ignoring unsupported signals.
def _restore_signals(saved):
    for signum, handler in saved.items():
        try:
            signal.signal(signum, handler)
        except Exception:
            pass


# Record host command execution without blocking the command if auditing fails.
def audit_cmd(cmdline):
    try:
        import main
        import kernel
        from common.audit import audit
        actor = kernel.get_system_username()
        audit(main.root_dir, actor, "host.exec", cmdline)
    except Exception:
        pass


# Register the process in the process and handle tables for remote signaling.
def _register(cmdline, popen_obj):
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


# Relay binary data to stdout without decoding or modifying escape sequences.
def _pump_to_terminal(src_fd):
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


# Start a host process with the requested stream, session, and environment settings.
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


# Restore terminal settings after a foreground child exits.
def _restore_tty():
    try:
        import ttyutil
        ttyutil.ensure_sane_tty()
    except Exception:
        pass


# Wait for a foreground process and normalize its exit code for the PCB.
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


# Reap a background process and report its normalized exit status to the job table.
def _watch_background(popen_obj, pcb):
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


# Start daemon relay threads for a background process's piped output.
def _start_relay(popen_obj):
    # Duplicate each stream before closing the original so the relay owns the fd.
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


# Start and register a host process; return its (Popen, PCB) pair without waiting.
# Background pipe output is relayed automatically; callers must wait or track it.
def spawn_host(argv, background=False, stdout_fd=None, stdin_fd=None,
               stderr_fd=None, merge_stderr=False, env_extra=None):
    popen_obj = _spawn(argv, background, stdout_fd, stdin_fd, stderr_fd,
                       merge_stderr, env_extra)
    cmdline = " ".join(argv)
    pcb = _register(cmdline, popen_obj)
    if background and (popen_obj.stdout is not None
                       or popen_obj.stderr is not None):
        _start_relay(popen_obj)
    return popen_obj, pcb


# Wait for a foreground host process and return its normalized exit code.
def wait_host(popen_obj, pcb):
    return _wait_foreground(popen_obj, pcb)


# Register a background process as a job, print its job line, and start reaping.
def track_bg(popen_obj, pcb, cmdline):
    import process as proc
    job = proc.new_job(cmdline, pids=[pcb.pid])
    import printk
    printk.ok(f"[{job.job_id}] {pcb.pid}  {cmdline}\n")
    threading.Thread(target=_watch_background, args=(popen_obj, pcb),
                     daemon=True).start()
    return job


# Resolve and run a host command, returning (handled, status).
# Return (False, 127) when PATH resolution fails so the caller can report 127.
def run_status(tokens, background, stdout_fd=None, stdin_fd=None,
               stderr_fd=None, merge_stderr=False, env_extra=None):
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


# Run a host command when PATH resolution succeeds; return whether it was handled.
def run(tokens, background):
    handled, _ = run_status(tokens, background)
    return handled
