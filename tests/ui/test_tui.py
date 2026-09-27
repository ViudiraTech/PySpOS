'''
 *
 *      test_tui.py
 *      TUI regression locks: the single-window rendering invariant plus both backends.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import inspect
import io
import re

import tui


# Reduce an object's source to real code, dropping comments and docstrings so prose cannot trip a structural assertion.
def _code_only(obj):
    src = inspect.getsource(obj)
    src = re.sub(r'"{3}(?:.|\n)*?"{3}', "", src)
    src = re.sub(r"#.*", "", src)
    return src


# Drawing must land on stdscr; going back to newwin brings back the 'background box only' bug.
def test_curses_backend_never_uses_subwindow():
    src = _code_only(tui)
    for bad in ("curses.newwin", "curses.subwin", "curses.newpad"):
        assert bad not in src, f"TUI 不得使用 {bad}（会导致子窗口被读键刷新覆盖）"


# Regression lock: every getch must act on self.s, the window that is drawn, or ncurses' implicit refresh erases the content.
def test_draw_and_readkey_use_same_window():
    src = _code_only(tui._CursesUI)
    assert "self.s.getch()" in src
    # Reading keys from any other window object is forbidden
    for bad in ("win.getch", "self.win.getch", "stdscr.getch"):
        assert bad not in src, f"读键必须用 self.s.getch()，不应出现 {bad}"


# Regression lock: one erase before drawing and exactly one refresh after, never a second clear that wipes the frame.
def test_frame_does_not_clear_after_draw():
    src = _code_only(tui._CursesUI._frame)
    assert "self.s.erase()" in src
    assert src.count("self.s.refresh()") == 1
    assert "self.s.clear()" not in src


# addstr on the last cell raises curses.error, so _put has to reserve the bottom-right corner.
def test_put_guards_bottom_right_cell():
    src = _code_only(tui._CursesUI._put)
    assert "self.w - x - 1" in src, "必须留出最后一格"


# Regression lock: the curses ACS constants are already characters, and wrapping them in chr() raises ValueError.
def test_acs_constants_are_characters_not_codepoints():
    src = _code_only(tui._CursesUI._frame)
    assert "chr(hline)" not in src and "chr(vline)" not in src
    assert "isinstance(hline, str)" in src


# PYSPOS_TUI picks the backend, and curses is only offered when it imported cleanly.
def test_backend_selection(monkeypatch):
    monkeypatch.setenv("PYSPOS_TUI", "line")
    assert tui.backend() == tui.LINE_BACKEND_MARK
    if tui._CURSES_OK:
        monkeypatch.setenv("PYSPOS_TUI", "curses")
        assert tui.backend() == "curses"


# Replace input() with a scripted answer sequence.
def _feed(monkeypatch, *answers):
    seq = iter(answers)
    monkeypatch.setattr("builtins.input", lambda _p="": next(seq))


# The line backend must render and then return the right value for note, confirm, ask_text and ask_select, back navigation included.
def test_line_backend_roundtrip(monkeypatch, capsys):
    monkeypatch.setenv("PYSPOS_TUI", "line")
    _feed(monkeypatch, "")                 # note: Enter to continue
    assert tui.note("标题", "正文", 1, 3) is None
    out = capsys.readouterr().out
    assert "标题" in out and "正文" in out

    _feed(monkeypatch, "y")
    assert tui.confirm("Q", "body", "继续?", True, 1, 3) is True
    _feed(monkeypatch, "n")
    assert tui.confirm("Q", "body", "继续?", True, 1, 3) is False
    _feed(monkeypatch, "")                 # Enter means the default
    assert tui.confirm("Q", "body", "继续?", True, 1, 3) is True

    _feed(monkeypatch, "abc")
    assert tui.ask_text("T", "body", "名字", "def", 1, 3) == "abc"
    _feed(monkeypatch, "2")
    assert tui.ask_select("S", "body", ["a", "b", "c"], 1, 1, 3) == 1
    _feed(monkeypatch, "<")
    assert tui.ask_select("S", "body", ["a", "b"], 0, 1, 3) is tui.BACK
    _feed(monkeypatch, "<")
    assert tui.confirm("Q", "b", "q", True, 1, 3) is tui.BACK
