"""真子进程 stdio 中继回归锁。

2026-09-24 修的两个真 bug（都表现为「跑 zzlsb 没反应/挂死」）：

1. **协议不匹配**：中继曾用 `multiprocessing.Pipe`，那是 send_bytes /
   recv_bytes 的消息帧协议（4 字节长度头 + 负载），而 stdio 中继写的是
   `os.fdopen(fd).print()` 的裸字节流。父进程 recv_bytes 把裸文本当长度头
   → 直接 EOF → 输出线程静默死掉，子进程输出全丢。

2. **前台作业完全不走中继**：`use_relay = background or start=="spawn"`，
   Linux(fork) 下前台作业 use_relay=False，孙进程直接继承父 tty，既拿不到
   父 stdin 的输入，又会把终端状态污染给父 shell。

另外：后台作业的 stdin 必须接 /dev/null，否则父进程持有管道写端不关，
子进程 input() 永久阻塞（zzlsb 挂死不退的根因）。
"""

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


def _wait_terminal(pcb, timeout=TIMEOUT_S):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pcb.state in proc.TERMINAL_STATES:
            return True
        time.sleep(0.05)
    return False


# ---- 协议：必须是裸 os.pipe，不能是 mp.Pipe ----

def test_relay_uses_raw_os_pipe_not_multiprocessing_pipe():
    """回归锁：源码里不能再出现 mp.Pipe/Connection.send_bytes 中继。"""
    src = (REPO / "src" / "forkexec.py").read_text(encoding="utf-8")
    assert "mp.Pipe(" not in src, "stdio 中继不能用 mp.Pipe（消息帧协议）"
    assert ".send_bytes(" not in src, "不能用 send_bytes 中继字节流"
    assert ".recv_bytes(" not in src, "不能用 recv_bytes 中继字节流"
    assert "os.pipe()" in src


def _code_lines(src: str):
    """只取真正的代码行：去掉注释与文档字符串。

    之前的断言 `'use_relay = background' not in src` 匹配到了**解释这段
    历史 bug 的注释**，导致源码写对了测试却报红。断言源码结构时必须先
    剥掉注释。
    """
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


