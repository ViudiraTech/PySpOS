#
#   shell/shparser.py
#   shell 词法 / 语法 / 展开：引号、管道、&&/||/;、重定向、变量、命令替换、glob。
#

"""分词把一行拆成 WORD（含引号片段）和 OP；语法把 OP 串成管线与条件链；
展开把 WORD 算成最终参数。执行在 shexec.py。
"""

import glob as _glob
import os
import re

MAX_SUBST_DEPTH = 16

_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


class LexError(Exception):
    pass


class ExpandError(Exception):
    pass


def _is_name(text):
    return bool(_NAME_RE.match(text or ""))


def tokenize(line):
    """拆成 [('word', spans) | ('op', op)]。

    span 有三种：('lit', 文本, quoted)、('var', 名, quoted)、
    ('subst', 内部命令)。quoted 只区分单双引号内外，不做转义外
    的任何语义事，语义全留给 expand_word。
    """
    tokens = []
    spans = []
    buf = []
    i, n = 0, len(line)

    def flush_lit():
        if buf:
            spans.append(("lit", "".join(buf), False))
            buf.clear()

    def flush_word():
        flush_lit()
        if spans:
            tokens.append(("word", spans[:]))
            spans.clear()

    while i < n:
        c = line[i]
        if c in " \t":
            flush_word()
            i += 1
            continue
        if c == "#" and not spans and not buf:
            flush_word()
            break
        if line.startswith("||", i):
            flush_word()
            tokens.append(("op", "||"))
            i += 2
            continue
        if line.startswith("&&", i):
            flush_word()
            tokens.append(("op", "&&"))
            i += 2
            continue
        if line.startswith("2>&1", i):
            flush_word()
            tokens.append(("op", "2>&1"))
            i += 4
            continue
        if line.startswith(">>", i):
            flush_word()
            tokens.append(("op", ">>"))
            i += 2
            continue
        if c in "|;&><":
            flush_word()
            tokens.append(("op", c))
            i += 1
            continue
        if c in "()":
            flush_word()
            tokens.append(("op", c))
            i += 1
            continue
        if c == "&" and line.startswith("&1", i) and not spans and not buf \
                and (not i or line[i - 1] == ">"):
            flush_word()
            tokens.append(("op", "&1"))
            i += 2
            continue
        if c.isdigit():
            j = i
            while j < n and line[j].isdigit():
                j += 1
            if j < n and line[j] in "><" and not spans and not buf:
                flush_word()
                if line.startswith(">&", j) and j + 2 < n and line[j + 2].isdigit():
                    k = j + 2
                    while k < n and line[k].isdigit():
                        k += 1
                    tokens.append(("op", f"{int(line[i:j])}>&{int(line[j + 2:k])}"))
                    i = k
                    continue
                if line.startswith(">>", j):
                    tokens.append(("op", str(int(line[i:j])) + ">>"))
                    i = j + 2
                else:
                    tokens.append(("op", str(int(line[i:j])) + line[j]))
                    i = j + 1
                continue
        if c == "'":
            flush_lit()
            j = line.find("'", i + 1)
            if j < 0:
                raise LexError("未闭合的单引号")
            spans.append(("lit", line[i + 1:j], True))
            i = j + 1
            continue
        if c == '"':
            flush_lit()
            j = i + 1
            piece = []
            while j < n and line[j] != '"':
                if line[j] == "\\" and j + 1 < n and line[j + 1] in '$`"\\\n':
                    if line[j + 1] != "\n":
                        piece.append(line[j + 1])
                    j += 2
                    continue
                if line[j] == "$":
                    text, name, quoted_var, j = _scan_dollar(line, j, True)
                    if piece:
                        spans.append(("lit", "".join(piece), True))
                        piece = []
                    spans.append((text, name, quoted_var))
                    continue
                if line[j] == "`":
                    inner, j = _scan_backtick(line, j)
                    if piece:
                        spans.append(("lit", "".join(piece), True))
                        piece = []
                    spans.append(("subst", inner, True))
                    continue
                piece.append(line[j])
                j += 1
            if j >= n:
                raise LexError("未闭合的双引号")
            if piece:
                spans.append(("lit", "".join(piece), True))
            i = j + 1
            continue
        if c == "\\" and i + 1 < n:
            flush_lit()
            if line[i + 1] == "\n":
                i += 2
                continue
            spans.append(("lit", line[i + 1], True))
            i += 2
            continue
        if c == "$":
            flush_lit()
            kind, name, q, i = _scan_dollar(line, i, False)
            spans.append((kind, name, q))
            continue
        if c == "`":
            flush_lit()
            inner, i = _scan_backtick(line, i)
            spans.append(("subst", inner, False))
            continue
        buf.append(c)
        i += 1
    flush_word()
    return tokens


