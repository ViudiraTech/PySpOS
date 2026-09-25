#
#   shell/shexec.py
#   shell 执行器：跑 shparser 产出的管线与条件链。
#

"""管线按段执行：连续宿主段用真 fd 并发成链，其余段串行缓冲。
后台只 detach 纯宿主/应用管线；含 builtin 的后台管线同步跑并提示，
因为后台线程换 sys.stdin 会和主循环的 input() 抢，撞上就是 EOFError
退出 shell —— 这买卖不做。
"""

import io
import os
import sys
import threading

import printk

from . import hostexec, shparser
from .util import is_safe_filename

_LAST = 0
_VARS = {}
_STDIO_LOCK = threading.Lock()
_ENCODING = (sys.stdout.encoding or "utf-8")


def reset_state():
    global _LAST
    _LAST = 0
    _VARS.clear()


def last_status():
    return _LAST


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


def _invoke(meta, args):
    from . import dispatch as _dispatch
    try:
        ret = _dispatch._invoke_builtin(meta, args)
    except SystemExit:
        raise
    except Exception as exc:
        printk.error(f"命令执行失败: {exc}\n")
        return 1
    return ret if type(ret) is int else 0


def _write_fd(fd, data):
    view = memoryview(data)
    while view:
        try:
            n = os.write(fd, view)
        except BlockingIOError:
            continue
        except OSError:
            break
        if n <= 0:
            break
        view = view[n:]


def _write_file(path, data, append):
    flags = os.O_WRONLY | os.O_CREAT | (os.O_APPEND if append else os.O_TRUNC)
    fd = os.open(path, flags, 0o644)
    try:
        _write_fd(fd, data)
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


def _open_out(path, append):
    flags = os.O_WRONLY | os.O_CREAT | (os.O_APPEND if append else os.O_TRUNC)
    return os.open(path, flags, 0o644)


def _run_builtin(argv, real, stdin_data, out, err):
    """out/err: ('term',) | ('buf',) | ('file', path, append) | ('fd', fd)。

    返回 (status, 截获的 stdout 字节|None)。'buf' 才截获，其余直写。
    """
    import commands as cmd_registry
    meta = cmd_registry.get_meta(real)
    args = " ".join(argv[1:])
    swap_out = out[0] != "term"
    swap_err = err[0] not in ("term", "merge")
    old_in, old_out, old_err = sys.stdin, sys.stdout, sys.stderr
    buf_out, buf_err = io.StringIO(), io.StringIO()
    status = 0
    with _STDIO_LOCK:
        try:
            if stdin_data is not None:
                sys.stdin = io.StringIO(stdin_data.decode(
                    _ENCODING, errors="replace"))
            if swap_out:
                sys.stdout = buf_out
            if swap_err:
                sys.stderr = buf_err
            status = _invoke(meta, args)
        finally:
            sys.stdin, sys.stdout, sys.stderr = old_in, old_out, old_err
    data = buf_out.getvalue().encode(
        _ENCODING, errors="replace") if swap_out else b""
    if swap_out and data.endswith(b"\n\n"):
        data = data[:-1]
    captured = None
    if out[0] == "buf":
        captured = data
    elif out[0] == "file":
        _write_file(out[1], data, out[2])
    elif out[0] == "fd":
        _write_fd(out[1], data)
    err_data = buf_err.getvalue().encode(
        _ENCODING, errors="replace") if swap_err else b""
    if err[0] == "merge" and swap_out:
        if out[0] == "buf":
            captured = (captured or b"") + err_data
        elif out[0] == "file":
            _write_file(out[1], err_data, True)
        elif out[0] == "fd":
            _write_fd(out[1], err_data)
    elif err[0] == "file":
        _write_file(err[1], err_data, err[2])
    elif err[0] == "fd":
        _write_fd(err[1], err_data)
    return status, captured


def _resolve_io(cmd, stdin_data, final_out, depth):
    """算重定向。返回 (stdin_bytes|None, out, err, 错误串|None)。

    final_out 是无重定向时的默认 stdout 去向；显式重定向按从左到右覆盖。
    """
    stdin, out, err = stdin_data, final_out, ("term",)
    for fd, mode, target_spans in cmd["redirects"]:
        if mode == "dup":
            if fd == 2:
                err = ("merge",)
            continue
        try:
            target = _expand_one(target_spans, depth)
        except shparser.ExpandError as exc:
            return None, out, err, str(exc)
        if not is_safe_filename(target):
            return None, out, err, "错误：文件名不允许包含 ../ 或绝对路径"
        try:
            if mode == "<":
                if fd != 0:
                    return None, out, err, f"不支持 {fd}<"
                with open(target, "rb") as f:
                    stdin = f.read()
            else:
                append = mode == ">>"
                if fd == 2:
                    err = ("file", target, append)
                else:
                    out = ("file", target, append)
        except OSError as exc:
            return None, out, err, f"打开 {target} 失败: {exc}"
    return stdin, out, err, None


def _feed_and_close(w, data):
    try:
        _write_fd(w, data)
    finally:
        try:
            os.close(w)
        except OSError:
            pass


