"""TUI 回归：单窗口渲染不变式 + 双后端行为。

背景（2026-09-24 修复的真实 bug）：
  早期实现在 curses.newwin 子窗口上绘制、却用 stdscr.getch() 读键。
  ncurses 规定 wgetch 会在窗口被修改后自动 wrefresh 自身，于是每次读键
  都会把 stdscr 重刷、覆盖掉子窗口内容 → 屏幕上只剩背景框。
  成熟实现（dialog/newt/python-dialog）统一采用「单窗口」：绘制与读键
  在同一个 window 上。本测试用结构断言把这个不变式锁死，防止回归。
"""

import inspect
import io
import re

import tui


def _code_only(obj):
    """去掉注释与 docstring，只留真实代码，避免注释文字误报。"""
    src = inspect.getsource(obj)
    src = re.sub(r'"{3}(?:.|\n)*?"{3}', "", src)
    src = re.sub(r"#.*", "", src)
    return src


def test_curses_backend_never_uses_subwindow():
    """绘制必须直接落在 stdscr；一旦改回 newwin 就会重现“只有背景”问题。"""
    src = _code_only(tui)
    for bad in ("curses.newwin", "curses.subwin", "curses.newpad"):
        assert bad not in src, f"TUI 不得使用 {bad}（会导致子窗口被读键刷新覆盖）"


def test_draw_and_readkey_use_same_window():
    """_CursesUI 所有 getch 调用必须作用于 self.s（与绘制同一窗口）。"""
    src = _code_only(tui._CursesUI)
    assert "self.s.getch()" in src
    # 不得出现对其它窗口对象读键
    for bad in ("win.getch", "self.win.getch", "stdscr.getch"):
        assert bad not in src, f"读键必须用 self.s.getch()，不应出现 {bad}"


def test_frame_does_not_clear_after_draw():
    """_frame 内应在绘制后统一 refresh，且不再对 stdscr 做二次清屏。"""
    src = _code_only(tui._CursesUI._frame)
    assert "self.s.erase()" in src
    assert src.count("self.s.refresh()") == 1
    assert "self.s.clear()" not in src


def test_put_guards_bottom_right_cell():
    """addstr 触底会抛 curses.error，_put 必须预截断。"""
    src = _code_only(tui._CursesUI._put)
    assert "self.w - x - 1" in src, "必须留出最后一格"


def test_acs_constants_are_characters_not_codepoints():
    """curses.ACS_HLINE 本身是字符；再套 chr() 会抛 ValueError。"""
    src = _code_only(tui._CursesUI._frame)
    assert "chr(hline)" not in src and "chr(vline)" not in src
    assert "isinstance(hline, str)" in src


def test_backend_selection(monkeypatch):
    monkeypatch.setenv("PYSPOS_TUI", "line")
    assert tui.backend() == tui.LINE_BACKEND_MARK
    if tui._CURSES_OK:
        monkeypatch.setenv("PYSPOS_TUI", "curses")
        assert tui.backend() == "curses"


def _feed(monkeypatch, *answers):
    seq = iter(answers)
    monkeypatch.setattr("builtins.input", lambda _p="": next(seq))


def test_line_backend_roundtrip(monkeypatch, capsys):
    monkeypatch.setenv("PYSPOS_TUI", "line")
    _feed(monkeypatch, "")                 # note: 回车继续
    assert tui.note("标题", "正文", 1, 3) is None
    out = capsys.readouterr().out
    assert "标题" in out and "正文" in out

    _feed(monkeypatch, "y")
    assert tui.confirm("Q", "body", "继续?", True, 1, 3) is True
    _feed(monkeypatch, "n")
    assert tui.confirm("Q", "body", "继续?", True, 1, 3) is False
    _feed(monkeypatch, "")                 # 回车=默认
    assert tui.confirm("Q", "body", "继续?", True, 1, 3) is True

    _feed(monkeypatch, "abc")
    assert tui.ask_text("T", "body", "名字", "def", 1, 3) == "abc"
    _feed(monkeypatch, "2")
    assert tui.ask_select("S", "body", ["a", "b", "c"], 1, 1, 3) == 1
    _feed(monkeypatch, "<")
    assert tui.ask_select("S", "body", ["a", "b"], 0, 1, 3) is tui.BACK
    _feed(monkeypatch, "<")
    assert tui.confirm("Q", "b", "q", True, 1, 3) is tui.BACK
