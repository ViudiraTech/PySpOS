#
#   tui.py
#   Debian-Installer 风格的文本向导框体。双后端同签名：
#     curses 后端（POSIX + tty）：居中对话框，方向键/Tab/回车/Esc，列表可滚动；
#     line 后端（Windows / 无 tty / 强制）：d-i text 前端语义——输编号+回车、
#       回车=默认、< =返回、! =留空。
#   后端选择：curses 可用且双端 tty 且 PYSPOS_TUI 未强制 line → curses，否则 line。
#   非交互 EOF 抛 TUIAbort，调用方按“中止”处理（OOBE 不写标记）。
#

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

# 布局常量（对齐 whiptail/dialog 的成熟做法）
PAD = 2            # 正文与边框之间的留白（whiptail 76/80 即两侧各留 2）
MIN_W = 34         # 框体最小宽度（含边框）
MIN_BODY_W = 24    # 正文最小可用宽度
MIN_H = 7          # 框体最小高度
BORDER_H = 2       # 上下边框
BORDER_V = 2       # 左右边框
BUTTON_ROWS = 2    # 按钮行 + 其上留白


def dwidth(s: str) -> int:
    """显示宽度：CJK/全角算 2 列，组合字符算 0 列。

    这是中文 TUI 可读性的关键——whiptail 用的就是 _newt_wstrlen（宽字符
    长度）而不是 strlen。用 len() 量中文会得到真实宽度的一半，框体随之
    缩一半，正文必然溢出错行。
    """
    w = 0
    for ch in str(s):
        if _combining(ch):
            continue
        w += 2 if _wide(ch) else 1
    return w


def _wide(ch: str) -> bool:
    import unicodedata
    return unicodedata.east_asian_width(ch) in ("W", "F")


def _combining(ch: str) -> bool:
    import unicodedata
    return unicodedata.combining(ch) != 0


# 允许的控制字符：仅换行。其它 C0/C1 一律净化。
_ALLOWED_CTRL = {"\n"}

# 完整 ANSI/VT 转义序列：ESC [ ... final、ESC ] ... BEL/ST、ESC 单字符
_ANSI_RE = re.compile(
    r"\x1b\[[0-?]*[ -/]*[@-~]"       # CSI（颜色/光标）
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"  # OSC（含标题设置）
    r"|\x1b[@-Z\\-_]"                 # 其它单字符转义
)


def sanitize(text) -> str:
    """净化控制字符，防止破坏 TUI 布局。

    典型来源：文件里的 CRLF（Windows 编辑的 JSON/脚本）、管道进来的
    带 \r 文本、日志行尾残留。curses 的 addstr 遇到 \r 会把光标移回行首、
    遇到 \t 会跳到不规则列，表现为终端里出现 `^M` 或整段错位。
    这里统一：先整段剥离 ANSI 转义序列（否则会残留可见的 `[31m`），
    再把 \r\n 与孤立 \r 规整为 \n、\t 转空格、其余 C0/C1 丢弃。
    """
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
            # 其它 C0/C1 直接丢弃
            continue
        if o in (0x200B, 0x200C, 0x200D, 0xFEFF):
            continue
        out.append(ch)
    return "".join(out)


def dtrunc(s: str, limit: int) -> str:
    """按显示宽度截断（超出加省略号）。"""
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


def dpad(s: str, width: int) -> str:
    """右侧补空格到指定显示宽度。"""
    return str(s) + " " * max(0, width - dwidth(s))


def dwrap(text: str, width: int) -> list:
    """按显示宽度折行；中英混排时不切碎宽字符，英文整词不拆。"""
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
                # 行尾空格不计入宽度（避免无谓提前折行）
                if line:
                    pending_space = True
                continue
            need = tw + (1 if pending_space else 0)
            if w + need > width and line:
                if tw > width:                     # 超长单词硬切
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


def _tokens(text):
    """切分为词元：连续 ASCII 单词/空格为一元，CJK 逐字一元。"""
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


class TUIAbort(Exception):
    pass


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


def _step_prefix(i, n):
    if i is None or n is None:
        return ""
    return _("oobe.step", i=i, n=n) + " "


# --------------------------------------------------------------------------
# line 后端
# --------------------------------------------------------------------------

def _line_input(prompt):
    try:
        return input(prompt)
    except EOFError:
        raise TUIAbort("EOF")
    except KeyboardInterrupt:
        raise TUIAbort("interrupt")


def _line_note(title, body, i=None, n=None):
    print(f"\n==== {_step_prefix(i, n)}{sanitize(title)} ====\n"
          f"{sanitize(body)}\n")
    s = _line_input(f"[{_('tui.cont')}/{_('tui.back')}] {_('tui.press_enter')}").strip()
    if s == "<":
        return BACK
    return None


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


def _line_progress(title, body, frac):
    bar = int(frac * 30)
    print(f"\n==== {sanitize(title)} ====\n{sanitize(body)}\n"
          f"[{'#' * bar}{'-' * (30 - bar)}] {int(frac * 100)}%")


