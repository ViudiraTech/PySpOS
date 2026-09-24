#
#   ttyutil.py
#   终端输入防御层（标准库 only，可被 launcher.py 直接 import）。
#
#   背景：curses 会话若异常退出（Ctrl-C 漏网、SIGKILL、子进程 os._exit），
#   tty 会留在 cbreak/icrnl-关闭 的坏状态——回车发出的 \r 不被翻译成 \n，
#   终端直接回显 ^M，之后所有 input() 都读到垃圾并无限重试。
#   成熟做法（vim/less/dialog/reset）：启动时先恢复 sane 状态，
#   输入统一归一化，重试必须有上限。
#

import os
import sys


def is_tty(stream=None) -> bool:
    try:
        return (stream or sys.stdin).isatty()
    except Exception:
        return False


def ensure_sane_tty() -> bool:
    """把 stdin 恢复到 cooked/回显/CR转NL 的 sane 状态。

    返回 True 表示执行过恢复。非 tty / 非 POSIX / 失败一律静默返回 False，
    调用方无需处理——这是防御性调用，不是必须成功的契约。
    """
    try:
        if not is_tty():
            return False
        if os.name != "posix":
            return False
        import subprocess
        # stty sane 正是 reset(1) 恢复输入模式的做法，比手调 termios 全面
        # （icanon/echo/icrnl/ixon/isig 一次修好）。
        r = subprocess.run(["stty", "sane"],
                           stdin=sys.stdin, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


def read_line(prompt: str = "") -> str:
    """input() 的归一化封装：统一处理 \\r\\n/\\r，剥掉行尾空白。

    EOFError / KeyboardInterrupt 原样上抛，由调用方决定语义
    （launcher 视为默认、shell 视为取消），不吞异常。
    """
    s = input(prompt)
    # 坏终端/管道可能送来裸 \r；universal newline 通常已处理，这里是兜底。
    # 关键：先归一化再剥空白，否则 "^M" 会被 strip 吃掉尾巴、又被 input
    # 的 universal-newline 重复处理，导致读回来的是 "^" 这种半截串。
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    # 只去行尾换行与空白，保留行首空格（缩进/密码前缀的语义）
    return s.strip("\n").rstrip()


def read_choice(prompt: str, valid=("y", "n"), default="n",
                max_retries: int = 0) -> str:
    """y/n 类选择的循环读取。

    - 空输入直接取 default（launcher/confirm 的通用语义）；
    - 大小写不敏感，yes/no 全写也接受；
    - max_retries > 0 时，连续无效超过上限返回 default，避免坏终端下死循环；
    - max_retries = 0 表示无限重试（仅用于确信 tty 正常的场景）。
    """
    valid = tuple(v.lower() for v in valid)
    default = default.lower()
    if default not in valid:
        default = valid[0] if valid else ""
    tries = 0
    while True:
        s = read_line(prompt).lower()
        if not s:
            return default
        if s in valid:
            return s
        # 接受全写
        for v in valid:
            if s == v:
                return v
        tries += 1
        if max_retries and tries >= max_retries:
            return default
        print(f"\033[33m无效输入：{s}，请输入 {'/'.join(valid)}（默认 {default}）\033[0m")
