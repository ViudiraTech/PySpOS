'''
 *
 *      parse_spf.py
 *      Parser for SpaceConfig files.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import gc
import logk
import main
import pyspos

# Run logging is on in alpha and developer builds, where it is badly needed.
if pyspos.OS_DEVELOP_STAGE == "alpha" or pyspos.DEVELOPER_MODE:
    run_log_enabled = 1
else:
    run_log_enabled = 0

# Run the spf file at the given path.
# SPF 2.0 additions (2026-09-24, backward compatible with the 0.1 putchar/exit):
# print("...")        putchar alias, with $variable interpolation
# var(name, "val")    define a variable
# set(name, "val")    change a variable, creating it if absent
# add(a, b, out)      add a and b into out, either may be a name or a number
# input("prompt", out) read a line into out
# sleep(seconds)      sleep
# include("other.spf") run another spf, depth capped at 8 to catch cycles
def run_spf(spf_path, _depth=0, _env=None):
    if _env is None:
        _env = {}
    if _depth > 8:
        raise RecursionError("spf include 嵌套过深（>8），疑似循环引用")
    if not spf_path:
        raise SyntaxError("path is null")

    try:
        with open(spf_path, 'r', encoding='utf-8') as f:
            code = f.read()

        lines = code.splitlines()
        cleaned_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped and not (stripped.startswith("#") or stripped.startswith("//")):
                cleaned_lines.append(stripped)
        
        code = "".join(cleaned_lines)
        if run_log_enabled:
            print(f"File content:\n{code}")
        if not code:
            raise SyntaxError("An error occurred while reading the spf file, the file may be empty or corrupted")

        code = code.rstrip() + ";"
        commands = [cmd.strip() for cmd in code.split(";") if cmd.strip()]

        for cmd in commands:
            try:
                cmd_stripped = cmd.strip()

                if cmd_stripped.startswith("#") or cmd_stripped.startswith("//"):
                    continue
                if not cmd_stripped:
                    continue

# Strip one layer of matching quotes, if present.
                def _unquote(s):
                    s = s.strip()
                    if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
                        return s[1:-1]
                    return s

# Expand $name from the environment; $$ is a literal dollar sign.
                def _subst(s):
                    out = []
                    i = 0
                    while i < len(s):
                        if s[i] == '$' and i + 1 < len(s) and s[i + 1] == '$':
                            out.append('$')
                            i += 2
                        elif s[i] == '$':
                            j = i + 1
                            while j < len(s) and (s[j].isalnum() or s[j] == '_'):
                                j += 1
                            name = s[i + 1:j]
                            out.append(str(_env.get(name, '')))
                            i = j
                        else:
                            out.append(s[i])
                            i += 1
                    return ''.join(out)

# Split a call's arguments on commas, ignoring commas inside quotes.
                def _split_args(inner):
                    args, cur, q = [], '', None
                    for ch in inner:
                        if q:
                            cur += ch
                            if ch == q:
                                q = None
                        elif ch in ('"', "'"):
                            q = ch
                            cur += ch
                        elif ch == ',':
                            args.append(cur.strip())
                            cur = ''
                        else:
                            cur += ch
                    if cur.strip() or args:
                        args.append(cur.strip())
                    return [a for a in args if a != '']

# Coerce an argument to int, then float, resolving a variable name first.
                def _num(v):
                    if isinstance(v, (int, float)):
                        return v
                    v = str(v).strip()
                    if v in _env:
                        v = _env[v]
                    try:
                        return int(v)
                    except (ValueError, TypeError):
                        return float(v)

                if cmd_stripped.startswith("putchar(") and cmd_stripped.endswith(")"):
                    param = cmd_stripped[8:-1].strip()

                    if not (param.startswith('"') and param.endswith('"')):
                        raise SyntaxError(f"putchar parameter must be string, got {param}")

                    output_str = _subst(param[1:-1])
                    print(output_str)

                elif cmd_stripped.startswith("print(") and cmd_stripped.endswith(")"):
                    param = _unquote(cmd_stripped[6:-1])
                    print(_subst(param))

                elif cmd_stripped.startswith("var(") and cmd_stripped.endswith(")"):
                    args = _split_args(cmd_stripped[4:-1])
                    if len(args) != 2:
                        raise SyntaxError(f"var 需要 2 个参数，got {args}")
                    _env[args[0].strip()] = _unquote(args[1])

                elif cmd_stripped.startswith("set(") and cmd_stripped.endswith(")"):
                    args = _split_args(cmd_stripped[4:-1])
                    if len(args) != 2:
                        raise SyntaxError(f"set 需要 2 个参数，got {args}")
                    _env[args[0].strip()] = _unquote(args[1])

                elif cmd_stripped.startswith("add(") and cmd_stripped.endswith(")"):
                    args = _split_args(cmd_stripped[4:-1])
                    if len(args) != 3:
                        raise SyntaxError(f"add 需要 3 个参数，got {args}")
                    _env[args[2].strip()] = _num(args[0]) + _num(args[1])

                elif cmd_stripped.startswith("input(") and cmd_stripped.endswith(")"):
                    args = _split_args(cmd_stripped[6:-1])
                    if len(args) != 2:
                        raise SyntaxError(f"input 需要 2 个参数，got {args}")
                    prompt = _subst(_unquote(args[0]))
                    _env[args[1].strip()] = input(prompt)

                elif cmd_stripped.startswith("sleep(") and cmd_stripped.endswith(")"):
                    import time as _time
                    _time.sleep(float(_unquote(cmd_stripped[6:-1])))

                elif cmd_stripped.startswith("include(") and cmd_stripped.endswith(")"):
                    import os as _os
                    inc = _unquote(cmd_stripped[8:-1])
                    if not _os.path.isabs(inc):
                        inc = _os.path.join(_os.path.dirname(_os.path.abspath(spf_path)), inc)
                    run_spf(inc, _depth=_depth + 1, _env=_env)

                elif cmd_stripped.startswith("exit(") and cmd_stripped.endswith(")"):
                    param = cmd_stripped[5:-1].strip()
                    if not param:
                        raise SyntaxError("You must provide an exit code")
                    if run_log_enabled:
                        logk.printl("parser_spf", f"SPF file path: {spf_path} is exited, exitcode is {int(param)}", main.boot_time)
                    print()
                    return

                else:
                    raise SyntaxError(f"Unknown code {cmd_stripped}")
            except Exception as cmd_err:
                logk.printl("parser_spf", f"cmd '{cmd}' execute failed: {cmd_err}", main.boot_time)
                continue
        
        gc.collect()
    
    except Exception as i:
        logk.printl("parser_spf", f"spf run has fatal error: {i}", main.boot_time)