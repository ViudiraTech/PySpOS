'''
 *
 *      stdinctx.py
 *      Thread-local standard-input handling for shell builtins.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''
import io
import sys
import threading

_LOCAL = threading.local()
_REAL_STDIN = None


# Cache and return the process's real standard-input stream.
def _real_stdin():
    global _REAL_STDIN
    if _REAL_STDIN is None:
        _REAL_STDIN = sys.stdin
    return _REAL_STDIN


# Mark the current background thread as having no standard input.
def suppress():
    _LOCAL.no_stdin = True


# Clear the current thread's suppressed-standard-input marker.
def release():
    _LOCAL.no_stdin = False


# Report whether the current thread has suppressed standard input.
def suppressed():
    return bool(getattr(_LOCAL, "no_stdin", False))


# Report whether stdin is a terminal; suppressed background input is always False.
def is_tty():
    if suppressed():
        return False
    stream = sys.stdin
    try:
        return bool(stream) and stream.isatty()
    except Exception:
        return False


# Read all standard input, returning an empty string when suppressed.
def read_text():
    if suppressed():
        return ""
    stream = sys.stdin
    try:
        if not stream or stream.isatty():
            return ""
        return stream.read()
    except Exception:
        return ""


# Read at most limit lines, or through EOF when limit is None.
# Early termination lets upstream writers receive SIGPIPE instead of blocking.
def read_lines(limit=None):
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


# Yield input lines lazily for commands that can stop before EOF.
def iter_lines():
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
