#
#   shell/shexec.py
#   shell 执行器：跑 shparser 产出的管线与条件链。
#

"""全管道架构：段与段之间一律真管道，宿主段和 builtin 段都直接写 fd。

之前的做法是把 builtin 输出先收进 StringIO 再喂下去，于是
`yes | head -2` 这种「上游不结束、下游提前收手」必然死锁：上游等
读端、读端等上游。现在每段边界的写端由写者用完即关、读端由读者用完
即关（读者提前退出会让上游拿到 SIGPIPE），并发度和 bash 一致。

- 连续宿主段仍合并成一条真 fd 链并发执行；
- builtin 段把 sys.stdout 换成包着管道写端的 TextIOWrapper，print
  直接落进管道，所以不缓冲、没有 64K 死锁、没有大输出撑爆内存；
- 后台：纯宿主/应用管线真 detach；含 builtin 的在工作线程里跑，
  输出直接写终端，stdin 用 stdinctx 线程局部标记为空——绝不换
  sys.stdin，主循环的 input() 正在用它。
"""

import io
import os
import shlex
import signal
import sys
import threading

import printk

from . import hostexec, shparser
from .util import is_safe_filename

_LAST = 0
_VARS = {}
_ENCODING = (sys.stdout.encoding or "utf-8")
_DEBUG = os.environ.get("PYSPOS_SHELL_DEBUG") == "1"


def _dbg(message):
    """阶段级调试日志。设 PYSPOS_SHELL_DEBUG=1 打开，走 stderr 不污染管道。"""
    if _DEBUG:
        try:
            import time
            sys.stderr.write(f"[shell {time.time() % 1000:8.3f}] {message}\n")
            sys.stderr.flush()
        except Exception:
            pass


def reset_state():
    global _LAST
    _LAST = 0
    _VARS.clear()


def last_status():
    return _LAST


# --------------------------------------------------------------------------
# fd 记账
# --------------------------------------------------------------------------

class _Fds:
    """统一登记本条命令用到的 fd，退出时兜底关掉。"""

    def __init__(self):
        self._owned = []

    def add(self, fd):
        if isinstance(fd, int):
            self._owned.append(fd)
        return fd

    def discard(self, fd):
        if fd in self._owned:
            self._owned.remove(fd)

    def close_all(self):
        while self._owned:
            fd = self._owned.pop()
            try:
                os.close(fd)
            except OSError:
                pass


class _Pipe:
    def __init__(self, fds):
        read_fd, write_fd = os.pipe()
        self.read = fds.add(read_fd)
        self.write = fds.add(write_fd)

    def close_read(self):
        if self.read is not None:
            try:
                os.close(self.read)
            except OSError:
                pass
            self.read = None

    def close_write(self):
        if self.write is not None:
            try:
                os.close(self.write)
            except OSError:
                pass
            self.write = None


def _write_fd(fd, data):
    view = memoryview(data)
    while view:
        try:
            n = os.write(fd, view)
        except BlockingIOError:
            continue
        except OSError:
            return False
        if n <= 0:
            return False
        view = view[n:]
    return True


def _open_out(path, append):
    flags = os.O_WRONLY | os.O_CREAT | (os.O_APPEND if append else os.O_TRUNC)
    return os.open(path, flags, 0o644)


def _write_file(path, data, append):
    fd = _open_out(path, append)
    try:
        _write_fd(fd, data)
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


def _feed_and_close(write_fd, data, fds):
    try:
        _write_fd(write_fd, data)
    finally:
        fds.discard(write_fd)
        try:
            os.close(write_fd)
        except OSError:
            pass


def _devnull_in():
    return os.open(os.devnull, os.O_RDONLY)


def _fmt_spec(spec):
    if spec is None:
        return "term"
    if isinstance(spec, tuple):
        if spec[0] == "fd":
            return f"fd{spec[1]}"
        if spec[0] == "bytes":
            return f"bytes[{len(spec[1])}]"
        if spec[0] == "file":
            return f"file[{spec[1]}]"
        return str(spec[0])
    return str(spec)


# --------------------------------------------------------------------------
# 展开与分类
# --------------------------------------------------------------------------

def _ctx(depth):
    return {"vars": _VARS, "last": _LAST, "depth": depth,
            "run_capture": lambda line, d: run_line(
                line, capture=True, depth=d)[1].decode(
                    _ENCODING, errors="replace")}


