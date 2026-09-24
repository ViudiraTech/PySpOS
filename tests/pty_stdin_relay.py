#!/usr/bin/env python3
"""pty 实测前台交互：把答案真正喂进子进程 stdin。

验证 stdin 中继（裸 os.pipe 字节流）端到端可用：父终端按键 →
_pump_in 逐字节写管道 → 子进程 os.fdopen(stdin).readline() 拿到数据。
"""
import os
import pty
import select
import signal
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEEDLE = "输入你猜的数字".encode("utf-8")

CHILD = r"""
import sys, time
sys.path.insert(0, 'src')
import forkexec, process as proc
pcb = forkexec.fork_exec('app:zzlsb.py', background=False)
for _ in range(60):
    time.sleep(0.2)
    if pcb.state in proc.TERMINAL_STATES:
        break
print('FINAL state=%s code=%s' % (pcb.state, pcb.exit_code))
sys.stdout.flush()
"""


def read_avail(fd, timeout=0.4):
    r, _, _ = select.select([fd], [], [], timeout)
    if not r:
        return b""
    try:
        return os.read(fd, 4096)
    except OSError:
        return b""


def main():
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(ROOT)
        os.environ["PYTHONPATH"] = "src"
        os.execv(sys.executable, [sys.executable, "-c", CHILD])

    out = b""
    fed = 0
    deadline = time.time() + 25
    while time.time() < deadline:
        chunk = read_avail(fd)
        if chunk:
            out += chunk
        if fed < 2 and NEEDLE in out:
            time.sleep(0.2)
            # 猜 50：命中就说恭喜，不中会说猜大了/猜小了，两种都能验证读到
            os.write(fd, b"50\n")
            fed += 1
        if b"FINAL" in out:
            break
    try:
        os.kill(pid, signal.SIGKILL)
        os.waitpid(pid, 0)
    except (ProcessLookupError, ChildProcessError):
        pass
    os.close(fd)

    text = out.decode("utf-8", "replace")
    print(text)
    print("=" * 60)
    checks = [
        ("父进程看到子进程 banner", "简单猜数字游戏" in text),
        ("提示语出现", "输入你猜的数字" in text),
        ("子进程确实读到了输入", ("猜大了" in text or "猜小了" in text
                                 or "恭喜" in text)),
        ("子进程正常终止", "FINAL state=" in text),
        ("未出现 EOF traceback", "EOF when reading" not in text),
    ]
    bad = 0
    for name, good in checks:
        print(f"  [{'OK ' if good else 'FAIL'}] {name}")
        if not good:
            bad += 1
    print("结论：", "前台 stdin 中继端到端正常" if not bad else f"{bad} 项失败")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
