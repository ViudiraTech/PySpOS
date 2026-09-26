'''
 *
 *      test_tty_safety.py
 *      Terminal input defence: the caret-M retry loop under a broken tty.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import io
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

import ttyutil  # noqa: E402


# CRLF, bare CR and LF all read back as one line, and extra CRs leave no newline behind.
def test_read_line_normalizes_carriage_returns(monkeypatch):
    # CRLF, bare CR and LF all read back as the same content
    for payload, want in (("y\r\n", "y"), ("y\r", "y"), ("y\n", "y"), ("y", "y")):
        monkeypatch.setattr("builtins.input", lambda p="": payload)
        assert ttyutil.read_line() == want, payload
    # Extra bare CRs must not leave a newline behind
    monkeypatch.setattr("builtins.input", lambda p="": "y\r\r\r")
    assert ttyutil.read_line() == "y"


# Only trailing line noise is stripped; leading spaces are part of the answer.
def test_read_line_preserves_leading_whitespace(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda p="": "  a b  \n")
    assert ttyutil.read_line() == "  a b"


# EOF must propagate: the launcher relies on it to detect a non-interactive session, so swallowing it would hang the boot.
def test_read_line_propagates_eof(monkeypatch):
# input() stand-in reporting a closed stdin.
    def _boom(p=""):
        raise EOFError
    monkeypatch.setattr("builtins.input", _boom)
    try:
        ttyutil.read_line()
    except EOFError:
        return
    raise AssertionError("EOFError 应上抛而不是被吞掉")


# An empty line means the default, whichever way that default points.
def test_read_choice_empty_input_uses_default(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda p="": "\n")
    assert ttyutil.read_choice("?", default="n") == "n"
    monkeypatch.setattr("builtins.input", lambda p="": "\n")
    assert ttyutil.read_choice("?", default="y") == "y"


# Core regression: the ^M a broken tty echoes back must not count as invalid input, and the default must win instead.
def test_read_choice_accepts_carets_as_yes(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda p="": "^\r\r\rM\r")
    # ^M is not a valid choice, but after normalising it must not trigger a retry storm
    out = ttyutil.read_choice("?", default="n", max_retries=3)
    assert out == "n"


# Repeatedly invalid input gives up at the retry cap, so a bad terminal cannot flood the screen.
def test_read_choice_retry_limit_stops_spam(monkeypatch, capsys):
    calls = []

# input() stand-in that always feeds the broken-tty caret stream, counting the prompts it received.
    def _bad(p=""):
        calls.append(p)
        return "^\r\rM\r"

    monkeypatch.setattr("builtins.input", _bad)
    assert ttyutil.read_choice("?", default="n", max_retries=3) == "n"
    assert len(calls) <= 4, f"重试次数应受限，实际 {len(calls)}"
    captured = capsys.readouterr()
    assert captured.out.count("无效输入") <= 3, "无效提示刷屏"


# A stdin that is not a terminal is reported as such instead of being poked with termios calls.
def test_ensure_sane_tty_noop_on_non_tty(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO())
    assert ttyutil.ensure_sane_tty() is False


# ensure_sane_tty reports success or failure but must never propagate an exception to the caller.
def test_ensure_sane_tty_never_raises():
    assert ttyutil.ensure_sane_tty() in (True, False)


# printk.confirm still has to work when ttyutil cannot be imported, for instance on a stripped-down host.
def test_confirm_falls_back_when_ttyutil_is_missing(monkeypatch):
    import builtins
    import printk
    monkeypatch.setitem(sys.modules, "ttyutil", None)
    monkeypatch.setattr(builtins, "input", lambda _prompt="": "y")
    assert printk.confirm("继续") is True


# ---- integration level: source locks that stop anyone deleting the backstops ----

# Regression lock: the launcher restores the tty and asks for the slot through the capped reader, never a bare input().
def test_launcher_uses_hardened_choice():
    src = (REPO / "launcher.py").read_text(encoding="utf-8")
    assert "ensure_sane_tty" in src, "launcher 启动时必须恢复终端"
    assert "read_choice" in src, "槽位询问必须用带上限的读法，不能裸 input"
    assert "max_retries" in src


# Regression lock: the curses UI restores terminal modes through an atexit hook, so a crash cannot leave the user's shell broken.
def test_tui_restores_terminal_on_exit():
    src = (REPO / "src" / "tui.py").read_text(encoding="utf-8")
    assert "atexit" in src, "curses 退出必须有 atexit 兜底"
    assert "_restore_terminal" in src


# Regression lock: the forked child restores the shared tty before os._exit, which never runs atexit.
def test_fork_child_restores_terminal_before_exit():
    src = (REPO / "src" / "forkexec.py").read_text(encoding="utf-8")
    i = src.index("os._exit(code)")
    # The restore must come before os._exit, which never runs atexit
    head = src[:i]
    assert "ensure_sane_tty" in head, "子进程 os._exit 前必须恢复共享 tty"
    assert head.rindex("ensure_sane_tty") > head.rindex("finally:")


# Regression lock: printk's own confirm must carry a retry cap.
def test_printk_confirm_has_retry_limit():
    src = (REPO / "src" / "printk.py").read_text(encoding="utf-8")
    assert "max_retries" in src