def _expand_argv(cmd, depth):
    ctx = _ctx(depth)
    out = []
    for spans in cmd["argv"]:
        out.extend(shparser.expand_word(spans, ctx))
    return out


def _expand_one(spans, depth):
    words = shparser.expand_word(spans, _ctx(depth))
    if len(words) != 1:
        raise shparser.ExpandError("重定向目标有歧义")
    return words[0]


def _apply_assign(cmd, depth):
    for name, value_spans in cmd["assign"]:
        try:
            words = shparser.expand_word(value_spans, _ctx(depth))
        except shparser.ExpandError as exc:
            printk.error(str(exc) + "\n")
            return False
        _VARS[name] = " ".join(words)
    return True


def _classify(argv):
    import commands as cmd_registry
    name = argv[0]
    real = cmd_registry._ALIASES.get(name, name)
    meta = cmd_registry.get_meta(real)
    if meta is not None and meta.fn is not None:
        return "builtin", real, None
    if cmd_registry.resolve_external(real):
        return "app", real, None
    try:
        import main
        target = cmd_registry.resolve_package_command(real, main.root_dir)
    except Exception:
        target = None
    if target is not None:
        return "package", real, target
    if hostexec.resolve(argv[0]) is not None:
        return "host", real, None
    return "missing", real, None


def _builtin_args(argv):
    """把 argv[1:] 拼回一条能被 shlex.split 精确还原的串。

    直接 " ".join 会丢引号边界：grep "a b" 会被拆成 pattern=a file=b。
    shlex.join 负责补引号，带空格/引号/换行的参数都原样还原。
    """
    return shlex.join(argv[1:])


# --------------------------------------------------------------------------
# 重定向解析
# --------------------------------------------------------------------------

def _apply_dup(out, err, src, marker):
    """N>&M：让 fd N 跟 fd M 走同一个去向。

    目标已经在终端/文件/另一个 fd 上都能跟；只在目标是内存缓冲时报错
    （缓冲不是 fd，没法 dup）。
    """
    target = marker[1]
    current = err if target == 2 else out
    if not isinstance(current, tuple):
        return out, err, f"重定向 {src}>&{target}：目标不可用"
    if current[0] == "buf":
        return out, err, f"重定向 {src}>&{target}：内存缓冲不是 fd"
    if src == 1:
        return current, err, None
    if src == 2:
        return out, current, None
    return out, err, f"重定向 {src}>&{target}：只支持 fd 1/2"


def _resolve_redirects(cmd, depth, fds, base_stdin, base_out):
    """把 cmd 上的重定向折进 (stdin, out, err)。

    stdin 形态：None（继承/空）| ("bytes", b"...") | ("file", 路径)
    out/err 形态：("term",) | ("buf",) | ("file", 路径, append) | ("fd", n)
    """
    stdin, out, err = base_stdin, base_out, ("term",)
    err_msg = None
    for fd, mode, target in cmd["redirects"]:
        if mode == "dup":
            if fd == 2:
                err = ("merge",)
            continue
        if mode == "dup_fd":
            out, err, err_msg = _apply_dup(out, err, fd, target)
            if err_msg:
                break
            continue
        try:
            name = _expand_one(target, depth)
        except shparser.ExpandError as exc:
            err_msg = str(exc)
            break
        if not is_safe_filename(name):
            err_msg = "错误：文件名不允许包含 ../ 或绝对路径"
            break
        try:
            if mode == "<":
                if fd != 0:
                    err_msg = f"不支持 {fd}<"
                    break
                stdin = ("file", name)
            else:
                append = mode == ">>"
                if fd == 2:
                    err = ("file", name, append)
                else:
                    out = ("file", name, append)
        except OSError as exc:
            err_msg = f"打开 {name} 失败: {exc}"
    return stdin, out, err, err_msg


# --------------------------------------------------------------------------
# 各段执行
# --------------------------------------------------------------------------

