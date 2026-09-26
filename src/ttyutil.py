'''
 *
 *      ttyutil.py
 *      Defensive terminal input handling for curses and prompts.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import os
import sys


# Report whether a stream is an interactive terminal.
def is_tty(stream=None) -> bool:
    try:
        return (stream or sys.stdin).isatty()
    except Exception:
        return False


# Restore stdin to cooked mode with echo and CR translation, via stty sane.
def ensure_sane_tty() -> bool:
    try:
        if not is_tty():
            return False
        if os.name != "posix":
            return False
        import subprocess
# stty sane is exactly how reset(1) restores the input modes, and is more complete than
# hand-editing termios, since it fixes icanon, echo, icrnl, ixon and isig at once.
        r = subprocess.run(["stty", "sane"],
                           stdin=sys.stdin, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


# Read one line with newlines normalised and trailing whitespace stripped.
def read_line(prompt: str = "") -> str:
    s = input(prompt)
# A broken terminal or a pipe can send a bare \r; universal newlines normally handles it, this is the backstop.
# The point: normalise before stripping, otherwise strip eats the tail of a stray ^M and input's
# own universal-newline handling mangles it again, leaving a truncated string such as ^.
    s = s.replace("\r\n", "\n").replace("\r", "\n")
# Only trailing newline and whitespace go; leading spaces are kept, since indentation and password prefixes are meaningful.
    return s.strip("\n").rstrip()


# Full words accepted for the one-letter answers, so the documented yes/no
# answers work as well as y and n.
CHOICE_WORDS = {"y": ("yes",), "n": ("no",)}


# Match one answer against the valid set, accepting a full word for a one-letter
# answer, so 'yes' and 'no' work where the prompt offers y and n.
def _match_choice(text, valid):
    if text in valid:
        return text
    for v in valid:
        if text in CHOICE_WORDS.get(v, ()):
            return v
    return None


# Ask a yes/no style question, retrying up to a limit and then taking the default.
def read_choice(prompt: str, valid=("y", "n"), default="n",
                max_retries: int = 0) -> str:
    valid = tuple(v.lower() for v in valid)
    default = default.lower()
    if default not in valid:
        default = valid[0] if valid else ""
    tries = 0
    while True:
        s = read_line(prompt).lower()
        if not s:
            return default
        match = _match_choice(s, valid)
        if match is not None:
            return match
        tries += 1
        if max_retries and tries >= max_retries:
            return default
        print(f"\033[33m无效输入：{s}，请输入 {'/'.join(valid)}（默认 {default}）\033[0m")
