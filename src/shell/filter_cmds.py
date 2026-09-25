#
#   shell/filter_cmds.py
#   文本过滤器：一行一个命令，无文件参数时读 stdin（管线即插即用）。
#

"""wc/head/tail/sort/uniq/tr/cut/rev/seq/tee/tac/nl/sed/date/test/true/false。
约定和 grep/cat 一致：给文件读文件，不给读 stdin；stdin 是 tty 且没给
文件就报用法（免得交互式下傻等输入）。返回 int 即退出码，专供 &&/||。
"""

import os
import re
import sys

import fs
import printk


def _split_args(args):
    import shlex
    try:
        return shlex.split(args) if args else []
    except ValueError:
        return args.split() if args else []


def _read_inputs(tokens, usage):
    """(文本列表, 错误串|None)。文件读不到记错误继续（bash 风）。"""
    if tokens:
        texts = []
        for name in tokens:
            text = fs.cat_file(name)
            if text is None:
                printk.error(f"未找到文件: {name}\n")
                continue
            texts.append(text)
        return texts, None
    if not sys.stdin.isatty():
        return [sys.stdin.read()], None
    return None, f"用法: {usage}\n"


def _one_input(tokens, usage):
    texts, err = _read_inputs(tokens, usage)
    if err:
        return None, err
    return "".join(texts), None


def cmd_true(args=""):
    return 0


def cmd_false(args=""):
    return 1


def cmd_wc(args=""):
    tokens = _split_args(args)
    flags = {t for t in tokens if t.startswith("-") and len(t) > 1}
    files = [t for t in tokens if not (t.startswith("-") and len(t) > 1)]
    if files:
        rows = []
        for name in files:
            text = fs.cat_file(name)
            if text is None:
                printk.error(f"未找到文件: {name}\n")
                continue
            rows.append((name, text))
        if not rows:
            return 1
    elif not sys.stdin.isatty():
        rows = [("", sys.stdin.read())]
    else:
        printk.error("用法: wc [-lwc] [文件...]\n")
        return 1

    def cols_of(text):
        cols = []
        if not flags or "-l" in flags:
            cols.append(str(text.count("\n")))
        if not flags or "-w" in flags:
            cols.append(str(len(text.split())))
        if not flags or "-c" in flags:
            cols.append(str(len(text)))
        return cols

    for name, text in rows:
        print(" ".join(cols_of(text)) + (f" {name}" if name else ""))
    if len(rows) > 1:
        total = "".join(text for _, text in rows)
        print(" ".join(cols_of(total)) + " 总计")
    return 0


def _parse_n(tokens, default):
    count, rest, err, plus = default, [], None, False
    skip = False
    for index, token in enumerate(tokens):
        if skip:
            skip = False
            continue
        if token == "-n" and index + 1 < len(tokens):
            raw = tokens[index + 1]
            try:
                count = int(raw)
            except ValueError:
                return None, rest, f"非法行数: {raw}", False
            plus = raw.startswith("+")
            skip = True
            continue
        if re.fullmatch(r"-\d+", token):
            count = int(token[1:])
            continue
        if re.fullmatch(r"\+\d+", token):
            count, plus = int(token), True
            continue
        rest.append(token)
    return count, rest, err, plus


def cmd_head(args=""):
    tokens = _split_args(args)
    count, files, err, _ = _parse_n(tokens, 10)
    if err:
        printk.error(err + "\n")
        return 1
    text, err = _one_input(files, "head [-n 行数] [文件]")
    if err:
        printk.error(err)
        return 1
    lines = text.splitlines()
    print("\n".join(lines[:count]))
    if lines[:count]:
        print()
    return 0


def cmd_tail(args=""):
    tokens = _split_args(args)
    count, files, err, plus = _parse_n(tokens, 10)
    if err:
        printk.error(err + "\n")
        return 1
    text, err = _one_input(files, "tail [-n 行数] [文件]")
    if err:
        printk.error(err)
        return 1
    lines = text.splitlines()
    if plus:
        picked = lines[max(count - 1, 0):]
    elif count >= 0:
        picked = lines[-count:] if count else []
    else:
        picked = lines[-count:]
    print("\n".join(picked))
    if picked:
        print()
    return 0


def cmd_sort(args=""):
    tokens = _split_args(args)
    flags = {t for t in tokens if t.startswith("-")}
    files = [t for t in tokens if not t.startswith("-")]
    text, err = _one_input(files, "sort [-r] [-n] [-u] [文件]")
    if err:
        printk.error(err)
        return 1
    lines = text.splitlines()
    if "-n" in flags:
        def key(line):
            match = re.match(r"\s*(-?\d+)", line)
            return (1, int(match.group(1)), "") if match else (0, 0, line)
        lines.sort(key=key)
    else:
        lines.sort()
    if "-r" in flags:
        lines.reverse()
    if "-u" in flags:
        seen, deduped = set(), []
        for line in lines:
            if line not in seen:
                seen.add(line)
                deduped.append(line)
        lines = deduped
    for line in lines:
        print(line)
    if lines:
        print()
    return 0