def _invoke_builtin(argv, real, stdin_stream, out, err):
    """在当前线程跑一个 builtin。

    out/err 形态：("term",) | ("fd", n) | ("buf",) | ("file", 路径, append)
    返回 (退出码, 截获的 stdout 字节|None)。SystemExit 原样抛出
    （hotreset/shutdown 靠它退出进程）。
    """
    import commands as cmd_registry
    from . import dispatch as _dispatch
    meta = cmd_registry.get_meta(real)
    args = _builtin_args(argv)
    old_in, old_out, old_err = sys.stdin, sys.stdout, sys.stderr
    swap_out = out[0] in ("fd", "buf", "file")
    swap_err = err[0] in ("fd", "buf", "file")
    buf_out, buf_err = None, None
    out_stream = err_stream = None
    try:
        if stdin_stream is not None:
            sys.stdin = stdin_stream
        if out[0] == "fd":
            out_stream = io.TextIOWrapper(
                open(out[1], "wb", closefd=False, buffering=0),
                encoding=_ENCODING, errors="replace", newline="")
            sys.stdout = out_stream
        elif out[0] in ("buf", "file"):
            buf_out = io.StringIO()
            sys.stdout = buf_out
        if err[0] == "fd":
            err_stream = io.TextIOWrapper(
                open(err[1], "wb", closefd=False, buffering=0),
                encoding=_ENCODING, errors="replace", newline="")
            sys.stderr = err_stream
        elif err[0] in ("buf", "file"):
            buf_err = io.StringIO()
            sys.stderr = buf_err
        try:
            ret = _dispatch._invoke_builtin(meta, args)
        except SystemExit:
            raise
        except BrokenPipeError:
            return 141, None
        except Exception as exc:
            printk.error(f"命令执行失败: {exc}\n")
            return 1, None
    finally:
        sys.stdin, sys.stdout, sys.stderr = old_in, old_out, old_err
        for stream in (out_stream, err_stream):
            if stream is not None:
                try:
                    stream.flush()
                except (OSError, ValueError):
                    pass
    status = ret if type(ret) is int else 0
    captured = None
    if out[0] in ("buf", "file"):
        captured = buf_out.getvalue().encode(_ENCODING, errors="replace")
        if err[0] == "merge" and buf_err is not None:
            captured += buf_err.getvalue().encode(_ENCODING, errors="replace")
    if out[0] == "file":
        _write_file(out[1], captured or b"", out[2])
    err_data = None
    if err[0] == "file":
        err_data = buf_err.getvalue().encode(_ENCODING, errors="replace")
        _write_file(err[1], err_data, err[2])
    return status, captured


def _spawn_host(argv, stdin_spec, out, err, background, fds, env_extra):
    """起一个宿主段。返回 (Popen, PCB, stdin_fd) 或 None。"""
    stdin_fd = None
    owned_stdin = False
    if isinstance(stdin_spec, tuple) and stdin_spec[0] == "fd":
        stdin_fd = stdin_spec[1]
    elif isinstance(stdin_spec, tuple) and stdin_spec[0] == "bytes":
        data = stdin_spec[1]
        if data:
            read_fd, write_fd = os.pipe()
            stdin_fd = fds.add(read_fd)
            fds.add(write_fd)
            threading.Thread(target=_feed_and_close,
                             args=(write_fd, data, fds),
                             daemon=True).start()
        else:
            stdin_fd = fds.add(_devnull_in())
            owned_stdin = True
    elif isinstance(stdin_spec, tuple) and stdin_spec[0] == "file":
        try:
            stdin_fd = fds.add(os.open(stdin_spec[1], os.O_RDONLY))
        except OSError as exc:
            printk.error(f"打开 {stdin_spec[1]} 失败: {exc}\n")
            return None
    elif stdin_spec is None and background:
        stdin_fd = fds.add(_devnull_in())
        owned_stdin = True
    if out[0] == "file":
        stdout_fd = fds.add(_open_out(out[1], out[2]))
    elif out[0] == "fd":
        stdout_fd = out[1]
    else:
        stdout_fd = None
    stderr_fd = None
    merge = err[0] == "merge"
    if err[0] == "file":
        stderr_fd = fds.add(_open_out(err[1], err[2]))
    elif err[0] == "fd":
        stderr_fd = err[1]
    try:
        popen_obj, pcb = hostexec.spawn_host(
            argv, background=background, stdout_fd=stdout_fd,
            stdin_fd=stdin_fd, stderr_fd=stderr_fd,
            merge_stderr=merge or out[0] == "term",
            env_extra=env_extra)
    except OSError as exc:
        printk.error(f"{argv[0]}: 启动失败: {exc}\n")
        return None
    hostexec.audit_cmd(" ".join(argv))
    if background:
        hostexec.track_bg(popen_obj, pcb, " ".join(argv))
        return popen_obj, pcb, None
    if owned_stdin and stdin_fd is not None:
        fds.discard(stdin_fd)
        try:
            os.close(stdin_fd)
        except OSError:
            pass
    return popen_obj, pcb, stdin_fd


