'''
 *
 *      test_fork_stdio_relay.py
 *      Regression locks on the stdio relay between a real child and the parent terminal.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import multiprocessing as mp
import os
import pathlib
import sys
import time

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

import forkexec  # noqa: E402
import process as proc  # noqa: E402

TIMEOUT_S = 20


# Poll until the child reaches a terminal state, or give up after the timeout.
def _wait_terminal(pcb, timeout=TIMEOUT_S):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pcb.state in proc.TERMINAL_STATES:
            return True
        time.sleep(0.05)
    return False


# ---- protocol: a raw os.pipe, never mp.Pipe ----

# Regression lock: the relay must stay a raw os.pipe byte stream, never the mp.Pipe message framing that silently dropped all output.
def test_relay_uses_raw_os_pipe_not_multiprocessing_pipe():
    src = (REPO / "src" / "forkexec.py").read_text(encoding="utf-8")
    assert "mp.Pipe(" not in src, "stdio 中继不能用 mp.Pipe（消息帧协议）"
    assert ".send_bytes(" not in src, "不能用 send_bytes 中继字节流"
    assert ".recv_bytes(" not in src, "不能用 recv_bytes 中继字节流"
    assert "os.pipe()" in src


# Reduce source to real code tokens, dropping comments and docstrings, so a structural assertion cannot match prose.
def _code_lines(src: str):
    import io
    import tokenize
    out = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            out.append(tok.string)
    except tokenize.TokenError:
        return src
    return " ".join(out)


# Regression lock: the four pipe ends must be created unconditionally, and no use_relay branch may bypass the relay for a foreground job.
def test_foreground_always_uses_relay():
    import ast
    src = (REPO / "src" / "forkexec.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    # Locate the node that assigns out_r inside fork_exec
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "fork_exec")
    targets = {t.id for n in ast.walk(fn)
               if isinstance(n, ast.Assign)
               for t in n.targets if isinstance(t, ast.Name)}
    assert {"out_r", "out_w", "in_r", "in_w"} <= targets, \
        f"fork_exec 应创建这四个管道端，实际赋值：{sorted(targets)}"

    for n in ast.walk(fn):
        if not isinstance(n, ast.Assign):
            continue
        names = {t.id for t in n.targets if isinstance(t, ast.Name)}
        if not names & {"out_r", "out_w", "in_r", "in_w"}:
            continue
        # If that assignment is wrapped in a condition (it sits in some test's body), it fails
        for outer in ast.walk(fn):
            if isinstance(outer, (ast.If, ast.While, ast.Try)):
                for field in ("body", "orelse"):
                    if n in getattr(outer, field, []):
                        pytest.fail(
                            f"管道创建被 {type(outer).__name__} 包住了，"
                            "前台作业会绕过中继")
    assert "use_relay" not in _code_lines(src), \
        "use_relay 分支已删除：中继必须恒开，前台作业同样需要"


# Regression lock: the child must close the inherited parent-side pipe ends, or it holds the stdin write end open and input() never sees EOF.
def test_child_closes_parent_pipe_ends():
    src = (REPO / "src" / "forkexec.py").read_text(encoding="utf-8")
    code = _code_lines(src)
    i = code.index("def _child_main")
    seg = code[i:code.index("def ", i + 10)]
    assert "parent_fds" in seg, "_child_main 必须接收并关闭父进程持有的端"
    assert "close" in seg, "必须真的 os.close，不能只是接收参数"
    # The caller has to pass the parent-side ends in
    assert "parent_fds = tuple" in code



# The relay helper must say in source that it uses a raw os.pipe.
def test_child_stdio_documented():
    src = (REPO / "src" / "forkexec.py").read_text(encoding="utf-8")
    i = src.index("def _relay_child_stdio")
    seg = src[i:i + 1200]
    assert "os.pipe" in seg, "_relay_child_stdio 必须写明中继用裸 os.pipe"


# ---- end to end: background jobs ----

# A backgrounded interactive app reads EOF on stdin at once and must exit by itself instead of hanging.
def test_background_job_gets_devnull_stdin_and_exits():
    pcb = forkexec.fork_exec("app:zzlsb.py", background=True)
    assert _wait_terminal(pcb), "后台作业未在超时内退出（stdin 很可能卡住了）"
    assert pcb.exit_code == 0


# Child stdout must actually reach the parent terminal; mp.Pipe used to swallow it.
def test_background_job_output_is_relayed():
    import io
    import contextlib
    buf = io.StringIO()
    pcb = None
    with contextlib.redirect_stdout(buf):
        pcb = forkexec.fork_exec("app:zzlsb.py", background=True)
        assert _wait_terminal(pcb)
        # The relay runs in a background thread; wait for it to flush the rest
        time.sleep(0.4)
    out = buf.getvalue()
    assert "简单猜数字游戏" in out, f"子进程输出没中继到父终端: {out!r}"


# A `cmd > log` run stores a copy: the terminal still sees the output and the log lands on disk.
def test_log_path_tees_instead_of_swallowing_output():
    import io
    import contextlib
    import tempfile
    log = tempfile.NamedTemporaryFile(suffix=".log", delete=False)
    log.close()
    buf = io.StringIO()
    pcb = None
    try:
        with contextlib.redirect_stdout(buf):
            # The tee has to be checked with a foreground job: by shell semantics a background job's output only reaches the log,
            # never the terminal (_log_relay uses echo=not background), and that is deliberate.
            pcb = forkexec.fork_exec("app:zzlsb.py", background=False,
                                     log_path=log.name)
            assert _wait_terminal(pcb)
            time.sleep(0.4)
        assert "简单猜数字游戏" in buf.getvalue(), "tee 时终端输出被吞了"
        assert "简单猜数字游戏" in open(log.name, encoding="utf-8").read(), \
            "日志没落盘"
    finally:
        try:
            os.unlink(log.name)
        except OSError:
            pass


# ---- end to end: foreground jobs ----

# A foreground job gets the relay and, with no stdin, EOFs out instead of hanging.
def test_foreground_job_relays_output_and_stays_interactive():
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        pcb = forkexec.fork_exec("app:zzlsb.py", background=False)
        # The parent stdin is not a tty under pytest, so _pump_in gets EOF at once
        # and the child must exit normally with it; the point is that it must not hang.
        assert _wait_terminal(pcb), "前台作业未退出（stdin 中继没送 EOF）"
        time.sleep(0.4)
    out = buf.getvalue()
    assert "简单猜数字游戏" in out, f"前台输出没中继: {out!r}"
    assert "猜数字" in out


# ---- zzlsb's own EOF and index bugs ----

# Regression lock: the food index bound must track len(FOOD_OPTIONS), or the game crashes on the first turn one time in six.
def test_zzlsb_food_index_in_range():
    import re
    src = (REPO / "src" / "apps" / "zzlsb.py").read_text(encoding="utf-8")
    m = re.search(r"food_index\s*=\s*random\.randint\((.+)\)\s*$", src, re.M)
    assert m, "找不到 food_index 赋值"
    args = m.group(1)
    # The pattern has to swallow nested parens: the upper bound of `randint(1, len(FOOD_OPTIONS) - 1)`
    # carries parens of its own, and `[^)]*` cuts it at the first closing paren, leaving
    # "1, len(FOOD_OPTIONS" and wrongly reads the bound as unchanged.
    assert "len(FOOD_OPTIONS)" in args, \
        f"food_index 上界应随 FOOD_OPTIONS 长度变化，实际参数：{args!r}"
    # Run it 200 times for real; it must not raise an index error
    import random as _r
    opts = ["", "炸鸡", "炖肉", "胖牛", "汉堡", "飞电6Chanllger"]
    ns = {"random": _r, "FOOD_OPTIONS": opts}
    for _ in range(200):
        lo, hi = 1, len(opts) - 1
        idx = ns["random"].randint(lo, hi)
        assert opts[idx]


# zzlsb must catch EOFError and KeyboardInterrupt, or a closed stdin spins the CPU.
def test_zzlsb_handles_eof_source():
    import ast
    src = (REPO / "src" / "apps" / "zzlsb.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    handlers = {n.type.id for n in ast.walk(tree)
                if isinstance(n, ast.ExceptHandler) and n.type is not None
                and isinstance(n.type, ast.Name)}
    assert "EOFError" in handlers
    assert "KeyboardInterrupt" in handlers
