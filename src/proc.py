#
#   proc.py
#   兼容垫片（2026-09-24）：真正的进程管理 + EEVDF 调度器已迁移至 process.py，
#   本模块仅做名称重导出，保证历史调用方（main/shell/tests）零改动。
#
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
