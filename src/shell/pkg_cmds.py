'''
 *
 *      pkg_cmds.py
 *      Runs the entry point of an installed user package.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import os

import main
import printk


# Fork the package entry point described by target, waiting or backgrounding it.
# A background run gets its own /tmp log file so its output cannot corrupt the terminal.
def run_entrypoint(target, args="", background=False):
    import forkexec
    import process as proc
    env = {
        "PYSPOS_PACKAGE_ID": target["package_id"],
        "PYSPOS_PACKAGE_VERSION": target["version"],
        "PYSPOS_PACKAGE_ROOT": target["package_dir"],
        "PYSPOS_PACKAGE_ARGS": args,
        "PYSPOS_APP_ARGS": args,
    }
    log_path = None
    if background:
        log_path = os.path.join(
            "/tmp", f"pyspos_bg_{target['name']}_{os.getpid()}.log")
    pcb = forkexec.fork_exec(
        f"app:{target['path']}", kind="package", background=background,
        src_dir=main.script_dir, apps_dir=target["package_dir"], env=env,
        log_path=log_path)
    if background:
        job = proc.new_job(
            f"{target['name']} {args}".strip(), pids=[pcb.pid])
        proc._table().mark_last_bg(pcb.pid)
        printk.ok(f"[{job.job_id}] {pcb.pid}  {target['name']} {args}\n")
    else:
        forkexec.wait(pcb.pid, timeout=None)
        proc.reap_children(pcb.ppid)
    return pcb