def _scan_dollar(line, i, quoted):
    """扫 $ 开头的扩展，返回 (kind, 名/内部命令, quoted, 新位置)。"""
    n = len(line)
    if line.startswith("$((", i):
        j = line.find("))", i + 3)
        if j < 0:
            raise LexError("未闭合的 $((...))")
        return "arith", line[i + 3:j], quoted, j + 2
    if line.startswith("$(", i):
        depth = 1
        j = i + 2
        in_s = in_d = False
        while j < n and depth:
            c = line[j]
            if c == "\\" and not in_s:
                j += 2
                continue
            if c == "'" and not in_d:
                in_s = not in_s
            elif c == '"' and not in_s:
                in_d = not in_d
            elif not in_s and not in_d:
                if c == "(":
                    depth += 1
                elif c == ")":
                    depth -= 1
            j += 1
        if depth:
            raise LexError("未闭合的 $(...)")
        return "subst", line[i + 2:j - 1], quoted, j
    if line.startswith("${", i):
        j = line.find("}", i + 2)
        if j < 0:
            raise LexError("未闭合的 ${...}")
        return "var", line[i + 2:j], quoted, j + 1
    if i + 1 < n and (line[i + 1].isalpha() or line[i + 1] == "_"):
        j = i + 1
        while j < n and (line[j].isalnum() or line[j] == "_"):
            j += 1
        return "var", line[i + 1:j], quoted, j
    if i + 1 < n and line[i + 1] in "?$!#":
        return "var", line[i + 1], quoted, i + 2
    return "lit", "$", quoted, i + 1


def _scan_backtick(line, i):
    j = i + 1
    n = len(line)
    piece = []
    while j < n and line[j] != "`":
        if line[j] == "\\" and j + 1 < n:
            piece.append(line[j + 1])
            j += 2
            continue
        piece.append(line[j])
        j += 1
    if j >= n:
        raise LexError("未闭合的反引号")
    return "".join(piece), j + 1


def _split_statements(tokens):
    """按 ; & && || 切语句，返回 [(tokens, cond, background)]。

    圆括号做嵌套分组：只有配平的顶层括号会被剥掉，当成一次普通命令。
    """
    out = []
    cur = []
    pending_cond = None
    depth = 0
    for kind, value in tokens:
        if kind == "op" and value == "(":
            depth += 1
            cur.append((kind, value))
            continue
        if kind == "op" and value == ")":
            depth -= 1
            if depth < 0:
                raise LexError("多余的右括号")
            cur.append((kind, value))
            continue
        if kind == "op" and depth == 0 and value in (";", "&", "&&", "||"):
            if cur or value in ("&&", "||"):
                out.append((cur, pending_cond, value == "&"))
                cur = []
            pending_cond = None if value in (";", "&") else value
            continue
        cur.append((kind, value))
    if depth:
        raise LexError("未闭合的左括号")
    if cur:
        out.append((cur, pending_cond, False))
    elif pending_cond in ("&&", "||"):
        raise LexError(f"缺少 {pending_cond} 右端命令")
    return out


def _strip_group(tokens):
    """剥掉 ( ... ) 外层括号；未配平或首尾不是括号时返回 None。"""
    if not (tokens and tokens[0] == ("op", "(")
            and tokens[-1] == ("op", ")")):
        return None
    inner = tokens[1:-1]
    if not inner:
        raise LexError("空括号")
    return inner


