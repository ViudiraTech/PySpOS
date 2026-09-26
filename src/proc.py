'''
 *
 *      proc.py
 *      Compatibility shim re-exporting the names of process.py.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

from process import (
    PCB,
    SIGTERM, SIGKILL, SIGINT, SIGUSR1, SIGUSR2, SIGSTOP, SIGCONT,
    SIGNALS,
    TASK_RUNNING, TASK_INTERRUPTIBLE, TASK_STOPPED, EXIT_ZOMBIE, EXIT_DEAD,
    RUNNING, DONE, FAILED, KILLED, STOPPED,
    EEVDFRunQueue,
    ProcessTable,
    spawn, fork_task, finish, send_signal, parse_signal,
    list_procs, get, reset,
    sched_tick, pick_next, set_nice, avg_vruntime, block, unblock,
    nice_to_weight, NICE_0_LOAD,
)

__all__ = [
    "PCB",
    "SIGTERM", "SIGKILL", "SIGINT", "SIGUSR1", "SIGUSR2", "SIGSTOP", "SIGCONT",
    "SIGNALS",
    "TASK_RUNNING", "TASK_INTERRUPTIBLE", "TASK_STOPPED", "EXIT_ZOMBIE", "EXIT_DEAD",
    "RUNNING", "DONE", "FAILED", "KILLED", "STOPPED",
    "EEVDFRunQueue",
    "ProcessTable",
    "spawn", "fork_task", "finish", "send_signal", "parse_signal",
    "list_procs", "get", "reset",
    "sched_tick", "pick_next", "set_nice", "avg_vruntime", "block", "unblock",
    "nice_to_weight", "NICE_0_LOAD",
]