def _wait_all(pending):
    """等所有已起的宿主段结束，返回最后一段的退出码。"""
    status = 0
    for popen_obj, pcb in pending:
        try:
            status = hostexec.wait_host(popen_obj, pcb)
        except Exception:
            status = 1
    return status


# --------------------------------------------------------------------------
# 管线
# --------------------------------------------------------------------------

def _stdin_stream(spec, fds):
    """给 builtin 段造一个可读的 stdin 对象。

    spec 形态：None（沿用终端）| ("fd", n) | ("bytes", b"...") | ("file", 路径)
    """
    if spec is None:
        return None
    if isinstance(spec, tuple) and spec[0] == "fd":
        if spec[1] is None:
            return None
        return io.TextIOWrapper(
            os.fdopen(spec[1], "rb", closefd=False),
            encoding=_ENCODING, errors="replace", newline="")
    if isinstance(spec, tuple) and spec[0] == "bytes":
        return io.StringIO(spec[1].decode(_ENCODING, errors="replace"))
    if isinstance(spec, tuple) and spec[0] == "file":
        try:
            fd = fds.add(os.open(spec[1], os.O_RDONLY))
        except OSError as exc:
            printk.error(f"打开 {spec[1]} 失败: {exc}\n")
            return None
        return io.TextIOWrapper(
            os.fdopen(fd, "rb", closefd=False),
            encoding=_ENCODING, errors="replace", newline="")
    return None


_REAL_KINDS = ("host", "app", "package")


def _run_stages(stages, stdin_spec, out, background, depth, fds):
    """按管线跑各段。

    段边界的传输方式按「有没有真进程」选：

    - 边界两侧涉及真进程 → 真管道。消费者若是宿主段就先 spawn，
      于是生产者写管道时有人在读，不会写满死锁；消费者若是 builtin
      就直接从管道 fd 流式读，head/grep -q 提前收手时上游拿到 SIGPIPE。
    - builtin → builtin/group → 内存缓冲。builtin 共用同一个
      sys.stdout，两个 builtin 无法并发写；同线程顺序跑时生产者会
      把管道写满把自己锁死，所以这里必须缓冲。
    """
    total = len(stages)
    pipes = [_Pipe(fds) for _ in range(max(total - 1, 0))]
    spawned = []
    status = 0
    statuses = [0] * total
    buffered = [None] * total

    for index, stage in enumerate(stages):
        if stage["kind"] not in _REAL_KINDS:
            continue
        is_last = index == total - 1
        if index == 0:
            seg_stdin = stdin_spec
        else:
            seg_stdin = ("fd", pipes[index - 1].read)
        if is_last:
            seg_out = out
        else:
            seg_out = ("fd", pipes[index].write)
        _dbg(f"spawn stage[{index}] {stage['kind']} "
             f"{' '.join(stage['argv'])[:60]!r} in={_fmt_spec(seg_stdin)} "
             f"out={_fmt_spec(seg_out)}")
        if stage["kind"] in ("app", "package"):
            if not is_last:
                printk.warn(f"{stage['argv'][0]}: 应用输出不支持接进管道，"
                            "下游将收到空输入\n")
            _run_app(stage, background)
            buffered[index] = b""
            if not is_last:
                pipes[index].close_write()
            continue
        result = _spawn_host(stage["argv"], seg_stdin, seg_out,
                             ("term",), background, fds, _VARS or None)
        if result is None:
            status = 1
            buffered[index] = b""
            continue
        popen_obj, pcb, _ = result
        if background:
            buffered[index] = b""
        else:
            spawned.append((popen_obj, pcb, index))
        if not is_last:
            pipes[index].close_write()

    for index, stage in enumerate(stages):
        kind = stage["kind"]
        if kind in _REAL_KINDS:
            if index > 0:
                pipes[index - 1].close_read()
            continue
        is_last = index == total - 1
        if index == 0:
            seg_stdin = stdin_spec
        else:
            prev = stages[index - 1]
            if prev["kind"] in _REAL_KINDS and buffered[index - 1] is None:
                seg_stdin = ("fd", pipes[index - 1].read)
            else:
                seg_stdin = ("bytes", buffered[index - 1] or b"")
        if is_last:
            seg_out = out
        elif stages[index + 1]["kind"] in _REAL_KINDS:
            seg_out = ("fd", pipes[index].write)
        else:
            seg_out = ("buf",)
        _dbg(f"run   stage[{index}] {kind} "
             f"{' '.join(stage['argv'])[:60]!r} in={_fmt_spec(seg_stdin)} "
             f"out={_fmt_spec(seg_out)}")
        if kind == "builtin":
            stream = _stdin_stream(seg_stdin, fds)
            status, captured = _invoke_builtin(
                stage["argv"], stage["real"], stream, seg_out, ("term",))
            statuses[index] = status
            buffered[index] = captured
        elif kind == "missing":
            print(f"{stage['argv'][0]}: 未找到命令"
                  "（help 查看内置命令；外部程序按 PATH 查找）\n")
            status = 127
            statuses[index] = 127
            buffered[index] = b""
        else:
            status, produced = _run_group_stage(
                stage, seg_stdin, seg_out, background, depth, fds)
            statuses[index] = status
            buffered[index] = produced
        if not is_last:
            pipes[index].close_write()
        if index > 0:
            pipes[index - 1].close_read()

    for pipe in pipes:
        pipe.close_read()
    for popen_obj, pcb, index in spawned:
        try:
            stage_status = hostexec.wait_host(popen_obj, pcb)
        except Exception:
            stage_status = 1
        _dbg(f"wait  stage[{index}] status={stage_status}")
        buffered[index] = buffered[index] if buffered[index] else b""
        if index == total - 1:
            status = stage_status
        statuses[index] = stage_status
    return statuses[total - 1], (buffered[total - 1]
                               if out[0] == "buf" else None)


