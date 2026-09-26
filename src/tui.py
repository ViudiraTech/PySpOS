'''
 *
 *      tui.py
 *      Curses and line-mode terminal UI toolkit.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import os
import re
import sys

try:
    import curses as _curses
    _CURSES_OK = True
except ImportError:
    _curses = None
    _CURSES_OK = False

from syslocale import _

BACK = "<back>"
LINE_BACKEND_MARK = "line"

# Layout constants, following what whiptail and dialog settle on.
PAD = 2            # padding between the text and the border, whiptail leaves 2 per side at 76/80
MIN_W = 34         # smallest frame width, borders included
MIN_BODY_W = 24    # smallest usable body width
MIN_H = 7          # smallest frame height
BORDER_H = 2       # top and bottom border rows
BORDER_V = 2       # left and right border columns
BUTTON_ROWS = 2    # button row plus the blank line above it


# Return the display width of a string: CJK and fullwidth count 2 columns,
# combining marks 0. This is what a CJK TUI has to measure, not len(): whiptail
# uses _newt_wstrlen, and sizing a box with len() halves every Chinese line.
def dwidth(s: str) -> int:
    w = 0
    for ch in str(s):
        if _combining(ch):
            continue
        w += 2 if _wide(ch) else 1
    return w


# Report whether a character is East Asian wide or fullwidth, so it takes two columns.
def _wide(ch: str) -> bool:
    import unicodedata
    return unicodedata.east_asian_width(ch) in ("W", "F")


# Report whether a character is a combining mark, so it adds no column of its own.
def _combining(ch: str) -> bool:
    import unicodedata
    return unicodedata.combining(ch) != 0


# Only the newline is allowed through, every other C0/C1 is sanitised
_ALLOWED_CTRL = {"\n"}

# Whole ANSI/VT escapes: CSI, OSC and single-character forms
_ANSI_RE = re.compile(
    r"\x1b\[[0-?]*[ -/]*[@-~]"       # CSI, colours and cursor moves
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"  # OSC, which also sets the terminal title
    r"|\x1b[@-Z\\-_]"                 # other single-character escapes
)


# Strip control characters and ANSI escapes so they cannot break the layout.
# CRLF from Windows-edited files, piped text and log leftovers all reach us, and
# curses addstr turns \r into a cursor jump and \t into a ragged column.
def sanitize(text) -> str:
    s = str(text)
    if not s:
        return ""
    s = _ANSI_RE.sub("", s)
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    out = []
    for ch in s:
        if ch in _ALLOWED_CTRL:
            out.append(ch)
            continue
        o = ord(ch)
        if o < 0x20 or o == 0x7F or 0x80 <= o <= 0x9F:
            if ch == "\t":
                out.append(" ")
            # Every other C0/C1 byte is dropped
            continue
        if o in (0x200B, 0x200C, 0x200D, 0xFEFF):
            continue
        out.append(ch)
    return "".join(out)


# Truncate to a display width in columns, appending an ellipsis when anything was cut.
def dtrunc(s: str, limit: int) -> str:
    s = str(s)
    if dwidth(s) <= limit:
        return s
    out, w = [], 0
    for ch in s:
        cw = 0 if _combining(ch) else (2 if _wide(ch) else 1)
        if w + cw > limit - 1:
            break
        out.append(ch)
        w += cw
    return "".join(out) + "…"


# Pad on the right with spaces up to a display width in columns.
def dpad(s: str, width: int) -> str:
    return str(s) + " " * max(0, width - dwidth(s))


# Wrap text to a display width, never splitting a wide character and never breaking a whole English word.
def dwrap(text: str, width: int) -> list:
    width = max(8, width)
    out = []
    for para in str(text).split("\n"):
        if not para:
            out.append("")
            continue
        line, w = [], 0
        pending_space = False
        for token in _tokens(para):
            tw = dwidth(token)
            if token == " ":
                # A trailing space does not count towards the width, so no line wraps early
                if line:
                    pending_space = True
                continue
            need = tw + (1 if pending_space else 0)
            if w + need > width and line:
                if tw > width:                     # a token wider than the line is cut hard
                    out.append("".join(line).rstrip())
                    line, w, pending_space = [], 0, False
                    chunk, cw = [], 0
                    for ch in token:
                        c = 0 if _combining(ch) else (2 if _wide(ch) else 1)
                        if cw + c > width:
                            break
                        chunk.append(ch)
                        cw += c
                    line, w = chunk, cw
                    rest = token[len(chunk):]
                    if rest:
                        line, w = [rest], dwidth(rest)
                else:
                    out.append("".join(line).rstrip())
                    line, w, pending_space = [token], tw, False
            else:
                if pending_space:
                    line.append(" ")
                    w += 1
                line.append(token)
                w += tw
                pending_space = False
        if line:
            out.append("".join(line).rstrip())
    return out or [""]


# Split text into tokens: runs of ASCII word characters stay whole, CJK splits per character.
def _tokens(text):
    toks, buf = [], ""
    for ch in str(text):
        if _wide(ch) or ch == " ":
            if buf:
                toks.append(buf)
                buf = ""
            toks.append(ch)
        else:
            buf += ch
    if buf:
        toks.append(buf)
    return toks


# Raised when a prompt cannot be answered: end of input or Ctrl-C at the prompt.
class TUIAbort(Exception):
    pass


# Return the backend in use, 'curses' or 'line'.
# PYSPOS_TUI forces one; otherwise curses also needs a real tty on both ends.
def backend():
    force = os.environ.get("PYSPOS_TUI", "").strip().lower()
    if force == LINE_BACKEND_MARK:
        return LINE_BACKEND_MARK
    if force == "curses" and _CURSES_OK:
        return "curses"
    if _CURSES_OK:
        try:
            if sys.stdin.isatty() and sys.stdout.isatty():
                return "curses"
        except Exception:
            pass
    return LINE_BACKEND_MARK


# Prefix a title with the wizard step counter, or leave it alone when i or n is None.
def _step_prefix(i, n):
    if i is None or n is None:
        return ""
    return _("oobe.step", i=i, n=n) + " "


# --------------------------------------------------------------------------
# Line backend
# --------------------------------------------------------------------------

# Read one line, turning EOF and Ctrl-C into TUIAbort so callers treat both as 'quit'.
def _line_input(prompt):
    try:
        return input(prompt)
    except EOFError:
        raise TUIAbort("EOF")
    except KeyboardInterrupt:
        raise TUIAbort("interrupt")


# Show a message and wait for Enter; '<' returns BACK, anything else returns None.
def _line_note(title, body, i=None, n=None):
    print(f"\n==== {_step_prefix(i, n)}{sanitize(title)} ====\n"
          f"{sanitize(body)}\n")
    s = _line_input(f"[{_('tui.cont')}/{_('tui.back')}] {_('tui.press_enter')}").strip()
    if s == "<":
        return BACK
    return None


# Ask a yes/no question and retry until the answer is valid; empty input takes default, '<' returns BACK.
def _line_confirm(title, body, question, default=True, i=None, n=None):
    d = "Y/n" if default else "y/N"
    print(f"\n==== {_step_prefix(i, n)}{sanitize(title)} ====\n{sanitize(body)}\n"
          f"{sanitize(question)} [{d}] {_('tui.back_hint')}")
    while True:
        s = _line_input("> ").strip().lower()
        if s == "":
            return default
        if s == "<":
            return BACK
        if s in ("y", "yes", "是", "好", "ok"):
            return True
        if s in ("n", "no", "否", "不"):
            return False
        print(_("tui.invalid"))


# Ask for one line of text; Enter keeps default, '!' forces empty, '<' returns BACK.
def _line_text(title, body, question, default="", i=None, n=None):
    print(f"\n==== {_step_prefix(i, n)}{sanitize(title)} ====\n{sanitize(body)}\n"
          f"{sanitize(question)} {_('tui.default_hint')} "
          f"{_('tui.back_hint')} {_('tui.empty_hint')}")
    if default:
        print(f"[{default}]")
    while True:
        s = _line_input("> ")
        if s == "<":
            return BACK
        if s == "!":
            return ""
        if s == "":
            return default
        return s


# Recovery style line menu: the user types an option number and Enter, empty input takes default_idx.
def _line_menu(header, options, default_idx=0):
    print(sanitize(header))
    print()
    for idx, opt in enumerate(options):
        mark = ">" if idx == default_idx else " "
        print(f"{mark} {idx}  {sanitize(str(opt))}")
    print()
    while True:
        s = _line_input("recovery> ").strip()
        if s == "":
            return default_idx
        if s.isdigit() and 0 <= int(s) < len(options):
            return int(s)
        print(_("tui.invalid"))


# List the options numbered from 1 and retry until a valid number, '<' or an empty line; returns an index or BACK.
def _line_select(title, body, options, default_idx=0, i=None, n=None):
    print(f"\n==== {_step_prefix(i, n)}{sanitize(title)} ====\n{sanitize(body)}")
    for idx, opt in enumerate(options, 1):
        mark = "*" if idx - 1 == default_idx else " "
        print(f" {mark}{idx}) {opt}")
    print(_("tui.back_hint"))
    while True:
        s = _line_input(f"{_('tui.choose')} [{default_idx + 1}]: ").strip()
        if s == "":
            return default_idx
        if s == "<":
            return BACK
        if s.isdigit() and 1 <= int(s) <= len(options):
            return int(s) - 1
        print(_("tui.invalid"))


# Print a text progress bar for frac (0.0 to 1.0); it never waits for input.
def _line_progress(title, body, frac):
    bar = int(frac * 30)
    print(f"\n==== {sanitize(title)} ====\n{sanitize(body)}\n"
          f"[{'#' * bar}{'-' * (30 - bar)}] {int(frac * 100)}%")


# --------------------------------------------------------------------------
# Curses backend
# --------------------------------------------------------------------------

# Single-window renderer: draw on stdscr, refresh once, and read keys with
# stdscr.getch(). No sub-windows, because curses wgetch auto-refreshes the
# window it reads and would overwrite a sibling window's contents.
class _CursesUI:

# Bind the window, hide the cursor, enable keypad mode and cache the size and colour pairs.
    def __init__(self, stdscr):
        self.s = stdscr
        try:
            _curses.curs_set(0)
        except Exception:
            pass
        self.s.keypad(True)
        self.h, self.w = self.s.getmaxyx()
        self._init_colors()

# Fill the C_* colour attributes, falling back to plain text on a terminal without colour.
    def _init_colors(self):
        self.C_FRAME = 0
        self.C_TITLE = 0
        self.C_TEXT = 0
        self.C_FOOT = 0
        self.C_SEL = 0
        self.C_HINT = 0
        self.C_BTN = 0
        try:
            if not _curses.has_colors():
                return
            _curses.start_color()
            _curses.use_default_colors()
            defs = [
                (1, _curses.COLOR_CYAN),    # frame
                (2, _curses.COLOR_BLACK),   # title background
                (3, _curses.COLOR_WHITE),   # body text
                (4, _curses.COLOR_BLUE),    # footer
                (5, _curses.COLOR_BLACK),   # selected row, yellow background
                (6, _curses.COLOR_GREEN),   # hints
            ]
            for idx, color in defs:
                _curses.init_pair(idx, color, -1)
            _curses.init_pair(7, _curses.COLOR_BLACK, _curses.COLOR_YELLOW)
            self.C_FRAME = _curses.color_pair(1) | _curses.A_BOLD
            self.C_TITLE = _curses.color_pair(2) | _curses.A_BOLD
            self.C_TEXT = _curses.color_pair(3)
            self.C_FOOT = _curses.color_pair(4) | _curses.A_DIM
            self.C_SEL = _curses.color_pair(7) | _curses.A_BOLD
            self.C_HINT = _curses.color_pair(6)
            self.C_BTN = _curses.color_pair(7) | _curses.A_BOLD
        except Exception:
            pass

# Write text at (y, x) with an attribute, clipped to the screen and to the
# last column. Last line of defence for control characters: even if a caller
# skipped sanitize, \r, \t and ANSI escapes cannot reach the frame.
    def _put(self, y, x, text, attr=0):
        if not (0 <= y < self.h and 0 <= x < self.w):
            return
        text = sanitize(text).replace("\n", " ")
        maxlen = self.w - x - 1          # keep the last cell free so addstr cannot hit the bottom-right corner
        if maxlen <= 0:
            return
        # Truncate by display width, cutting by len would halve a wide character
        out, w = [], 0
        for ch in text:
            cw = 0 if _combining(ch) else (2 if _wide(ch) else 1)
            if w + cw > maxlen:
                break
            out.append(ch)
            w += cw
        try:
            self.s.addstr(y, x, "".join(out), attr)
        except Exception:
            pass

# Draw a centred frame around the already-wrapped body lines, measured by display width.
    def _frame(self, title, body, footer="", sel=None, buttons=None,
               min_content=0):
        h, w = self.h, self.w
        self.s.erase()

        title = sanitize(title)
        body = [sanitize(l) for l in (body or [""])]
        footer = sanitize(footer) if footer else ""
        buttons = [sanitize(b) for b in buttons] if buttons else None
        # Width: the widest of title, body, footer and buttons, plus borders and padding
        need = max([dwidth(title)] + [dwidth(str(l)) for l in body]
                   + [dwidth(footer or "")] + [dwidth(b) for b in (buttons or [])]
                   + [min_content])
        bw = min(max(need + BORDER_V + PAD * 2, MIN_W), w - 2)

        # Height: body lines plus borders plus the button or footer row
        extra = BUTTON_ROWS if buttons else (1 if footer else 0)
        bh = min(len(body) + BORDER_H + extra, h - 1)
        max_body = max(1, bh - BORDER_H - extra)
        if len(body) > max_body:
            body = body[:max_body]

        y0 = max(0, (h - bh) // 2)
        x0 = max(0, (w - bw) // 2)
        lx = x0 + 1 + PAD          # left edge of the body
        rx = x0 + bw - 1 - PAD    # right edge of the body
        span = max(1, rx - lx + 1)

        hline = getattr(_curses, "ACS_HLINE", "-")
        vline = getattr(_curses, "ACS_VLINE", "|")
        if not isinstance(hline, str):
            hline = chr(hline & 0xFF)
        if not isinstance(vline, str):
            vline = chr(vline & 0xFF)

        # Horizontal rules top and bottom; middle rows get only the two verticals, leaving the body clear
        # (an earlier version filled every row with the horizontal rule and patched two columns, so text rows came out as |--text-|)
        self._put(y0, x0, hline * bw, self.C_FRAME)
        self._put(y0 + bh - 1, x0, hline * bw, self.C_FRAME)
        for y in range(y0 + 1, y0 + bh - 1):
            self._put(y, x0, vline, self.C_FRAME)
            self._put(y, x0 + bw - 1, vline, self.C_FRAME)

        # The title sits on the top border, as whiptail's newtOpenWindow does, instead of eating a body row
        cap = f" {dtrunc(title, bw - 6)} "
        self._put(y0, x0 + max(1, (bw - dwidth(cap)) // 2), cap, self.C_TITLE)

        for r, line in enumerate(body):
            attr = self.C_SEL if (sel is not None and r == sel) else self.C_TEXT
            self._put(y0 + 1 + r, lx, dpad(dtrunc(str(line), span), span), attr)

        if buttons:
            bar = "  ".join(
                ("<" + b + ">") if k == getattr(self, "_focus", 0) else (" " + b + " ")
                for k, b in enumerate(buttons))
            bar = f"  {bar}"
            by = y0 + bh - 2
            self._put(by, lx, dpad(dtrunc(bar, span), span), self.C_BTN)
        elif footer:
            self._put(y0 + bh - 2, lx, dpad(dtrunc(footer, span), span), self.C_FOOT)

        self.s.refresh()

# Build the dialog line list: short explanation, blank line, context, then
# the question last so it sits next to the buttons. Consecutive blanks collapse
# to one and every line goes through sanitize.
    def _compose(self, body, question=None):
        merged = []
        for p in sanitize(body).split("\n"):
            if not p.strip():
                if merged and merged[-1] != "":
                    merged.append("")
                continue
            merged.append(p)
        while merged and merged[-1] == "":
            merged.pop()
        lines = list(merged)          # merged is already shaped as paragraph plus blank line, use it as is
        if question:
            if lines:
                lines.append("")
            lines.append(sanitize(question))
        return lines

# Take the frame width from the natural width of the content, then wrap
# inside it; wrapping to a fixed 76 columns first left the box half empty.
# Returns the wrapped lines and the width used.
    def _layout(self, body, question=None):
        raw = self._compose(body, question)
        # Natural width: the longest unwrapped paragraph, capped at a comfortable line length
        cap = max(MIN_BODY_W, min(self.w - 2, 76) - BORDER_V - PAD * 2)
        natural = max((dwidth(p) for p in raw if p), default=0)
        width = max(MIN_BODY_W, min(natural, cap))
        lines = []
        for p in raw:
            lines.extend(dwrap(p, width) if p else [""])
        return lines, width

# Show a message with a single Continue button; Esc returns BACK, Enter returns None.
    def note(self, title, body, i=None, n=None):
        title = _titled(title, i, n)
        # Note: never take the width as `lines, _ = ...`, because `_` is the module-level translation function
        # shadowing it makes the translation call fail with 'int object is not callable'
        lines = self._layout(body)[0]
        while True:
            self._frame(title, lines, buttons=[_("tui.cont")])
            c = self.s.getch()
            if c == 27:
                return BACK
            if c in (10, 13, _curses.KEY_ENTER):
                return None

# Show a yes/no dialog with Continue and Back buttons; Tab or the arrows move focus, Enter takes the focused button, Esc means no.
    def confirm(self, title, body, question, default=True, i=None, n=None):
        title = _titled(title, i, n)
        lines = self._layout(body, question)[0]
        self._focus = 1 if not default else 0
        buttons = [_("tui.cont"), _("tui.back")]
        while True:
            self._frame(title, lines, buttons=buttons)
            c = self.s.getch()
            if c in (9, _curses.KEY_LEFT, _curses.KEY_RIGHT, _curses.KEY_BTAB):
                self._focus = (self._focus + 1) % len(buttons)
            elif c == 27:
                return False
            elif c in (10, 13, _curses.KEY_ENTER):
                return self._focus == 0
            elif c in (ord("y"), ord("Y")):
                return True
            elif c in (ord("n"), ord("N")):
                return False

# Edit a one-line answer in place with a caret; Enter returns it, Esc returns BACK.
    def text(self, title, body, question, default="", i=None, n=None):
        title = _titled(title, i, n)
        lines, width = self._layout(body, question)
        buf = list(default)
        while True:
            view = lines + ["", dtrunc("".join(buf) + "▏", width)]
            self._frame(title, view, buttons=[_("tui.cont"), _("tui.back")])
            c = self.s.getch()
            if c == 27:
                return BACK
            if c in (10, 13, _curses.KEY_ENTER):
                return "".join(buf)
            if c in (_curses.KEY_BACKSPACE, 127, 8):
                buf = buf[:-1]
            elif 32 <= c <= 0x10FFFF:
                try:
                    ch = chr(c)
                except ValueError:
                    continue
                if ch.isprintable() and dwidth("".join(buf)) < width:
                    buf.append(ch)

# Show a scrollable option list and return the chosen index; Esc returns BACK.
# Typing a letter jumps to the first option that starts with it.
    def select(self, title, body, options, default_idx=0, i=None, n=None):
        title = _titled(title, i, n)
        head, width = self._layout(body)
        idx, top = default_idx, 0
        opts_w = max([dwidth(str(o)) for o in options] or [1])
        while True:
            page = max(3, self.h - len(head) - BORDER_H - BUTTON_ROWS - 3)
            if idx < top:
                top = idx
            if idx >= top + page:
                top = idx - page + 1
            view = list(head)
            for k in range(top, min(top + page, len(options))):
                mark = "›" if k == idx else " "
                view.append(f"{mark} {options[k]}")
            if top > 0:
                view[0] = "↑ " + view[0][2:]
            if top + page < len(options):
                view[-1] = "↓ " + view[-1][2:]
            sel_row = len(head) + (idx - top)
            footer = (f"{idx + 1}/{len(options)}    "
                      f"↑↓选择  PgUp/PgDn翻页  Home/End首尾  Enter确认  Esc返回")
            self._frame(title, view, footer=footer, sel=sel_row,
                        min_content=opts_w)
            c = self.s.getch()
            if c == _curses.KEY_UP:
                idx = (idx - 1) % len(options)
            elif c == _curses.KEY_DOWN:
                idx = (idx + 1) % len(options)
            elif c == _curses.KEY_PPAGE:
                idx = max(0, idx - page)
            elif c == _curses.KEY_NPAGE:
                idx = min(len(options) - 1, idx + page)
            elif c == _curses.KEY_HOME:
                idx, top = 0, 0
            elif c == _curses.KEY_END:
                idx = len(options) - 1
            elif c == 27:
                return BACK
            elif c in (10, 13, _curses.KEY_ENTER):
                return idx
            elif 32 <= c < 127:
                ch = chr(c).lower()
                for j, opt in enumerate(options):
                    if str(opt).lower().startswith(ch):
                        idx, top = j, j
                        break

# AOSP Recovery style full-screen text menu: no frame, '>' plus reverse
# video for the selection, scrolling to keep it visible. Arrows wrap, Home/End
# jump to the ends, Enter confirms, Esc returns BACK.
    def menu(self, header, options, default_idx=0):
        head = [sanitize(l) for l in str(header).split("\n")]
        opts = [sanitize(str(o)) for o in options]
        idx = max(0, min(default_idx, len(opts) - 1))
        top = 0
        while True:
            self.s.erase()
            h, w = self.h, self.w
            y = 1
            for l in head:
                self._put(y, 2, l, self.C_TEXT)
                y += 1
            y += 1
            page = max(1, h - y - 1)      # the last row is left for the footer hint
            if idx < top:
                top = idx
            if idx >= top + page:
                top = idx - page + 1
            for k in range(top, min(top + page, len(opts))):
                mark = ">" if k == idx else " "
                attr = (_curses.A_REVERSE | _curses.A_BOLD) if k == idx else self.C_TEXT
                self._put(y, 2, f"{mark} {k}  {opts[k]}", attr)
                y += 1
            self._put(h - 1, 2, "↑↓移动  回车确认  Esc返回", self.C_FOOT)
            self.s.refresh()
            c = self.s.getch()
            if c == _curses.KEY_UP:
                idx = (idx - 1) % len(opts)
            elif c == _curses.KEY_DOWN:
                idx = (idx + 1) % len(opts)
            elif c == _curses.KEY_HOME:
                idx, top = 0, 0
            elif c == _curses.KEY_END:
                idx = len(opts) - 1
            elif c == 27:
                return BACK
            elif c in (10, 13, _curses.KEY_ENTER):
                return idx

# Draw a progress bar for frac (0.0 to 1.0) and hold the screen for a quarter second.
    def progress(self, title, body, frac):
        lines, width = self._layout(body)
        filled = int(width * max(0.0, min(1.0, frac)))
        bar = "█" * filled + "░" * (width - filled)
        lines += ["", f"[{bar}] {int(frac * 100):3d}%"]
        self._frame(title, lines, footer="")
        _curses.napms(250)



# Prefix the title with the step counter when the caller passed both i and n.
def _titled(title, i, n):
    if i is None or n is None:
        return title
    from syslocale import _ as _t
    return f"{_t('oobe.step', i=i, n=n)} {title}"


# Write a diagnostic to stderr when PYSPOS_TUI_DEBUG is set, because a downgrade reason must stay visible.
def _debug(msg):
    if os.environ.get("PYSPOS_TUI_DEBUG"):
        import sys as _s
        _s.stderr.write(f"[tui] {msg}\n")
        _s.stderr.flush()


# Best-effort terminal restore after a curses session; atexit and finally
# both call it. curses.wrapper skips endwin() when a child os._exit()s, on
# SIGKILL or when an exception escapes it, leaving icrnl off: Enter echoes as ^M.
def _restore_terminal():
    try:
        if _curses is not None and _curses.isendwin() is False:
            _curses.endwin()
    except Exception:
        pass
    try:
        import ttyutil
        ttyutil.ensure_sane_tty()
    except Exception:
        pass


# Run the named _CursesUI method inside curses.wrapper, falling back to the
# matching _line_* function on failure. TUIAbort is re-raised unchanged.
def _with_curses(fn, *args, **kwargs):
    holder = {}
    import atexit
    # Idempotent: unregister first so repeated calls do not pile up handlers
    try:
        atexit.unregister(_restore_terminal)
    except Exception:
        pass
    atexit.register(_restore_terminal)

# Build a UI on stdscr, call the named method and stash its result for the caller.
    def _run(stdscr):
        ui = _CursesUI(stdscr)
        holder["ret"] = getattr(ui, fn)(*args, **kwargs)

    try:
        _curses.wrapper(_run)
    except TUIAbort:
        raise
    except Exception as e:
        # Curses init or draw failed (no TERM, terminal too small, draw error): fall back to line mode so it never crashes,
        # but print the reason, otherwise an empty screen hides the cause
        _debug(f"curses 后端失败({fn})，降级 line：{type(e).__name__}: {e}")
        return globals()[f"_line_{fn}"](*args, **kwargs)
    finally:
        # Restore even on TUIAbort: Ctrl-C mid-wizard must land back in a shell that accepts input
        _restore_terminal()
    return holder.get("ret")


# --------------------------------------------------------------------------
# Unified entry points, the only six functions callers use
# --------------------------------------------------------------------------

# Show a message and wait for the user, through whichever backend is active.
def note(title, body, i=None, n=None):
    if backend() == "curses":
        return _with_curses("note", title, body, i, n)
    return _line_note(title, body, i, n)


# Ask a yes/no question; returns a bool, and the curses backend never returns None.
def confirm(title, body, question, default=True, i=None, n=None):
    if backend() == "curses":
        r = _with_curses("confirm", title, body, question, default, i, n)
        return default if r is None else r
    return _line_confirm(title, body, question, default, i, n)


# Ask for one line of text; returns the answer or BACK.
def ask_text(title, body, question, default="", i=None, n=None):
    if backend() == "curses":
        return _with_curses("text", title, body, question, default, i, n)
    return _line_text(title, body, question, default, i, n)


# Pick one option; returns the index or BACK.
def ask_select(title, body, options, default_idx=0, i=None, n=None):
    if backend() == "curses":
        return _with_curses("select", title, body, options, default_idx, i, n)
    return _line_select(title, body, options, default_idx, i, n)


# Full-screen Recovery style menu: arrows and Enter under curses, a typed number otherwise. Esc returns BACK; EOF or an interrupt raises TUIAbort.
def ask_menu(header, options, default_idx=0):
    if backend() == "curses":
        return _with_curses("menu", header, options, default_idx)
    return _line_menu(header, options, default_idx)


# Show a progress bar for frac (0.0 to 1.0) without waiting for a key.
def progress(title, body, frac):
    if backend() == "curses":
        try:
            _with_curses("progress", title, body, frac)
            return
        except TUIAbort:
            raise
        except Exception:
            pass
    _line_progress(title, body, frac)