def _split_pipeline(tokens):
    """按 | 切管线。括号分组整体算一段，可以做管线成员。"""
    parts, cur = [], []
    i, n = 0, len(tokens)
    while i < n:
        kind, value = tokens[i]
        if kind == "op" and value == "|":
            parts.append(cur)
            cur = []
            i += 1
            continue
        if kind == "op" and value == "(":
            depth, j = 1, i + 1
            while j < n and depth:
                k2, v2 = tokens[j]
                if k2 == "op" and v2 == "(":
                    depth += 1
                elif k2 == "op" and v2 == ")":
                    depth -= 1
                j += 1
            if depth:
                raise LexError("未闭合的左括号")
            cur.append(("group", tokens[i + 1:j - 1]))
            i = j
            continue
        if kind == "op" and value == ")":
            raise LexError("多余的右括号")
        cur.append((kind, value))
        i += 1
    parts.append(cur)
    if any(not p for p in parts):
        raise LexError("管道缺了一段")
    return parts


_REDIRECTS = {">", ">>", "<", "2>", "2>&1", "&1"}
_FD_DUP_RE = re.compile(r"\A(\d+)>?&(\d+)\Z")


def _parse_command(tokens):
    argv, redirects, assign = [], [], []
    i, n = 0, len(tokens)
    while i < n:
        kind, value = tokens[i]
        if kind == "op" and (value in _REDIRECTS
                             or _FD_DUP_RE.match(value)
                             or (len(value) > 1 and value[0].isdigit()
                                 and value[-1] in "><")):
            dup = _FD_DUP_RE.match(value)
            if value == "2>&1" or value == "&1" or dup:
                if dup:
                    redirects.append((int(dup.group(1)), "dup_fd",
                                     ("fd", int(dup.group(2)))))
                else:
                    redirects.append((2, "dup", None))
                i += 1
                continue
            i += 1
            if i >= n or tokens[i][0] != "word":
                raise LexError(f"重定向 {value} 缺目标")
            target = tokens[i][1]
            if value.startswith("2"):
                redirects.append((2, value[1:], target))
            elif value[0].isdigit():
                fd = int(value[:-2] if value.endswith(">>") else value[:-1])
                mode = ">>" if value.endswith(">>") else value[-1]
                redirects.append((fd, mode, target))
            elif value == ">":
                redirects.append((1, ">", target))
            elif value == ">>":
                redirects.append((1, ">>", target))
            else:
                redirects.append((0, "<", target))
            i += 1
            continue
        if kind == "op":
            raise LexError(f"此处不需要 {value}")
        if not argv and not redirects and value and value[0][0] == "lit" \
                and not value[0][2] and "=" in value[0][1]:
            name, _, head = value[0][1].partition("=")
            if _is_name(name):
                rest = ([("lit", head, False)] if head else []) + value[1:]
                assign.append((name, rest))
                i += 1
                continue
        argv.append(value)
        i += 1
    return {"argv": argv, "redirects": redirects, "assign": assign}


def _build_cmd(part, parse_inner):
    """把一段 token 变成 cmd；遇到括号分组就递归解析成子程序。"""
    groups = [tok for tok in part if tok[0] == "group"]
    if groups:
        if len(groups) > 1 or groups[0] is not part[0]:
            raise LexError("括号分组后面只能跟重定向")
        rest = part[1:]
        trailing = _parse_command(rest)
        inner_tokens = groups[0][1]
        if not inner_tokens:
            raise LexError("空括号")
        return {"argv": [], "redirects": trailing["redirects"],
                "assign": trailing["assign"],
                "program": parse_inner(inner_tokens)}
    return _parse_command(part)


def parse(line):
    """line -> [({"cmds": [...], "background": bool}, cond)]。"""
    return _parse_tokens(tokenize(line))


def _parse_tokens(tokens, depth=0):
    if depth > 16:
        raise LexError("括号嵌套太深")
    program = []
    for stmt_tokens, cond, background in _split_statements(tokens):
        cmds = [_build_cmd(part, lambda inner, d=depth: _parse_tokens(inner, d + 1))
                for part in _split_pipeline(stmt_tokens)]
        program.append(({"cmds": cmds, "background": background}, cond))
    return program