def test_foreground_always_uses_relay():
    """回归锁：不能有「前台跳过中继」的条件。

    用 AST 判断管道创建是否被条件包裹，而不是在源码里 grep——
    注释里会引用旧的 use_relay 写法作为说明，字符串匹配必然误报。
    """
    import ast
    src = (REPO / "src" / "forkexec.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    # 定位 fork_exec 里给 out_r 赋值的节点
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
        # 若这次赋值本身被条件包住（出现在某个 test 的 body 里），则失败
        for outer in ast.walk(fn):
            if isinstance(outer, (ast.If, ast.While, ast.Try)):
                for field in ("body", "orelse"):
                    if n in getattr(outer, field, []):
                        pytest.fail(
                            f"管道创建被 {type(outer).__name__} 包住了，"
                            "前台作业会绕过中继")
    assert "use_relay" not in _code_lines(src), \
        "use_relay 分支已删除：中继必须恒开，前台作业同样需要"


def test_child_closes_parent_pipe_ends():
    """回归锁：子进程必须关掉继承来的父进程端。

    否则子进程自己捏着 stdin 管的写端，它的读端永远等不到 EOF，
    前台交互式 app 会挂在 input() 上退不掉。pty 手动喂输入的测试会
    掩盖这条路径，因为它绕过了 EOF。
    """
    src = (REPO / "src" / "forkexec.py").read_text(encoding="utf-8")
    code = _code_lines(src)
    i = code.index("def _child_main")
    seg = code[i:code.index("def ", i + 10)]
    assert "parent_fds" in seg, "_child_main 必须接收并关闭父进程持有的端"
    assert "close" in seg, "必须真的 os.close，不能只是接收参数"
    # 调用方要把父进程那两端传进去
    assert "parent_fds = tuple" in code



def test_child_stdio_documented():
    src = (REPO / "src" / "forkexec.py").read_text(encoding="utf-8")
    i = src.index("def _relay_child_stdio")
    seg = src[i:i + 1200]
    assert "os.pipe" in seg, "_relay_child_stdio 必须写明中继用裸 os.pipe"


# ---- 端到端：后台作业 ----

def test_background_job_gets_devnull_stdin_and_exits():
    """后台跑交互 app：stdin 接 /dev/null → 立即 EOF → 必须自行退出。"""
    pcb = forkexec.fork_exec("app:zzlsb.py", background=True)
    assert _wait_terminal(pcb), "后台作业未在超时内退出（stdin 很可能卡住了）"
    assert pcb.exit_code == 0


def test_background_job_output_is_relayed():
    """子进程 stdout 必须真的到达父终端（曾经被 mp.Pipe 吞掉）。"""
    import io
    import contextlib
    buf = io.StringIO()
    pcb = None
    with contextlib.redirect_stdout(buf):
        pcb = forkexec.fork_exec("app:zzlsb.py", background=True)
        assert _wait_terminal(pcb)
        # relay 是后台线程，等它把剩余字节刷完
        time.sleep(0.4)
    out = buf.getvalue()
    assert "简单猜数字游戏" in out, f"子进程输出没中继到父终端: {out!r}"


def test_log_path_tees_instead_of_swallowing_output():
    """`cmd > log` 是存副本，不是把终端输出吞掉。"""
    import io
    import contextlib
    import tempfile
    log = tempfile.NamedTemporaryFile(suffix=".log", delete=False)
    log.close()
    buf = io.StringIO()
    pcb = None
    try:
        with contextlib.redirect_stdout(buf):
            # 必须用前台作业验证 tee：后台作业按 shell 语义输出只进日志、
            # 不回终端（_log_relay 的 echo=not background），那是刻意的。
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


# ---- 端到端：前台作业 ----

def test_foreground_job_relays_output_and_stays_interactive():
    """前台作业要拿到中继；stdin 无输入时应自行 EOF 退出而不是挂死。"""
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        pcb = forkexec.fork_exec("app:zzlsb.py", background=False)
        # 父 stdin 在 pytest 下不是 tty，_pump_in 立刻拿到 EOF，
        # 子进程应随之正常退出——关键是「不能一直挂着」。
        assert _wait_terminal(pcb), "前台作业未退出（stdin 中继没送 EOF）"
        time.sleep(0.4)
    out = buf.getvalue()
    assert "简单猜数字游戏" in out, f"前台输出没中继: {out!r}"
    assert "猜数字" in out


# ---- zzlsb 自身的 EOF / 索引 bug ----

def test_zzlsb_food_index_in_range():
    """回归锁：FOOD_OPTIONS 越界会 1/6 概率一开局就崩。"""
    import re
    src = (REPO / "src" / "apps" / "zzlsb.py").read_text(encoding="utf-8")
    m = re.search(r"food_index\s*=\s*random\.randint\((.+)\)\s*$", src, re.M)
    assert m, "找不到 food_index 赋值"
    args = m.group(1)
    # 正则必须能吃掉嵌套括号：`randint(1, len(FOOD_OPTIONS) - 1)` 的上界
    # 本身就带括号，用 `[^)]*` 会在第一个右括号处截断成
    # "1, len(FOOD_OPTIONS"，误判成没改。
    assert "len(FOOD_OPTIONS)" in args, \
        f"food_index 上界应随 FOOD_OPTIONS 长度变化，实际参数：{args!r}"
    # 实际跑 200 次，不能抛 index error
    import random as _r
    opts = ["", "炸鸡", "炖肉", "胖牛", "汉堡", "飞电6Chanllger"]
    ns = {"random": _r, "FOOD_OPTIONS": opts}
    for _ in range(200):
        lo, hi = 1, len(opts) - 1
        idx = ns["random"].randint(lo, hi)
        assert opts[idx]


def test_zzlsb_handles_eof_source():
    import ast
    src = (REPO / "src" / "apps" / "zzlsb.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    handlers = {n.type.id for n in ast.walk(tree)
                if isinstance(n, ast.ExceptHandler) and n.type is not None
                and isinstance(n.type, ast.Name)}
    assert "EOFError" in handlers
    assert "KeyboardInterrupt" in handlers