def _run_group_stage(stage, seg_stdin, seg_out, background, depth, fds):
    if not _apply_assign(stage["cmd"], depth):
        return 1
    out_spec = ("fd", seg_out[1]) if seg_out[0] == "fd" else seg_out
    status, produced = _run_program(stage["cmd"]["program"], seg_stdin,
                                    out_spec, depth, capture=False)
    return status, produced


def _run_app(stage, background):
    from . import dispatch as _dispatch
    args = _builtin_args(stage["argv"])
    try:
        if stage["kind"] == "app":
            _dispatch._fork_external(stage["real"], args, background)
        else:
            _dispatch._fork_package(stage["target"], args, background)
    except Exception as exc:
        printk.error(f"运行 {stage['argv'][0]} 失败: {exc}\n")
        return 1
    return 0


def _prepare_stages(cmds, depth):
    """展开一条管线的各段。返回 (stages, err_status)。"""
    stages = []
    for cmd in cmds:
        if not _apply_assign(cmd, depth):
            return None, 1
        if cmd.get("program") is not None:
            stages.append({"kind": "group", "cmd": cmd, "argv": [],
                           "real": None, "target": None})
            continue
        if not cmd["argv"]:
            if not _touch_redirect(cmd, depth):
                return None, 1
            continue
        try:
            argv = _expand_argv(cmd, depth)
        except shparser.ExpandError as exc:
            printk.error(str(exc) + "\n")
            return None, 1
        if not argv:
            continue
        kind, real, target = _classify(argv)
        stages.append({"kind": kind, "cmd": cmd, "argv": argv,
                       "real": real, "target": target})
    return stages, 0


def _touch_redirect(cmd, depth):
    """纯重定向（没命令）：把目标文件建/截断出来。"""
    for fd, mode, target in cmd["redirects"]:
        if mode not in (">", ">>"):
            continue
        if fd == 2:
            continue
        try:
            name = _expand_one(target, depth)
        except shparser.ExpandError as exc:
            printk.error(str(exc) + "\n")
            return False
        if not is_safe_filename(name):
            printk.error("错误：文件名不允许包含 ../ 或绝对路径\n")
            return False
        try:
            os.close(_open_out(name, mode == ">>"))
        except OSError as exc:
            printk.error(f"打开 {name} 失败: {exc}\n")
            return False
    return True


