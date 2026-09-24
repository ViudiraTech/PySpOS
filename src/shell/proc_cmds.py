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
        print("没有运行中的进程。\n")
        return
    print(f"{'PID':>5}  {'PPID':>5}  {'STATE':<8}  {'KIND':<6}  CMD")
    for p in rows:
        remote = "*" if p.remote else " "
        print(f"{p.pid:>5}{remote} {p.ppid:>5}  {p.state:<8}  {p.kind:<6}  {p.cmd}")
    if any(p.remote for p in rows):
        print("  (* = 真实 OS 子进程)")
    print()


def _parse_job_ref(text: str):
    """支持 %1 / %% / 1 / %+ 形式，返回 Job 或 None。"""
    t = (text or "").strip()
    if not t:
        return None
    t = t.lstrip("%")
    if t in ("", "%"):
        jobs = [j for j in proc.list_jobs() if j.state != proc.DONE]
        return jobs[-1] if jobs else None
    if t == "+":
        jobs = [j for j in proc.list_jobs() if j.state != proc.DONE]
        return jobs[-1] if jobs else None
    if t == "-":
        jobs = [j for j in proc.list_jobs() if j.state != proc.DONE]
        return jobs[-2] if len(jobs) > 1 else None
    try:
        return proc.get_job(int(t))
    except ValueError:
        return None


def cmd_jobs():
    jobs = proc.list_jobs()
    if not jobs:
        print("没有后台作业。\n")
        return
    print(f"{'作业':>4}  {'PID':>5}  {'状态':<9}  命令")
    for j in jobs:
        live = [p for p in j.pids
                if proc.get(p) and proc.get(p).state not in proc.TERMINAL_STATES]
        pids = ",".join(str(p) for p in (live or j.pids))
        mark = "+" if j.state == proc.TASK_RUNNING and live else " "
        print(f"[{j.job_id}]{mark}{pids:>8}  {j.state:<9}  {j.cmdline}")
    print()


def cmd_fg(args: str = ""):
    job = _parse_job_ref(args)
    if job is None:
        printk.error("fg: 无此作业\n")
        return
    live = [p for p in job.pids
            if proc.get(p) and proc.get(p).state not in proc.TERMINAL_STATES]
    if not live:
        printk.error(f"fg: 作业 {job.job_id} 已结束\n")
        return
    import forkexec
    print(f"继续作业 [{job.job_id}] {job.cmdline}")
    for pid in live:
        proc.send_signal(pid, proc.SIGCONT)
    forkexec.wait(live[0], timeout=None)
    proc.reap_children(proc.current_shell_pid())


def cmd_bg(args: str = ""):
    job = _parse_job_ref(args)
    if job is None:
        printk.error("bg: 无此作业\n")
        return
    sent = 0
    for pid in job.pids:
        pcb = proc.get(pid)
        if pcb is not None and pcb.state == proc.TASK_STOPPED:
            ok, _ = proc.send_signal(pid, proc.SIGCONT)
            sent += 1 if ok else 0
    if sent:
        printk.ok(f"作业 [{job.job_id}] 已在后台继续（{sent} 个进程）\n")
    else:
        printk.warn(f"作业 [{job.job_id}] 无处于暂停状态的进程\n")


def cmd_wait(args: str = ""):
    import forkexec
    ref = (args or "").strip()
    if ref:
        job = _parse_job_ref(ref)
        if job is None:
            printk.error("wait: 无此作业\n")
            return
        for pid in job.pids:
            forkexec.wait(pid, timeout=None)
    else:
        for job in list(proc.list_jobs()):
            for pid in job.pids:
                forkexec.wait(pid, timeout=None)
    proc.reap_children(proc.current_shell_pid())
    print()


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
    import process as _p
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
    rq = _p._table().rq
    print(f"调度器: EEVDF | runnable={len(rq._queued)} curr="
          f"{rq.curr.comm if rq.curr else '-'} | 切换次数={rq.nr_switches}")
    cmd_ps()
    print()


