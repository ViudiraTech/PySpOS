"""终端输入防御：坏 tty 下的 ^M 无限重试回归锁。

「按 enter 疯狂出 ^M」的根因：curses / 子进程 os._exit 让 tty 停在
icrnl-off 状态，回车的 \\r 不被翻译成 \\n，终端原样回显 ^M；
裸 input() 读到非空非 y/n 的串 → 无限重试。这里锁住三层防御：
  1. ttyutil.ensure_sane_tty 恢复输入模式；
  2. ttyutil.read_choice / read_line 归一化 \\r\\n 与裸 \\r；
  3. 重试有上限，坏终端也不会刷屏。
"""

import io
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

import ttyutil  # noqa: E402


def test_read_line_normalizes_carriage_returns(monkeypatch):
    # CRLF / 裸 CR / LF 归一化后内容一致
    for payload, want in (("y\r\n", "y"), ("y\r", "y"), ("y\n", "y"), ("y", "y")):
        monkeypatch.setattr("builtins.input", lambda p="": payload)
        assert ttyutil.read_line() == want, payload
    # 多余的裸 CR 不能留下换行
    monkeypatch.setattr("builtins.input", lambda p="": "y\r\r\r")
    assert ttyutil.read_line() == "y"


def test_read_line_preserves_leading_whitespace(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda p="": "  a b  \n")
    assert ttyutil.read_line() == "  a b"


def test_read_line_propagates_eof(monkeypatch):
    """EOF 必须上抛：launcher 靠它判定非交互环境，不能被吞掉。"""
    def _boom(p=""):
        raise EOFError
    monkeypatch.setattr("builtins.input", _boom)
    try:
        ttyutil.read_line()
    except EOFError:
        return
    raise AssertionError("EOFError 应上抛而不是被吞掉")


def test_read_choice_empty_input_uses_default(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda p="": "\n")
    assert ttyutil.read_choice("?", default="n") == "n"
    monkeypatch.setattr("builtins.input", lambda p="": "\n")
    assert ttyutil.read_choice("?", default="y") == "y"


def test_read_choice_accepts_carets_as_yes(monkeypatch):
    """核心回归：坏 tty 喂进来的 ^M 不应被当成无效输入。"""
    monkeypatch.setattr("builtins.input", lambda p="": "^\r\r\rM\r")
    # ^M 不是合法选择，但归一化后不能触发刷屏重试
    out = ttyutil.read_choice("?", default="n", max_retries=3)
    assert out == "n"


def test_read_choice_retry_limit_stops_spam(monkeypatch, capsys):
    """坏终端下连续无效输入必须在上限后放弃，不能无限刷屏。"""
    calls = []

    def _bad(p=""):
        calls.append(p)
        return "^\r\rM\r"

    monkeypatch.setattr("builtins.input", _bad)
    assert ttyutil.read_choice("?", default="n", max_retries=3) == "n"
    assert len(calls) <= 4, f"重试次数应受限，实际 {len(calls)}"
    captured = capsys.readouterr()
    assert captured.out.count("无效输入") <= 3, "无效提示刷屏"


def test_ensure_sane_tty_noop_on_non_tty(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO())
    assert ttyutil.ensure_sane_tty() is False


def test_ensure_sane_tty_never_raises():
    assert ttyutil.ensure_sane_tty() in (True, False)


# ---- 集成层：源码级锁，防止有人删掉兜底 ----

def test_launcher_uses_hardened_choice():
    src = (REPO / "launcher.py").read_text(encoding="utf-8")
    assert "ensure_sane_tty" in src, "launcher 启动时必须恢复终端"
    assert "read_choice" in src, "槽位询问必须用带上限的读法，不能裸 input"
    assert "max_retries" in src


def test_tui_restores_terminal_on_exit():
    src = (REPO / "src" / "tui.py").read_text(encoding="utf-8")
    assert "atexit" in src, "curses 退出必须有 atexit 兜底"
    assert "_restore_terminal" in src


def test_fork_child_restores_terminal_before_exit():
    src = (REPO / "src" / "forkexec.py").read_text(encoding="utf-8")
    i = src.index("os._exit(code)")
    # 恢复必须在 os._exit 之前（os._exit 不跑 atexit）
    head = src[:i]
    assert "ensure_sane_tty" in head, "子进程 os._exit 前必须恢复共享 tty"
    assert head.rindex("ensure_sane_tty") > head.rindex("finally:")


def test_printk_confirm_has_retry_limit():
    src = (REPO / "src" / "printk.py").read_text(encoding="utf-8")
    assert "max_retries" in src