# --------------------------------------------------------------------------
# curses 后端
# --------------------------------------------------------------------------

class _CursesUI:
    """单窗口渲染器。

    刻意不使用 newwin 子窗口：curses 的 wgetch 在窗口被修改后会自动
    wrefresh 自身，而读键发生在另一个窗口上时会把子窗口内容覆盖掉
    （ncurses 已知陷阱，dialog/newt 等成熟实现一律单窗口绘制+读键）。
    全部绘制到 stdscr，再统一 refresh，读键也用 stdscr.getch()，无冲突。
    """

    def __init__(self, stdscr):
        self.s = stdscr
        try:
            _curses.curs_set(0)
        except Exception:
            pass
        self.s.keypad(True)
        self.h, self.w = self.s.getmaxyx()
        self._init_colors()

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
                (1, _curses.COLOR_CYAN),    # 框
                (2, _curses.COLOR_BLACK),   # 标题底
                (3, _curses.COLOR_WHITE),   # 正文
                (4, _curses.COLOR_BLUE),    # 页脚
                (5, _curses.COLOR_BLACK),   # 选中项（黄底）
                (6, _curses.COLOR_GREEN),   # 提示
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

    def _put(self, y, x, text, attr=0):
        """安全写字符：越界/触底自动截断，并净化控制字符。

        这里是控制字符的最后一道防线——即使上层漏了 sanitize，
        \r / \t / ANSI 转义也不会破坏框体布局。
        """
        if not (0 <= y < self.h and 0 <= x < self.w):
            return
        text = sanitize(text).replace("\n", " ")
        maxlen = self.w - x - 1          # 留出最后一格，避免 addstr 触底报错
        if maxlen <= 0:
            return
        # 按显示宽度截断（不能直接切 len，否则宽字符会被切半）
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

    def _frame(self, title, body, footer="", sel=None, buttons=None,
               min_content=0):
        """按显示宽度测量后居中绘制。body 为已折行的列表。"""
        h, w = self.h, self.w
        self.s.erase()

        title = sanitize(title)
        body = [sanitize(l) for l in (body or [""])]
        footer = sanitize(footer) if footer else ""
        buttons = [sanitize(b) for b in buttons] if buttons else None
        # 宽度：取标题/正文/页脚/按钮里最宽者 + 边框 + 两侧留白
        need = max([dwidth(title)] + [dwidth(str(l)) for l in body]
                   + [dwidth(footer or "")] + [dwidth(b) for b in (buttons or [])]
                   + [min_content])
        bw = min(max(need + BORDER_V + PAD * 2, MIN_W), w - 2)

        # 高度：正文 + 边框 + 按钮/页脚
        extra = BUTTON_ROWS if buttons else (1 if footer else 0)
        bh = min(len(body) + BORDER_H + extra, h - 1)
        max_body = max(1, bh - BORDER_H - extra)
        if len(body) > max_body:
            body = body[:max_body]

        y0 = max(0, (h - bh) // 2)
        x0 = max(0, (w - bw) // 2)
        lx = x0 + 1 + PAD          # 正文左边界
        rx = x0 + bw - 1 - PAD    # 正文右边界
        span = max(1, rx - lx + 1)

        hline = getattr(_curses, "ACS_HLINE", "-")
        vline = getattr(_curses, "ACS_VLINE", "|")
        if not isinstance(hline, str):
            hline = chr(hline & 0xFF)
        if not isinstance(vline, str):
            vline = chr(vline & 0xFF)

        # 上下边框画横线；中间行只画左右竖线，中间留空给正文。
        # （早先版本给每行都铺横线再覆盖两列，导致内容行出现 `|--内容-|`。）
        self._put(y0, x0, hline * bw, self.C_FRAME)
        self._put(y0 + bh - 1, x0, hline * bw, self.C_FRAME)
        for y in range(y0 + 1, y0 + bh - 1):
            self._put(y, x0, vline, self.C_FRAME)
            self._put(y, x0 + bw - 1, vline, self.C_FRAME)

        # 标题写在边框上（whiptail newtOpenWindow 的做法），而非占用正文行
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

    def _compose(self, body, question=None):
        """成熟对话框结构（linuxboot UX 规范）：

            <短说明>
            <空行>
            <上下文段落>
            <空行>
            <问题/提示>     ← 永远在最后，紧贴按钮

        中间空行把「说明」与「要回答的问题」在视觉上分开，可读性关键。
        连续空行合并为一行（早期版本每个元素前都插空行，1 个空行变成 3 个）。
        所有文本先过 sanitize，CRLF/控制符不会带进布局。
        """
        merged = []
        for p in sanitize(body).split("\n"):
            if not p.strip():
                if merged and merged[-1] != "":
                    merged.append("")
                continue
            merged.append(p)
        while merged and merged[-1] == "":
            merged.pop()
        lines = list(merged)          # merged 已是「段 + 空行」结构，直接用
        if question:
            if lines:
                lines.append("")
            lines.append(sanitize(question))
        return lines

    def _layout(self, body, question=None):
        """先按内容自然宽度定框，再在该宽度内折行。

        早期版本先按最大宽度(76)折行再定框，导致内容只占半框、右侧大片
        空白，可读性很差。成熟做法是「内容定宽 → 框内折行」。
        """
        raw = self._compose(body, question)
        # 自然宽度：最长未折行段落，但不超过舒适阅读上限
        cap = max(MIN_BODY_W, min(self.w - 2, 76) - BORDER_V - PAD * 2)
        natural = max((dwidth(p) for p in raw if p), default=0)
        width = max(MIN_BODY_W, min(natural, cap))
        lines = []
        for p in raw:
            lines.extend(dwrap(p, width) if p else [""])
        return lines, width

    def note(self, title, body, i=None, n=None):
        title = _titled(title, i, n)
        # 注意：不要用 `lines, _ = ...` 接收宽度——`_` 是模块级的翻译函数，
        # 局部遮蔽后 `_("tui.cont")` 会变成 "int object is not callable"。
        lines = self._layout(body)[0]
        while True:
            self._frame(title, lines, buttons=[_("tui.cont")])
            c = self.s.getch()
            if c == 27:
                return BACK
            if c in (10, 13, _curses.KEY_ENTER):
                return None

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

    def progress(self, title, body, frac):
        lines, width = self._layout(body)
        filled = int(width * max(0.0, min(1.0, frac)))
        bar = "█" * filled + "░" * (width - filled)
        lines += ["", f"[{bar}] {int(frac * 100):3d}%"]
        self._frame(title, lines, footer="")
        _curses.napms(250)



def _titled(title, i, n):
    if i is None or n is None:
        return title
    from syslocale import _ as _t
    return f"{_t('oobe.step', i=i, n=n)} {title}"


def _debug(msg):
    """降级原因必须可见——之前静默 fallback 把 curses 崩溃藏了两次。"""
    if os.environ.get("PYSPOS_TUI_DEBUG"):
        import sys as _s
        _s.stderr.write(f"[tui] {msg}\n")
        _s.stderr.flush()


def _restore_terminal():
    """curses 会话后的终端兜底恢复。

    `curses.wrapper` 正常路径会 endwin，但以下情况会跳过它：
      - 子进程走 `os._exit()`（forkexec 的 _child_main 就是）——共享同一个
        tty，子进程退出时 tty 仍留在 cbreak 模式；
      - SIGKILL / 段错误；
      - 异常在 wrapper 之外逃逸。
    结果是 tty 的 icrnl 被关掉：回车发出的 \\r 不再翻译成 \\n，终端把它
    当普通字符回显成 `^M`，之后所有 input() 读到非空垃圾 → 无限重试。
    这就是「按 enter 疯狂出 ^M」的成因。atexit + finally 双保险清掉它。
    """
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


def _with_curses(fn, *args, **kwargs):
    holder = {}
    import atexit
    # 幂等：多次注册靠 atexit 的取消机制避免堆积
    try:
        atexit.unregister(_restore_terminal)
    except Exception:
        pass
    atexit.register(_restore_terminal)

    def _run(stdscr):
        ui = _CursesUI(stdscr)
        holder["ret"] = getattr(ui, fn)(*args, **kwargs)

    try:
        _curses.wrapper(_run)
    except TUIAbort:
        raise
    except Exception as e:
        # curses 初始化/渲染失败（无 TERM、终端过小、绘制异常…）→ 降级行式，
        # 保证永不崩；但把原因打出来，避免「界面全空」这种问题被掩盖。
        _debug(f"curses 后端失败({fn})，降级 line：{type(e).__name__}: {e}")
        return globals()[f"_line_{fn}"](*args, **kwargs)
    finally:
        # TUIAbort 也必须恢复：向导中途 Ctrl-C 后要回到可正常输入的 shell
        _restore_terminal()
    return holder.get("ret")


# --------------------------------------------------------------------------
# 统一入口（调用方只用这五个）
# --------------------------------------------------------------------------

def note(title, body, i=None, n=None):
    if backend() == "curses":
        return _with_curses("note", title, body, i, n)
    return _line_note(title, body, i, n)


def confirm(title, body, question, default=True, i=None, n=None):
    if backend() == "curses":
        r = _with_curses("confirm", title, body, question, default, i, n)
        return default if r is None else r
    return _line_confirm(title, body, question, default, i, n)


def ask_text(title, body, question, default="", i=None, n=None):
    if backend() == "curses":
        return _with_curses("text", title, body, question, default, i, n)
    return _line_text(title, body, question, default, i, n)


def ask_select(title, body, options, default_idx=0, i=None, n=None):
    if backend() == "curses":
        return _with_curses("select", title, body, options, default_idx, i, n)
    return _line_select(title, body, options, default_idx, i, n)


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