def _drain_to_chunks(read_fd):
    chunks = []
    while True:
        try:
            chunk = os.read(read_fd, 65536)
        except OSError:
            break
        if not chunk:
            break
        chunks.append(chunk)
    return b"".join(chunks)


def _run_host_chain(stages, stdin_data, out, background, depth):
    """连续宿主段：真 fd 并发成链。stages=[(argv, redirects)]。

    返回 (status, 截获字节|None)。最后一段的状态即管线状态。
    """
    resolved = []
    for argv, redirects in stages:
        stdin_fd = s_out = s_err = None
        s_out, s_err = ("term",), ("term",)
        for fd, mode, target_spans in redirects:
            if mode == "dup":
                if fd == 2:
                    s_err = ("merge",)
                continue
            try:
                target = _expand_one(target_spans, depth)
            except shparser.ExpandError as exc:
                printk.error(str(exc) + "\n")
                return 1, None
            if not is_safe_filename(target):
                printk.error("错误：文件名不允许包含 ../ 或绝对路径\n")
                return 1, None
            try:
                if mode == "<":
                    if fd != 0:
                        printk.error(f"不支持 {fd}<\n")
                        return 1, None
                    stdin_fd = os.open(target, os.O_RDONLY)
                else:
                    out_fd = _open_out(target, mode == ">>")
                    if fd == 2:
                        s_err = ("opened", out_fd)
                    else:
                        s_out = ("opened", out_fd)
            except OSError as exc:
                printk.error(f"打开 {target} 失败: {exc}\n")
                return 1, None
        resolved.append([argv, stdin_fd, s_out, s_err])
    procs, owned, feeders = [], [], []
    for _, redir_in, redir_out, redir_err in resolved:
        for item in (redir_in, redir_out, redir_err):
            if isinstance(item, int):
                owned.append(item)
            elif isinstance(item, tuple) and item[0] == "opened":
                owned.append(item[1])
    prev_read = None
    n = len(resolved)
    try:
        for index, (argv, redir_in, redir_out, redir_err) in enumerate(resolved):
            if index == 0:
                if redir_in is not None:
                    sin_fd = redir_in
                elif isinstance(stdin_data, bytes) and stdin_data:
                    r, w = os.pipe()
                    owned.extend((r, w))
                    t = threading.Thread(target=_feed_and_close,
                                         args=(w, stdin_data), daemon=True)
                    t.start()
                    feeders.append(t)
                    sin_fd = r
                elif background or isinstance(stdin_data, bytes):
                    sin_fd = os.open(os.devnull, os.O_RDONLY)
                    owned.append(sin_fd)
                else:
                    sin_fd = None
            else:
                sin_fd = prev_read
            unused_read = None
            if redir_in is not None and index > 0:
                sin_fd = redir_in
                owned.append(sin_fd)
                if isinstance(prev_read, int):
                    unused_read = prev_read
            if index == n - 1:
                sout_fd, collect, tail_read = _tail_fd(
                    out, background, redir_out, owned)
            elif isinstance(redir_out, tuple) and redir_out[0] == "opened":
                r, w = os.pipe()
                try:
                    os.close(w)
                except OSError:
                    pass
                owned.append(r)
                prev_read = r
                sout_fd, collect, tail_read = redir_out[1], False, None
            else:
                r, w = os.pipe()
                owned.extend((r, w))
                prev_read = r
                sout_fd, collect, tail_read = w, False, None
            serr_fd, merge = _stage_err(redir_err, owned)
            try:
                popen_obj, pcb = hostexec.spawn_host(
                    argv, background=background, stdout_fd=sout_fd,
                    stdin_fd=sin_fd, stderr_fd=serr_fd,
                    merge_stderr=merge, env_extra=_VARS or None)
            except OSError as exc:
                printk.error(f"{argv[0]}: 启动失败: {exc}\n")
                return 1, None
            hostexec.audit_cmd(" ".join(argv))
            if background:
                hostexec.track_bg(popen_obj, pcb, " ".join(argv))
            procs.append((popen_obj, pcb))
            for fd in (sout_fd, sin_fd, unused_read):
                if isinstance(fd, int) and fd in owned:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                    owned.remove(fd)
        for t in feeders:
            t.join(timeout=30)
        statuses = []
        for popen_obj, pcb in procs:
            if background:
                statuses.append(0)
            else:
                try:
                    statuses.append(hostexec.wait_host(popen_obj, pcb))
                except Exception:
                    statuses.append(1)
        captured = _drain_to_chunks(tail_read) if collect else None
        return (statuses[-1] if statuses else 0), captured
    finally:
        for fd in owned:
            try:
                os.close(fd)
            except OSError:
                pass


def _tail_fd(out, background, redir_out, owned):
    if isinstance(redir_out, tuple) and redir_out[0] == "opened":
        return redir_out[1], False, None
    if out[0] == "file":
        fd = _open_out(out[1], out[2])
        owned.append(fd)
        return fd, False, None
    if out[0] == "fd":
        return out[1], False, None
    if out[0] == "buf" and not background:
        r, w = os.pipe()
        owned.extend((r, w))
        return w, True, r
    return None, False, None


