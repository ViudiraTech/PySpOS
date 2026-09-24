#!/usr/bin/env python3
"""pty 实测：在「坏 tty」下按 Enter，验证不再刷 ^M。

模拟真实故障态（icrnl-off，回车 \r 不翻译成 \n），然后：
  1. 直接用裸 input() 读 —— 应复现刷屏/空循环（即用户看到的现象）；
  2. 换成 ttyutil.read_choice —— 应一次读到默认并干净退出。

这比任何单测都更有说服力：真的开了 pty，真的关了 icrnl。
"""
import os
import pty
import select
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")


def run_in_broken_pty(code, label, expect_prefix):
    """开一个 pty，只关 icrnl（保留 icanon+echo），再跑 code。

    真实故障态就是 icrnl-off：canonical 模式下 IC RNL 关掉后，回车发出的
    \\r 不会被翻译成行结束符 \\n，终端只把它当普通字符回显成 ^M，
    input() 于是永远等不到行结束——用户每按一次 Enter 就多一个 ^M。
    """
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(ROOT)
        os.environ["PYTHONPATH"] = SRC + os.pathsep + os.environ.get("PYTHONPATH", "")
        os.execv(sys.executable, [sys.executable, "-c", code])
    subprocess.run(["stty", "-icrnl"], stdin=fd, stderr=subprocess.DEVNULL)
    time.sleep(0.4)
    for _ in range(3):
        os.write(fd, b"\r")          # 连按三次 Enter，发的是裸 \r
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


# 1) 裸 input()：应当复现问题（证明复现环境是真实的）
bare, bare_spins = run_in_broken_pty(
    "s=input('? (y/n)[n]: ')\n"
    "print('GOT', repr(s))",
    "裸 input() 读裸 \\r（icrnl-off）", "?")

# 2) ttyutil：应当自行恢复，一行读完干净退出
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
