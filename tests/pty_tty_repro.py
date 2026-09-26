'''
 *
 *      pty_tty_repro.py
 *      Manual pty reproduction of the broken-tty caret spam, before and after the ttyutil defence.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import os
import pty
import select
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")


# Run code in a pty with icrnl off, the real fault state where a bare CR echoes as ^M and never ends the line, then press Enter three times and report the counts.
def run_in_broken_pty(code, label, expect_prefix):
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(ROOT)
        os.environ["PYTHONPATH"] = SRC + os.pathsep + os.environ.get("PYTHONPATH", "")
        os.execv(sys.executable, [sys.executable, "-c", code])
    subprocess.run(["stty", "-icrnl"], stdin=fd, stderr=subprocess.DEVNULL)
    time.sleep(0.4)
    for _ in range(3):
        os.write(fd, b"\r")          # Press Enter three times; what goes out is a bare \r
        time.sleep(0.15)
    out, deadline = b"", time.time() + 6
    while time.time() < deadline:
        r, _, _ = select.select([fd], [], [], 0.4)
        if not r:
            continue
        try:
            chunk = os.read(fd, 4096)
        except OSError:
            break
        if not chunk:
            break
        out += chunk
    try:
        os.kill(pid, 9)
    except ProcessLookupError:
        pass
    try:
        os.waitpid(pid, 0)
    except ChildProcessError:
        pass
    os.close(fd)
    text = out.decode("utf-8", "replace")
    n_caret = text.count("^M")
    spins = text.count(expect_prefix)
    print(f"--- {label}")
    print(f"    收到 {len(out)} 字节 | '^M' 出现 {n_caret} 次 | "
          f"提示语出现 {spins} 次")
    tail = [l for l in text.replace("\r", "").splitlines() if l.strip()][-3:]
    for l in tail:
        print(f"    | {l[:70]}")
    return n_caret, spins


# 1) bare input(): must reproduce the problem, which proves the reproduction is real
bare, bare_spins = run_in_broken_pty(
    "s=input('? (y/n)[n]: ')\n"
    "print('GOT', repr(s))",
    "裸 input() 读裸 \\r（icrnl-off）", "?")

# 2) ttyutil: must recover by itself, read one line and exit cleanly
safe, safe_spins = run_in_broken_pty(
    "import ttyutil\n"
    "ttyutil.ensure_sane_tty()\n"
    "r=ttyutil.read_choice('? (y/n)[n]: ', valid=('y','n'),"
    " default='n', max_retries=5)\n"
    "print('GOT', repr(r))",
    "ttyutil.ensure_sane_tty + read_choice", "无效输入")

print()
ok = True
if bare == 0:
    print("注意：裸 input() 未复现 ^M，pty 复现环境可能不够真实")
    ok = False
if safe > 3:
    print(f"失败：read_choice 后仍出现 {safe} 次 ^M")
    ok = False
if safe_spins > 1:
    print(f"失败：无效提示刷了 {safe_spins} 次（有上限=1~2）")
    ok = False
print("结论：", "通过 —— 防御层生效" if ok else "未通过")
sys.exit(0 if ok else 1)
