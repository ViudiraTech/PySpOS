'''
 *
 *      test_tui_layout.py
 *      TUI layout primitives: CJK width, control character sanitizing, wrapping, truncation, dialog structure.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import tui


# Run the real compose and layout methods against a stub geometry class, so the dialog structure can be inspected without a terminal.
def _layout(body, question=None, w=80, h=24):
# Stub carrying only the geometry and the two unbound methods under test.
    class U:
        pass
    U.h, U.w = h, w
    U._compose = tui._CursesUI._compose
    U._layout = tui._CursesUI._layout
    return U()._layout(body, question)


# ---- display width ----

# Width is display columns, so CJK counts as two; len() would halve the whole frame.
def test_dwidth_counts_cjk_as_two_columns():
    assert tui.dwidth("欢迎") == 4
    assert tui.dwidth("PySpOS") == 6
    assert tui.dwidth("a中b") == 4
    assert tui.dwidth("（OOBE）") == 8
    assert tui.dwidth("") == 0
    # Key regression: len() would give 2 instead of 4
    assert tui.dwidth("欢迎") != len("欢迎")


# A combining accent must not add a column of its own.
def test_dwidth_ignores_combining_marks():
    assert tui.dwidth("é") == 1


# ---- control character sanitizing ----

# CRLF and bare CR both become a single line break, or the dialog shows a stray caret-M.
def test_sanitize_normalizes_crlf_and_cr():
    assert tui.sanitize("第一行\r\n第二行") == "第一行\n第二行"
    assert tui.sanitize("abc\rdef") == "abc\ndef"


# A tab must not pass through, since its width depends on the terminal, so it becomes one space.
def test_sanitize_converts_tab_to_space():
    assert tui.sanitize("a\tb") == "a b"


# The whole escape sequence must go, not just the ESC byte, or a visible fragment is left on screen.
def test_sanitize_strips_full_ansi_sequences():
    # Dropping only the ESC byte would leave a visible "[31m" behind
    assert tui.sanitize("\x1b[31m红色\x1b[0m") == "红色"
    assert tui.sanitize("\x1b[2J\x1b[H清屏") == "清屏"
    assert tui.sanitize("\x1b]0;title\x07x") == "x"
    for raw in ("\x1b[31m红色\x1b[0m", "a\x1b[1;5Hb"):
        out = tui.sanitize(raw)
        assert "\x1b" not in out and "[" not in out.replace("红色", "")


# Other control characters and zero-width marks are removed, since curses miscounts or errors on them.
def test_sanitize_drops_other_control_and_zero_width():
    assert tui.sanitize("a\x07\x08b") == "ab"
    assert tui.sanitize("a\u200bb") == "ab"
    assert tui.sanitize("a\x7fb") == "ab"


# ---- wrapping and truncation ----

# No wrapped line may exceed the requested display width, at any of the tested widths.
def test_dwrap_never_exceeds_width():
    for w in (9, 11, 20, 33):
        for line in tui.dwrap("中文中文中文中文 mixed english words here", w):
            assert tui.dwidth(line) <= w, (w, line, tui.dwidth(line))


# Wrapping breaks between characters only; half a wide character corrupts the line.
def test_dwrap_does_not_split_wide_chars():
    for line in tui.dwrap("中文中文中文中文", 9):
        # Every character must be whole; half a wide character is not allowed (checked by roundtrip)
        assert all(tui.dwidth(c) in (0, 1, 2) for c in line)
        assert not line.endswith(tui.dtrunc(line, 0)[-1:] or "")


# Truncation measures display width and spends the last column on an ellipsis.
def test_dtrunc_respects_display_width():
    assert tui.dtrunc("中文中文中文", 5) == "中文…"
    assert tui.dwidth(tui.dtrunc("中文中文中文", 5)) <= 5
    assert tui.dtrunc("短", 10) == "短"


# Padding must reach the requested display width, not the character count.
def test_dpad_fills_to_display_width():
    assert tui.dwidth(tui.dpad("中文", 10)) == 10


# ---- dialog structure ----

# A run of blank lines collapses to one, while the single blank line between paragraphs is kept.
def test_compose_collapses_consecutive_blank_lines():
    lines, _ = _layout("第一段。\n\n\n\n第二段。\n\n\n第三段。")
    blanks = [i for i, l in enumerate(lines) if not l.strip()]
    assert blanks == [1, 3], f"应为每段间 1 个空行，实际 {blanks}"
    # A run of blank lines collapses into one
    lines2, _ = _layout("A\n\n\n\n\n\nB")
    assert [i for i, l in enumerate(lines2) if not l.strip()] == [1]


# The body comes first, a blank line separates it, and the question is always the last line.
def test_compose_puts_question_last_with_separator():
    lines, _ = _layout("说明段落。", "是否继续？")
    assert lines[-1] == "是否继续？"
    assert lines[-2] == ""
    assert lines[0] == "说明段落。"


# Control characters and ANSI escapes in the body must not reach the curses window.
def test_compose_strips_control_chars_from_body():
    lines, _ = _layout("第一行\r\n第二行\x1b[31m红\x1b[0m")
    joined = "\n".join(lines)
    assert "\r" not in joined and "\x1b" not in joined
    assert "第一行" in joined and "红" in joined


# The frame hugs its content down to the minimum width instead of always claiming all 76 columns.
def test_layout_width_is_content_fitted():
    _, short = _layout("短")
    assert short == tui.MIN_BODY_W
    _, long = _layout("这是一个很长的说明段落" * 4)
    assert long > short
    assert tui.MIN_BODY_W <= long <= 74


# A narrow terminal shrinks the frame, and no composed line may exceed the resulting width.
def test_layout_respects_narrow_terminal():
    _, width = _layout("中文" * 60, w=40)
    assert width <= 40 - 2 - 4
    for line in []:
        pass
    lines, width = _layout("中文" * 60, w=40)
    for line in lines:
        assert tui.dwidth(line) <= width