def _run_pipeline(cmds, stdin_spec, out, background, depth):
    fds = _Fds()
    try:
        stages, status = _prepare_stages(cmds, depth)
        if stages is None:
            return status, None
        if not stages:
            return 0, None
        first_out, err, err_msg = out, ("term",), None
        stdin_spec, first_out, err, err_msg = _resolve_redirects(
            stages[0]["cmd"], depth, fds, stdin_spec, out)
        if err_msg:
            printk.error(err_msg + "\n")
            return 1, None
        if first_out[0] == "term":
            if err[0] == "merge":
                first_out = ("fd", 1)
            elif err[0] in ("file", "fd"):
                first_out = err
        guard = background and _needs_stdin_guard(stages)
        if guard:
            import stdinctx
            stdin_spec = None
            stdinctx.suppress()
        try:
            status, captured = _run_stages(
                stages, stdin_spec, first_out, background, depth, fds)
            if first_out[0] == "buf":
                return status, captured or b""
            return status, None
        finally:
            if guard:
                import stdinctx
                stdinctx.release()
    finally:
        fds.close_all()


def _needs_stdin_guard(stages):
    """后台 builtin 段：stdin 视为空，免得它去抢终端。"""
    for stage in stages:
        if stage["kind"] in ("builtin", "group"):
            return True
    return False


# --------------------------------------------------------------------------
# 语句层
# --------------------------------------------------------------------------

def _run_program(program, stdin_spec, out, depth, capture):
    global _LAST
    produced, status, acc = None, 0, None
    for stmt, cond in program:
        if cond == "&&" and status != 0:
            continue
        if cond == "||" and status == 0:
            continue
        if stmt["background"]:
            _run_background_stmt(stmt, depth)
            status = 0
            _LAST = 0
            continue
        status, produced = _run_pipeline(
            stmt["cmds"], stdin_spec, out, False, depth)
        _LAST = status
        if isinstance(out, tuple) and out[0] == "buf":
            # 缓冲目标下 `;` / 括号里的多条命令要拼成一份输出
            acc = (acc or b"") + (
                produced if isinstance(produced, bytes) else b"")
        if not capture and isinstance(out, tuple) and out[0] == "term":
            _redirect_notice(stmt["cmds"], depth)
    if isinstance(out, tuple) and out[0] == "buf":
        return status, acc if acc is not None else b""
    return status, None


def _run_background_stmt(stmt, depth):
    cmds = stmt["cmds"]
    if _pipeline_has_builtin(cmds, depth):
        _run_bg_thread(cmds, depth)
        return
    fds = _Fds()
    try:
        stages, status = _prepare_stages(cmds, depth)
        if stages is None:
            return
        _run_stages(stages, None, ("term",), True, depth, fds)
    finally:
        fds.close_all()


def _run_bg_thread(cmds, depth):
    """后台含 builtin：工作线程里跑，输出直接写终端，stdin 视为空。"""
    import stdinctx

    def worker():
        stdinctx.suppress()
        try:
            _run_pipeline(cmds, None, ("term",), False, depth)
        except Exception as exc:
            printk.error(f"后台命令失败: {exc}\n")
        finally:
            stdinctx.release()

    threading.Thread(target=worker, daemon=True).start()


def _pipeline_has_builtin(cmds, depth):
    for cmd in cmds:
        if cmd.get("program") is not None:
            return True
        if not cmd["argv"]:
            continue
        try:
            argv = _expand_argv(cmd, depth)
        except shparser.ExpandError:
            return True
        if not argv or _classify(argv)[0] == "builtin":
            return True
    return False


def _redirect_notice(cmds, depth):
    """最后一段落了 `>`/`>>` 文件就回显一句（沿旧行为）。"""
    for cmd in reversed(cmds):
        if cmd.get("program") is not None or not cmd["argv"]:
            continue
        target = None
        for fd, mode, target_spans in cmd["redirects"]:
            if fd == 1 and mode in (">", ">>"):
                try:
                    target = _expand_one(target_spans, depth)
                except shparser.ExpandError:
                    return
        if target is not None:
            printk.ok(f"已重定向输出到: {target}\n")
        return


def run_line(line, stdin_bytes=None, capture=False, depth=0):
    """跑一行。返回 (status, 截获字节)。capture=True 时终端输出被截获。"""
    global _LAST
    try:
        program = shparser.parse(line)
    except (shparser.LexError, shparser.ExpandError) as exc:
        printk.error(f"语法错误: {exc}\n")
        _LAST = 2
        return 2, b""
    out = ("buf",) if capture else ("term",)
    stdin_spec = None if stdin_bytes is None else ("bytes", stdin_bytes)
    status, produced = _run_program(program, stdin_spec, out, depth, capture)
    _LAST = status
    return _LAST, produced if capture and isinstance(produced, bytes) else b""