def cmd_uniq(args=""):
    tokens = _split_args(args)
    flags = {t for t in tokens if t.startswith("-")}
    files = [t for t in tokens if not t.startswith("-")]
    text, err = _one_input(files, "uniq [-c] [文件]")
    if err:
        printk.error(err)
        return 1
    out = []
    prev = None
    count = 0
    for line in text.splitlines() + [None]:
        if line == prev:
            count += 1
            continue
        if prev is not None:
            out.append(f"{count:>7} {prev}" if "-c" in flags else prev)
        prev, count = line, 1
    for line in out:
        print(line)
    if out:
        print()
    return 0


def _expand_tr_set(spec):
    out = []
    i = 0
    while i < len(spec):
        if spec[i] == "\\" and i + 1 < len(spec):
            esc = {"n": "\n", "t": "\t", "r": "\r"}.get(spec[i + 1],
                                                         spec[i + 1])
            out.append(esc)
            i += 2
            continue
        if i + 2 < len(spec) and spec[i + 1] == "-":
            for code in range(ord(spec[i]), ord(spec[i + 2]) + 1):
                out.append(chr(code))
            i += 3
            continue
        out.append(spec[i])
        i += 1
    return out


def cmd_tr(args=""):
    tokens = _split_args(args)
    delete = "-d" in tokens
    sets = [t for t in tokens if t != "-d"]
    if (len(sets) < 1) or (not delete and len(sets) < 2):
        printk.error("用法: tr [-d] 字符集1 [字符集2]\n")
        return 1
    if not sys.stdin.isatty():
        text = sys.stdin.read()
    else:
        printk.error("用法: tr [-d] 字符集1 [字符集2]\n")
        return 1
    src = _expand_tr_set(sets[0])
    if delete:
        drop = set(src)
        print("".join(c for c in text if c not in drop), end="")
        return 0
    dst = _expand_tr_set(sets[1])
    table = {}
    for index, ch in enumerate(src):
        table[ch] = dst[min(index, len(dst) - 1)]
    print("".join(table.get(c, c) for c in text), end="")
    return 0


def _parse_cut_list(spec, total):
    picked = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            left, _, right = part.partition("-")
            lo = int(left) if left else 1
            hi = int(right) if right else total
            picked.update(range(lo, hi + 1))
        else:
            picked.add(int(part))
    return picked


def cmd_cut(args=""):
    tokens = _split_args(args)
    delim, fields, files = "\t", None, []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token == "-d" and i + 1 < len(tokens):
            delim = tokens[i + 1]
            i += 2
            continue
        if token.startswith("-d") and len(token) > 2:
            delim = token[2:]
            i += 1
            continue
        if token == "-f" and i + 1 < len(tokens):
            fields = tokens[i + 1]
            i += 2
            continue
        if token.startswith("-f") and len(token) > 2:
            fields = token[2:]
            i += 1
            continue
        files.append(token)
        i += 1
    if fields is None:
        printk.error("用法: cut -d 分隔符 -f 字段 [文件]\n")
        return 1
    text, err = _one_input(files, "cut -d 分隔符 -f 字段 [文件]")
    if err:
        printk.error(err)
        return 1
    out = []
    for line in text.splitlines():
        cols = line.split(delim)
        try:
            picked = _parse_cut_list(fields, len(cols))
        except ValueError:
            printk.error(f"非法字段表: {fields}\n")
            return 1
        out.append(delim.join(
            cols[k - 1] for k in sorted(picked) if 1 <= k <= len(cols)))
    print("\n".join(out))
    if out:
        print()
    return 0


def cmd_rev(args=""):
    tokens = _split_args(args)
    text, err = _one_input(tokens, "rev [文件]")
    if err:
        printk.error(err)
        return 1
    lines = [line[::-1] for line in text.splitlines()]
    print("\n".join(lines))
    if lines:
        print()
    return 0


def cmd_tac(args=""):
    tokens = _split_args(args)
    text, err = _one_input(tokens, "tac [文件]")
    if err:
        printk.error(err)
        return 1
    lines = text.splitlines()[::-1]
    print("\n".join(lines))
    if lines:
        print()
    return 0


def cmd_nl(args=""):
    tokens = _split_args(args)
    files = [t for t in tokens if t != "-ba"]
    text, err = _one_input(files, "nl [文件]")
    if err:
        printk.error(err)
        return 1
    number_all = "-ba" in tokens
    num = 0
    for line in text.splitlines():
        if line or number_all:
            num += 1
            print(f"{num:>6}\t{line}")
        else:
            print()
    if text.splitlines():
        print()
    return 0