def _lookup_raw(name, ctx):
    """未设返回 None，已设但为空返回 ""。${V-d} / ${V:-d} 就靠这个区分。"""
    if name == "?":
        return str(ctx.get("last", 0))
    if name == "$":
        return str(os.getpid())
    if name == "!":
        try:
            import process as _proc
            pid = _proc.last_bg_pid()
            return None if pid is None else str(pid)
        except Exception:
            return None
    if name == "#":
        return "0"
    if name in ctx.get("vars", {}):
        return ctx["vars"][name]
    return os.environ.get(name)


def _lookup_var(name, ctx):
    value = _lookup_raw(name, ctx)
    return "" if value is None else value


def _expand_var_spec(spec, ctx):
    """${V} / ${V:-d} / ${V:=d} / ${V:?msg} / ${V:+alt}。

    没写运算符就是 ${V}；:- 类在未设或为空时取默认值，- 类只看未设。
    """
    match = _VAR_MOD_RE.match(spec)
    if not match:
        name = spec
        if not _is_name(name) and name not in ("?", "$", "!", "#"):
            raise ExpandError(f"非法变量名: {name}")
        return _lookup_var(name, ctx)
    name, op, arg = match.group(1), match.group(2), match.group(3)
    if not _is_name(name) and name not in ("?", "$", "!", "#"):
        raise ExpandError(f"非法变量名: {name}")
    raw = _lookup_raw(name, ctx)
    value = "" if raw is None else raw
    if op is None:
        return value
    unset = raw is None
    empty = raw == ""
    if op in (":-", "-"):
        if not unset and not (op == ":-" and empty):
            return value
        return _eval_operand(arg, ctx) if op == ":-" else arg
    if op in (":=", "="):
        if not unset and not (op == ":=" and empty):
            return value
        new = _eval_operand(arg, ctx) if op == ":=" else arg
        ctx["vars"][name] = new
        return new
    if op in (":+", "+"):
        if unset or (op == ":+" and empty):
            return ""
        return _eval_operand(arg, ctx) if op == ":+" else arg
    raise ExpandError(f"{name}: {arg or '缺少参数'}")


_VAR_MOD_RE = re.compile(r"\A([A-Za-z_][A-Za-z0-9_]*)"
                         r"(?:(:-|-|:\+|\+|:=|=|\?|:\?)(.*))?\Z", re.S)


def _eval_operand(text, ctx):
    """默认值/备选值里的 $VAR 仍要展开。"""
    if not text:
        return ""
    toks = tokenize(text)
    out = []
    for kind, spans in toks:
        if kind != "word":
            continue
        out.extend(expand_word(spans, ctx))
    return " ".join(out)


class _Arith:
    """$(( )) 的整数表达式求值。

    手写递归下降而不是 eval：算术展开里出现函数名/属性/下标就意味着
    有人想从 shell 逃到 Python，沙子箱里不做这事。
    """

    def __init__(self, text, ctx):
        self.text = text
        self.ctx = ctx
        self.pos = 0

    def _peek(self):
        return self.text[self.pos] if self.pos < len(self.text) else ""

    def _skip(self):
        while self._peek().isspace():
            self.pos += 1

    def _eat(self, ch):
        self._skip()
        if self._peek() == ch:
            self.pos += 1
            return True
        return False

    def value(self):
        result = self.expr()
        self._skip()
        if self.pos != len(self.text):
            raise ExpandError(f"算术表达式有多余内容: {self.text[self.pos:]}")
        return str(result)

    def expr(self):
        left = self.term()
        while True:
            self._skip()
            ch = self._peek()
            if ch == "+":
                self.pos += 1
                left += self.term()
            elif ch == "-":
                self.pos += 1
                left -= self.term()
            else:
                return left

    def term(self):
        left = self.power()
        while True:
            self._skip()
            ch = self._peek()
            if ch == "*":
                self.pos += 1
                left *= self.power()
            elif ch == "/":
                self.pos += 1
                divisor = self.power()
                if divisor == 0:
                    raise ExpandError("算术表达式除以零")
                left = int(left / divisor)
            elif ch == "%":
                self.pos += 1
                divisor = self.power()
                if divisor == 0:
                    raise ExpandError("算术表达式模零")
                left = left - divisor * int(left / divisor)
            else:
                return left

    def power(self):
        base = self.unary()
        self._skip()
        if self._peek() == "*" and self.text[self.pos:self.pos + 2] == "**":
            self.pos += 2
            return base ** self.power()
        return base

    def unary(self):
        self._skip()
        if self._eat("-"):
            return -self.power()
        if self._eat("+"):
            return self.power()
        return self.atom()

    def atom(self):
        self._skip()
        if self._eat("("):
            inner = self.expr()
            self._skip()
            if not self._eat(")"):
                raise ExpandError("算术表达式缺右括号")
            return inner
        if self._peek() == "$":
            self.pos += 1
            kind, name, _quoted, self.pos = _scan_dollar(
                self.text, self.pos, True)
            if kind == "var":
                return _as_int(_lookup_var(name, self.ctx), self.text)
            raise ExpandError("算术表达式里不支持命令替换")
        start = self.pos
        while self._peek().isdigit():
            self.pos += 1
        if start != self.pos:
            return int(self.text[start:self.pos])
        if self._peek().isalpha() or self._peek() == "_":
            j = self.pos
            while j < len(self.text) and (self.text[j].isalnum()
                                          or self.text[j] == "_"):
                j += 1
            name = self.text[self.pos:j]
            self.pos = j
            if not _is_name(name):
                raise ExpandError(f"非法变量名: {name}")
            return _as_int(_lookup_var(name, self.ctx), self.text)
        raise ExpandError(f"算术表达式无法解析: {self.text[start:]}")


