#
#   shell/proc_cmds.py
#   进程/系统状态命令（由 main.py 拆分而来，行为保持不变）。
#

import sys
import platform
import printk
import kernel
import process as proc  # 进程管理以 process.py（PCB + EEVDF）为准，proc.py 仅为兼容垫片
import pyspos
import ota
import main


def cmd_ps(args: str = ""):
    show_all = (args or "").strip() in ("-a", "--all")
    rows = proc.list_procs(include_done=show_all)
    if not rows:
        print("没有运行中的模拟进程。\n")
        return
    print(f"{'PID':>5}  {'STATE':<8}  {'KIND':<5}  CMD")
    for p in rows:
        print(f"{p.pid:>5}  {p.state:<8}  {p.kind:<5}  {p.cmd}")
    print()


def cmd_jobs():
    cmd_ps()


def cmd_kill(args: str):
    pid_s = (args or "").strip()
    if not pid_s:
        printk.error("用法: kill <pid>\n")
        return
    try:
        pid = int(pid_s)
    except ValueError:
        printk.error(f"kill: 非法 pid: {pid_s}\n")
        return
    ok, msg = proc.send_signal(pid, proc.SIGTERM)
    (printk.ok if ok else printk.error)(msg + "\n")


def cmd_signal(args: str):
    import shlex
    try:
        tokens = shlex.split(args) if args else []
    except ValueError:
        tokens = args.split() if args else []
    if len(tokens) != 2:
        printk.error("用法: signal <pid> <SIGTERM|SIGKILL|SIGSTOP|SIGCONT|SIGUSR1|SIGUSR2>\n")
        return
    try:
        pid = int(tokens[0])
    except ValueError:
        printk.error(f"signal: 非法 pid: {tokens[0]}\n")
        return
    signum = proc.parse_signal(tokens[1])
    if signum is None:
        printk.error(f"signal: 未知信号: {tokens[1]}（可用: TERM/KILL/INT/STOP/CONT/USR1/USR2）\n")
        return
    ok, msg = proc.send_signal(pid, signum)
    (printk.ok if ok else printk.error)(msg + "\n")


def cmd_sysmon():
    print(f"PySpOS {pyspos.OS_VERSION} ({pyspos.OS_DEVELOP_STAGE}) by {pyspos.OS_VENDOR}")
    print(f"Python {platform.python_version()} on {sys.platform} | CPU 逻辑核心: {kernel.cores}")
    try:
        print(f"用户: {kernel.get_system_username()}  ROOT: {'是' if main.rootstate else '否'}")
    except Exception:
        pass
    try:
        st = ota.get_ota_status()
        ota_s = "禁用" if not st.get("ota_enabled", True) else "启用"
        print(f"槽位: {st['current_slot']} ({st['current_version']})  OTA云端: {ota_s}")
    except Exception as e:
        print(f"槽位状态不可用: {e}")
    cmd_ps()
    print()


