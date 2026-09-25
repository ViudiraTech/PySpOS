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
        if c.isdigit():
            j = i
            while j < n and line[j].isdigit():
                j += 1
            if j < n and line[j] in "><" and not spans and not buf:
                flush_word()
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
    """按 ; & && || 切语句，返回 [(tokens, cond, background)]。"""
    out = []
    cur = []
    pending_cond = None
    for kind, value in tokens:
        if kind == "op" and value in (";", "&", "&&", "||"):
            if cur or value in ("&&", "||"):
                out.append((cur, pending_cond, value == "&"))
                cur = []
            pending_cond = None if value in (";", "&") else value
            continue
        cur.append((kind, value))
    if cur:
        out.append((cur, pending_cond, False))
    elif pending_cond in ("&&", "||"):
        raise LexError(f"缺少 {pending_cond} 右端命令")
    return out


def _split_pipeline(tokens):
    parts, cur = [], []
    for kind, value in tokens:
        if kind == "op" and value == "|":
            parts.append(cur)
            cur = []
            continue
        cur.append((kind, value))
    parts.append(cur)
    if any(not p for p in parts):
        raise LexError("管道缺了一段")
    return parts


_REDIRECTS = {">", ">>", "<", "2>", "2>&1"}


def _parse_command(tokens):
    argv, redirects, assign = [], [], []
    i, n = 0, len(tokens)
    while i < n:
        kind, value = tokens[i]
        if kind == "op" and (value in _REDIRECTS or
                             (len(value) > 1 and value[0].isdigit()
                              and value[-1] in "><")):
            if value == "2>&1":
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


def parse(line):
    """line -> [({"cmds": [...], "background": bool}, cond)]。"""
    program = []
    for stmt_tokens, cond, background in _split_statements(tokenize(line)):
        cmds = [_parse_command(part)
                for part in _split_pipeline(stmt_tokens)]
        program.append(({"cmds": cmds, "background": background}, cond))
    return program


def _lookup_var(name, ctx):
    if name == "?":
        return str(ctx.get("last", 0))
    if name == "$":
        return str(os.getpid())
    if name == "!":
        try:
            import process as _proc
            pid = _proc.last_bg_pid()
            return "" if pid is None else str(pid)
        except Exception:
            return ""
    if name == "#":
        return "0"
    value = ctx.get("vars", {}).get(name)
    if value is None:
        value = os.environ.get(name, "")
    return value


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
            if not _is_name(name) and name not in ("?", "$", "!", "#"):
                raise ExpandError(f"非法变量名: {name}")
            value = _lookup_var(name, ctx)
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
