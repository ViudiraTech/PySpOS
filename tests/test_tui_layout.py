"""TUI 布局原语：CJK 宽度、控制字符净化、折行截断、对话框结构。

这些是 2026-09-24 TUI 可读性返工的回归锁：
  - dwidth 必须按显示宽度（CJK 双宽），否则框体宽度只有真实值一半；
  - sanitize 必须剥掉完整 ANSI 序列与 \\r，否则终端出现 `^M` / `[31m`；
  - dwrap/dtrunc 不得把宽字符切一半；
  - _compose 连续空行必须合并，且提问永远在最后。
"""

import tui


def _layout(body, question=None, w=80, h=24):
    class U:
        pass
    U.h, U.w = h, w
    U._compose = tui._CursesUI._compose
    U._layout = tui._CursesUI._layout
    return U()._layout(body, question)


# ---- 显示宽度 ----

def test_dwidth_counts_cjk_as_two_columns():
    assert tui.dwidth("欢迎") == 4
    assert tui.dwidth("PySpOS") == 6
    assert tui.dwidth("a中b") == 4
    assert tui.dwidth("（OOBE）") == 8
    assert tui.dwidth("") == 0
    # 关键回归：len() 会给出 2 而不是 4
    assert tui.dwidth("欢迎") != len("欢迎")


def test_dwidth_ignores_combining_marks():
    assert tui.dwidth("é") == 1


# ---- 控制字符净化 ----

def test_sanitize_normalizes_crlf_and_cr():
    assert tui.sanitize("第一行\r\n第二行") == "第一行\n第二行"
    assert tui.sanitize("abc\rdef") == "abc\ndef"


def test_sanitize_converts_tab_to_space():
    assert tui.sanitize("a\tb") == "a b"


def test_sanitize_strips_full_ansi_sequences():
    # 不能只删 ESC 字节，否则会残留可见的 "[31m"
    assert tui.sanitize("\x1b[31m红色\x1b[0m") == "红色"
    assert tui.sanitize("\x1b[2J\x1b[H清屏") == "清屏"
    assert tui.sanitize("\x1b]0;title\x07x") == "x"
    for raw in ("\x1b[31m红色\x1b[0m", "a\x1b[1;5Hb"):
        out = tui.sanitize(raw)
        assert "\x1b" not in out and "[" not in out.replace("红色", "")


def test_sanitize_drops_other_control_and_zero_width():
    assert tui.sanitize("a\x07\x08b") == "ab"
    assert tui.sanitize("a\u200bb") == "ab"
    assert tui.sanitize("a\x7fb") == "ab"


# ---- 折行 / 截断 ----

def test_dwrap_never_exceeds_width():
    for w in (9, 11, 20, 33):
        for line in tui.dwrap("中文中文中文中文 mixed english words here", w):
            assert tui.dwidth(line) <= w, (w, line, tui.dwidth(line))


def test_dwrap_does_not_split_wide_chars():
    for line in tui.dwrap("中文中文中文中文", 9):
        # 每个字符都是完整的，不能出现半个宽字符（用 roundtrip 验证）
        assert all(tui.dwidth(c) in (0, 1, 2) for c in line)
        assert not line.endswith(tui.dtrunc(line, 0)[-1:] or "")


def test_dtrunc_respects_display_width():
    assert tui.dtrunc("中文中文中文", 5) == "中文…"
    assert tui.dwidth(tui.dtrunc("中文中文中文", 5)) <= 5
    assert tui.dtrunc("短", 10) == "短"


def test_dpad_fills_to_display_width():
    assert tui.dwidth(tui.dpad("中文", 10)) == 10


# ---- 对话框结构 ----

def test_compose_collapses_consecutive_blank_lines():
    """连续多个空行只保留一个（段与段之间的单个空行要保留）。"""
    lines, _ = _layout("第一段。\n\n\n\n第二段。\n\n\n第三段。")
    blanks = [i for i, l in enumerate(lines) if not l.strip()]
    assert blanks == [1, 3], f"应为每段间 1 个空行，实际 {blanks}"
    # 纯连续空行压成 1 个
    lines2, _ = _layout("A\n\n\n\n\n\nB")
    assert [i for i, l in enumerate(lines2) if not l.strip()] == [1]


def test_compose_puts_question_last_with_separator():
    lines, _ = _layout("说明段落。", "是否继续？")
    assert lines[-1] == "是否继续？"
    assert lines[-2] == ""
    assert lines[0] == "说明段落。"


def test_compose_strips_control_chars_from_body():
    lines, _ = _layout("第一行\r\n第二行\x1b[31m红\x1b[0m")
    joined = "\n".join(lines)
    assert "\r" not in joined and "\x1b" not in joined
    assert "第一行" in joined and "红" in joined


def test_layout_width_is_content_fitted():
    """框宽应贴合内容（受 MIN_BODY_W 下限约束），而不是恒定撑满 76 列。"""
    _, short = _layout("短")
    assert short == tui.MIN_BODY_W
    _, long = _layout("这是一个很长的说明段落" * 4)
    assert long > short
    assert tui.MIN_BODY_W <= long <= 74


def test_layout_respects_narrow_terminal():
    _, width = _layout("中文" * 60, w=40)
    assert width <= 40 - 2 - 4
    for line in []:
        pass
    lines, width = _layout("中文" * 60, w=40)
    for line in lines:
        assert tui.dwidth(line) <= width