def _as_int(value, context=""):
    try:
        return int(str(value).strip() or "0")
    except ValueError:
        raise ExpandError(f"算术表达式需要整数: {value!r}") from None


def _has_magic(text):
    return any(m in text for m in "*?[")


def _append_text(fields, flags, text, split, magic):
    if split:
        parts = text.split()
        if not parts:
            return
        fields[-1] += parts[0]
        flags[-1] = flags[-1] or (magic and _has_magic(parts[0]))
        for part in parts[1:]:
            fields.append(part)
            flags.append(bool(magic and _has_magic(part)))
    else:
        fields[-1] += text
        flags[-1] = flags[-1] or (magic and _has_magic(text))


def expand_word(spans, ctx):
    """WORD spans -> 最终参数串列表（含分词、glob、~）。"""
    run_capture = ctx.get("run_capture")
    depth = ctx.get("depth", 0)
    fields, flags, touched = [""], [False], [False]
    tilde = bool(spans) and spans[0][0] == "lit" and not spans[0][2] \
        and spans[0][1].startswith("~")
    for span in spans:
        kind = span[0]
        if kind == "lit":
            text, quoted = span[1], span[2]
            touched[0] = touched[0] or bool(text) or quoted
            _append_text(fields, flags, text, split=not quoted,
                         magic=not quoted)
        elif kind == "var":
            name, quoted = span[1], span[2]
            value = _expand_var_spec(name, ctx)
            touched[0] = touched[0] or bool(value) or quoted
            _append_text(fields, flags, value, split=not quoted,
                         magic=not quoted)
        elif kind == "arith":
            expr_text, quoted = span[1], span[2]
            value = _Arith(expr_text, ctx).value()
            touched[0] = touched[0] or bool(value) or quoted
            _append_text(fields, flags, value, split=not quoted,
                         magic=not quoted)
        else:
            inner, quoted = span[1], span[2]
            if run_capture is None:
                raise ExpandError("$() 需要执行器")
            if depth >= MAX_SUBST_DEPTH:
                raise ExpandError("$() 嵌套太深")
            try:
                value = run_capture(inner, depth + 1).rstrip("\n")
            except Exception as exc:
                raise ExpandError(f"$() 执行失败: {exc}")
            touched[0] = touched[0] or bool(value) or quoted
            _append_text(fields, flags, value, split=not quoted,
                         magic=not quoted)
    if not touched[0]:
        return []
    out = []
    for index, field in enumerate(fields):
        if index == 0 and tilde and field.startswith("~"):
            field = os.path.expanduser(field)
        if flags[index] and _has_magic(field):
            try:
                matches = sorted(_glob.glob(field))
            except Exception:
                matches = []
            out.extend(matches if matches else [field])
        else:
            out.append(field)
    return out
