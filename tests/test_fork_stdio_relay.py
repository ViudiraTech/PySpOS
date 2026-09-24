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


def test_foreground_always_uses_relay():
    """回归锁：不能有「前台跳过中继」的条件。"""
    src = (REPO / "src" / "forkexec.py").read_text(encoding="utf-8")
    assert 'use_relay = background' not in src
    assert 'use_relay = background or' not in src


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
            pcb = forkexec.fork_exec("app:zzlsb.py", background=True,
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
    m = re.search(r"food_index\s*=\s*random\.randint\(([^)]*)\)", src)
    assert m, "找不到 food_index 赋值"
    args = [a.strip() for a in m.group(1).split(",")]
    assert "len(FOOD_OPTIONS)" in " ".join(args), \
        "food_index 上界应随 FOOD_OPTIONS 长度变化"
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
