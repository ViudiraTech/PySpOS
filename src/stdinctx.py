#
#   stdinctx.py
#   builtin 读 stdin 的统一入口。
#

"""后台线程里跑 builtin 时不能换 sys.stdin：主循环的 input() 正在用它，
抢了就撞 EOFError，shell 直接退出。改用线程局部标记，让「stdin 是空的」
这件事只对当前后台线程成立。
"""

import io
import sys
import threading

_LOCAL = threading.local()
_REAL_STDIN = None


def _real_stdin():
    global _REAL_STDIN
    if _REAL_STDIN is None:
        _REAL_STDIN = sys.stdin
    return _REAL_STDIN


def suppress():
    _LOCAL.no_stdin = True


def release():
    _LOCAL.no_stdin = False


def suppressed():
    return bool(getattr(_LOCAL, "no_stdin", False))


def is_tty():
    """stdin 是不是终端：后台线程里恒为 False（等于空输入）。"""
    if suppressed():
        return False
    stream = sys.stdin
    try:
        return bool(stream) and stream.isatty()
    except Exception:
        return False


def read_text():
    """读全部 stdin；被抑制时返回空串。"""
    if suppressed():
        return ""
    stream = sys.stdin
    try:
        if not stream or stream.isatty():
            return ""
        return stream.read()
    except Exception:
        return ""


def read_lines(limit=None):
    """按行读，最多 limit 行（None 表示读到 EOF）。

    早停能让上游拿到 SIGPIPE，`yes | head -1` 这类才不会挂死。
    """
    if suppressed():
        return []
    stream = sys.stdin
    try:
        if not stream or stream.isatty():
            return []
        lines = []
        while limit is None or len(lines) < limit:
            line = stream.readline()
            if not line:
                break
            lines.append(line.rstrip("\n"))
        return lines
    except Exception:
        return []


def iter_lines():
    """流式按行读：head 这类要提前收手的命令用它。"""
    if suppressed():
        return
    stream = sys.stdin
    try:
        if not stream or stream.isatty():
            return
        for line in stream:
            yield line.rstrip("\n")
    except Exception:
        return