def cmd_seq(args=""):
    tokens = _split_args(args)
    try:
        nums = [float(t) for t in tokens]
    except ValueError:
        printk.error("用法: seq 起点 [步长] 终点\n")
        return 1
    if len(nums) == 1:
        first, step, last = 1.0, 1.0, nums[0]
    elif len(nums) == 2:
        first, step, last = nums[0], 1.0, nums[1]
    elif len(nums) == 3:
        first, step, last = nums
    else:
        printk.error("用法: seq 起点 [步长] 终点\n")
        return 1
    if step == 0:
        printk.error("seq: 步长不能为 0\n")
        return 1
    integral = all(float(v).is_integer() for v in (first, step, last))
    value = first
    count = 0
    while (step > 0 and value <= last + 1e-12) or \
            (step < 0 and value >= last - 1e-12):
        print(int(value) if integral else value)
        value += step
        count += 1
        if count > 1000000:
            printk.error("seq: 输出过多，已截断\n")
            return 1
    if count:
        print()
    return 0


def cmd_tee(args=""):
    tokens = _split_args(args)
    append = "-a" in tokens
    files = [t for t in tokens if t != "-a"]
    if not files:
        printk.error("用法: tee [-a] 文件...\n")
        return 1
    from shell.util import is_safe_filename
    for name in files:
        if not is_safe_filename(name):
            printk.error("错误：文件名不允许包含 ../ 或绝对路径\n")
            return 1
    if not sys.stdin.isatty():
        text = sys.stdin.read()
    else:
        printk.error("用法: tee [-a] 文件...（需要管道输入）\n")
        return 1
    mode = "a" if append else "w"
    for name in files:
        try:
            with open(name, mode, encoding="utf-8") as f:
                f.write(text)
        except OSError as exc:
            printk.error(f"tee: {name}: {exc}\n")
            return 1
    print(text, end="")
    return 0


def cmd_sed(args=""):
    tokens = _split_args(args)
    if not tokens or not tokens[0].startswith("s"):
        printk.error("用法: sed 's/查找/替换/[g]' [文件]\n")
        return 1
    expr = tokens[0]
    delim = expr[1:2]
    if not delim:
        printk.error("用法: sed 's/查找/替换/[g]' [文件]\n")
        return 1
    parts = expr[2:].split(delim)
    if len(parts) < 2:
        printk.error("用法: sed 's/查找/替换/[g]' [文件]\n")
        return 1
    pattern, repl, flags = parts[0], parts[1], parts[2] if len(parts) > 2 else ""
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        printk.error(f"sed: 正则错误: {exc}\n")
        return 1
    text, err = _one_input(tokens[1:], "sed 's/查找/替换/[g]' [文件]")
    if err:
        printk.error(err)
        return 1
    count = 0 if "g" in flags else 1
    try:
        out = "\n".join(regex.sub(repl, line, count=count)
                         for line in text.splitlines())
    except re.error as exc:
        printk.error(f"sed: 替换失败: {exc}\n")
        return 1
    print(out)
    if text.splitlines():
        print()
    return 0


def cmd_date(args=""):
    import datetime
    tokens = _split_args(args)
    fmt = "%a %b %d %H:%M:%S %Z %Y"
    if tokens and tokens[0].startswith("+"):
        fmt = tokens[0][1:]
    now = datetime.datetime.now().astimezone()
    print(now.strftime(fmt))
    print()
    return 0


def _test_expr(tokens):
    """返回 True/False；表达式错抛 ValueError。"""
    if not tokens:
        return False
    if len(tokens) == 1:
        return tokens[0] != ""
    if tokens[0] == "!":
        return not _test_expr(tokens[1:])
    if len(tokens) == 2:
        op, arg = tokens
        if op == "-n":
            return arg != ""
        if op == "-z":
            return arg == ""
        if op == "-e":
            return os.path.exists(arg)
        if op == "-f":
            return os.path.isfile(arg)
        if op == "-d":
            return os.path.isdir(arg)
        if op == "-r":
            return os.access(arg, os.R_OK)
        if op == "-w":
            return os.access(arg, os.W_OK)
        if op == "-x":
            return os.access(arg, os.X_OK)
        raise ValueError(f"未知一元操作符: {op}")
    if len(tokens) == 3:
        left, op, right = tokens
        if op == "=":
            return left == right
        if op == "!=":
            return left != right
        if op in ("-eq", "-ne", "-gt", "-ge", "-lt", "-le"):
            try:
                a, b = int(left), int(right)
            except ValueError:
                raise ValueError("整数比较需要数字")
            return {"-eq": a == b, "-ne": a != b, "-gt": a > b,
                    "-ge": a >= b, "-lt": a < b, "-le": a <= b}[op]
        raise ValueError(f"未知二元操作符: {op}")
    raise ValueError("表达式太复杂（只支持单层）")


def cmd_test(args=""):
    return _run_test(_split_args(args), bracketed=False)


def cmd_lbracket(args=""):
    """`[` 命令：`[` 本身是命令名，只需校验闭合的 `]`。"""
    return _run_test(_split_args(args), bracketed=True)


def _run_test(tokens, bracketed):
    if bracketed:
        if not tokens or tokens[-1] != "]":
            printk.error("用法: [ 表达式 ]\n")
            return 2
        tokens = tokens[:-1]
    try:
        return 0 if _test_expr(tokens) else 1
    except ValueError as exc:
        printk.error(f"test: {exc}\n")
        return 2