def _stage_err(redir_err, owned):
    if isinstance(redir_err, tuple) and redir_err[0] == "opened":
        return redir_err[1], False
    if redir_err[0] == "file":
        fd = _open_out(redir_err[1], redir_err[2])
        owned.append(fd)
        return fd, False
    if redir_err[0] == "fd":
        return redir_err[1], False
    if redir_err[0] == "merge":
        return None, True
    return None, False


def _run_app(argv, real, kind, target, out, background):
    from . import dispatch as _dispatch
    args = " ".join(argv[1:])
    try:
        if kind == "app":
            _dispatch._fork_external(real, args, background)
        else:
            _dispatch._fork_package(target, args, background)
    except Exception as exc:
        printk.error(f"运行 {argv[0]} 失败: {exc}\n")
        return 1, None
    if out[0] == "buf":
        return 0, b""
    return 0, None


def _expand_stage(cmd, depth):
    try:
        argv = _expand_argv(cmd, depth)
    except shparser.ExpandError as exc:
        printk.error(str(exc) + "\n")
        return None
    if not argv:
        return []
    kind, real, target = _classify(argv)
    return (cmd, argv, kind, real, target)


def _run_pipeline(cmds, stdin_data, out, background, depth):
    """分段：连续 host 并发成链，其余串行缓冲。返回 (status, 产出|None)。"""
    expanded = []
    for cmd in cmds:
        if not _apply_assign(cmd, depth):
            return 1, None
        if not cmd["argv"]:
            stdin, out_r, _, redir_err = _resolve_io(
                cmd, stdin_data, out, depth)
            if redir_err:
                printk.error(redir_err + "\n")
                return 1, None
            if isinstance(out_r, tuple) and out_r[0] == "file":
                try:
                    fd = _open_out(out_r[1], out_r[2])
                    os.close(fd)
                except OSError as exc:
                    printk.error(f"打开 {out_r[1]} 失败: {exc}\n")
                    return 1, None
            continue
        stage = _expand_stage(cmd, depth)
        if stage is None:
            return 1, None
        if stage:
            expanded.append(stage)
    if not expanded:
        return 0, None
    pending, status = stdin_data, 0
    index, total = 0, len(expanded)
    while index < total:
        if index > 0 and pending is None:
            pending = b""
        cmd, argv, kind, real, target = expanded[index]
        if kind == "host":
            chain = [(argv, cmd["redirects"])]
            j = index + 1
            while j < total and expanded[j][2] == "host":
                chain.append((expanded[j][1], expanded[j][0]["redirects"]))
                j += 1
            seg_out = out if j >= total else ("buf",)
            status, produced = _run_host_chain(
                chain, pending, seg_out, background, depth)
            pending = produced
            index = j
            continue
        seg_out = out if index == total - 1 else ("buf",)
        if kind == "builtin":
            stdin, out_r, err, redir_err = _resolve_io(
                cmd, pending, seg_out, depth)
            if redir_err:
                printk.error(redir_err + "\n")
                return 1, None
            status, produced = _run_builtin(argv, real, stdin, out_r, err)
        elif kind == "missing":
            print(f"{argv[0]}: 未找到命令"
                  "（help 查看内置命令；外部程序按 PATH 查找）\n")
            status, produced = 127, None
        else:
            status, produced = _run_app(
                argv, real, kind, target, seg_out, background)
        pending = produced
        index += 1
    if out[0] == "buf":
        return status, pending if isinstance(pending, bytes) else b""
    return status, None


def _redirect_notice(cmds, depth):
    """最后一段落了 `>`/`>>` 文件就回显一句（沿旧行为）。"""
    for cmd in reversed(cmds):
        if not cmd["argv"]:
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


def _pipeline_has_builtin(cmds, depth):
    for cmd in cmds:
        if not cmd["argv"]:
            continue
        try:
            argv = _expand_argv(cmd, depth)
        except shparser.ExpandError:
            return True
        if not argv or _classify(argv)[0] == "builtin":
            return True
    return False


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
    collected = []
    for stmt, cond in program:
        if cond == "&&" and _LAST != 0:
            continue
        if cond == "||" and _LAST == 0:
            continue
        if stmt["background"]:
            if _pipeline_has_builtin(stmt["cmds"], depth):
                printk.warn("后台暂不支持内置命令组合，已在前台执行\n")
                status, _ = _run_pipeline(
                    stmt["cmds"], stdin_bytes, ("term",), False, depth)
            else:
                status, _ = _run_pipeline(
                    stmt["cmds"], stdin_bytes, ("term",), True, depth)
            _LAST = 0
            continue
        status, produced = _run_pipeline(
            stmt["cmds"], stdin_bytes, out, False, depth)
        _LAST = status
        if not capture:
            _redirect_notice(stmt["cmds"], depth)
        if capture and produced:
            collected.append(produced)
    return _LAST, b"".join(collected)
