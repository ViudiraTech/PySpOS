'''
 *
 *      process.py
 *      Process table, PCB state, EEVDF scheduling and job control.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import heapq
import itertools
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# --------------------------------------------------------------------------
# constants mirroring kernel semantics; values are picked for teaching readability and are float milliseconds
# --------------------------------------------------------------------------

NICE_0_LOAD = 1024          # the kernel's NICE_0_LOAD
PID_MAX = 32768             # the kernel's PID_MAX_DEFAULT, simplified as a bitmap ceiling

# reserved PIDs, with Linux semantics: 0=idle/swapper (driven by the invisible scheduler),
# 1=init (orphan adoption, zombie reaping, signal forwarding), 2=shell (init's child, driven interactively).
PID_IDLE = 0
PID_INIT = 1
PID_SHELL = 2
RESERVED_PIDS = (PID_IDLE, PID_INIT, PID_SHELL)

BASE_SLICE_MS = 6.0         # sysctl_sched_base_slice, whose kernel default is roughly 3-6ms
MIN_SLICE_MS = 0.75         # minimum slice guard, after sysctl_sched_min_granularity
MAX_SLICE_MS = 24.0         # per-slice ceiling so one task cannot monopolise the CPU

# the kernel's sched_prio_to_weight[40] for nice -20..19, copied verbatim so the weight ratios are real
_SCHED_PRIO_TO_WEIGHT = (
    88761, 71755, 56483, 46273, 36291,
    29154, 23254, 18705, 14949, 11916,
    9548, 7620, 6100, 4904, 3906,
    3121, 2501, 1991, 1586, 1277,
    1024, 820, 655, 526, 423,
    335, 272, 215, 172, 137,
    110, 87, 70, 56, 45,
    36, 29, 23, 18, 15,
)


# Map a nice value in [-20, 19] onto its scheduler weight.
def nice_to_weight(nice: int) -> int:
    nice = max(-20, min(19, int(nice)))
    return _SCHED_PRIO_TO_WEIGHT[nice + 20]


# --------------------------------------------------------------------------
# signal numbers, kept from proc.py so the shell commands stay compatible
# --------------------------------------------------------------------------

SIGTERM = 15
SIGKILL = 9
SIGINT = 2
SIGUSR1 = 10
SIGUSR2 = 12
SIGSTOP = 19
SIGCONT = 18

SIGNALS: Dict[str, int] = {
    "SIGTERM": SIGTERM, "TERM": SIGTERM, "15": SIGTERM,
    "SIGKILL": SIGKILL, "KILL": SIGKILL, "9": SIGKILL,
    "SIGINT": SIGINT, "INT": SIGINT, "2": SIGINT,
    "SIGUSR1": SIGUSR1, "USR1": SIGUSR1, "10": SIGUSR1,
    "SIGUSR2": SIGUSR2, "USR2": SIGUSR2, "12": SIGUSR2,
    "SIGSTOP": SIGSTOP, "STOP": SIGSTOP, "19": SIGSTOP,
    "SIGCONT": SIGCONT, "CONT": SIGCONT, "18": SIGCONT,
}


# Turn a signal name or number into a signal number, or None.
def parse_signal(text: str) -> Optional[int]:
    if text is None:
        return None
    return SIGNALS.get(str(text).strip().upper())


# --------------------------------------------------------------------------
# task states mirroring Linux task_state, with the old proc.py English names kept for compatibility
# --------------------------------------------------------------------------

TASK_RUNNING = "Running"            # TASK_RUNNING: runnable or running
TASK_INTERRUPTIBLE = "Sleeping"     # TASK_INTERRUPTIBLE: interruptible sleep
TASK_STOPPED = "Stopped"            # TASK_STOPPED: stopped by SIGSTOP
EXIT_ZOMBIE = "Zombie"              # EXIT_ZOMBIE: exited, awaiting reaping
EXIT_DEAD = "Dead"                  # EXIT_DEAD: already reaped

# kept for the old proc.py state names
RUNNING = TASK_RUNNING
DONE = "Done"
FAILED = "Failed"
KILLED = "Killed"
STOPPED = TASK_STOPPED


# Process control block: the teaching subset of Linux's task_struct.
@dataclass
class PCB:
    pid: int
    comm: str                       # task name, Linux task_struct.comm
    state: str = TASK_RUNNING
    ppid: int = 0
    pgrp: int = 0                   # process group, defaulting to the pid so each command stands alone as in bash
    session: int = 0                # session, defaulting to the shell's session
    nice: int = 0
    static_prio: int = 120          # the kernel's static_prio = MAX_RT_PRIO(100) + nice + 20
    weight: int = NICE_0_LOAD
    vruntime: float = 0.0           # sched_entity.vruntime
    deadline: float = 0.0           # sched_entity.deadline, the virtual deadline
    slice: float = BASE_SLICE_MS    # slice requested this round, in real milliseconds
    sum_exec_runtime: float = 0.0   # se.sum_exec_runtime, cumulative real running time in ms
    nvcsw: int = 0                  # voluntary context switches
    nivcsw: int = 0                 # involuntary switches, that is preemptions
    exit_code: int = 0
    signal: int = 0                 # last fatal signal received
    pending: List[int] = field(default_factory=list)  # pending signal queue
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    kind: str = "app"               # app | elf | spf | shell | init | idle | kthread
    remote: bool = False            # True means it runs as a real host child and never enters the EEVDF run queue
    job_id: Optional[int] = None    # owning background job number
    note: str = ""
    cmd: str = ""                   # legacy proc.py compatibility: the full command line
    _gen: int = 0                   # run queue heap entry generation, internal

# Default the command name to comm when it was not given.
    def __post_init__(self):
        if not self.cmd:
            self.cmd = self.comm
        if not self.pgrp:
            self.pgrp = self.pid
        if not self.session:
            self.session = PID_SHELL
        self.static_prio = 100 + self.nice + 20
        self.weight = nice_to_weight(self.nice)

# Return the last scheduling-lag snapshot; the run queue owns the live value.
    @property
    def lag(self) -> float:
        return getattr(self, "_lag_snapshot", 0.0)


# --------------------------------------------------------------------------
# PID allocation, a simplification of the Linux bitmap: sequential inside a range, wrapping to reuse
# --------------------------------------------------------------------------

# Hands out PIDs from a bounded range, wrapping to avoid the reserved low ones.
class PidAllocator:
# Set the highest PID this allocator may hand out.
    def __init__(self, pid_max: int = PID_MAX):
        self.pid_max = pid_max
        self._used: set = set()
        self._next = 1

# Return the next free PID, skipping the reserved low range.
    def alloc(self) -> int:
        for _ in range(self.pid_max):
            pid = self._next
            self._next += 1
            if self._next > self.pid_max:
                self._next = 1
            if pid not in self._used:
                self._used.add(pid)
                return pid
        raise RuntimeError("pid 位图耗尽")

# Return a PID to the free pool.
    def free(self, pid: int) -> None:
        self._used.discard(pid)

# Mark a PID as permanently taken, such as idle, init and shell.
    def reserve(self, pid: int) -> None:
        self._used.add(pid)
        if self._next <= pid:
            self._next = pid + 1

# Forget every reserved and allocated PID.
    def reset(self) -> None:
        self._used.clear()
        self._next = 1


# --------------------------------------------------------------------------
# the EEVDF run queue for a single CPU, the EEVDF subset of the kernel's struct cfs_rq
# --------------------------------------------------------------------------

# Earliest Eligible Virtual Deadline First run queue.
class EEVDFRunQueue:
# Create an empty run queue with the given slice bounds.
    def __init__(self, base_slice: float = BASE_SLICE_MS,
                 min_slice: float = MIN_SLICE_MS):
        self.base_slice = base_slice
        self.min_slice = min_slice
        self.min_vruntime = 0.0     # cfs_rq->min_vruntime, monotonically increasing
        self.curr: Optional[PCB] = None
        self._heap: list = []       # (deadline, vruntime, seq, pid)
        self._seq = itertools.count()
        self._queued: Dict[int, PCB] = {}   # pid to PCB, for tasks currently on the run queue
        self.nr_switches = 0
        self.timeline: List[Tuple[float, int, str]] = []  # (vtime, pid, event)

# -- enqueue / dequeue ------------------------------------------------

# Make a runnable task eligible, ignoring host children.
    def enqueue(self, pcb: PCB) -> None:
# SIMPLIFY: place_entity is simplified; a woken task is clamped to min_vruntime,
# keeping the owed-debt preference but not the kernel's full PLACE_LAG/vlag decay.
# a remote task runs as a real host child on the host CPU and stays out of the virtual run queue.
        if pcb.remote:
            return
        if pcb.state == TASK_RUNNING:
            if pcb.vruntime < self.min_vruntime:
                pcb.vruntime = self.min_vruntime
            if pcb.deadline <= pcb.vruntime:
                pcb.deadline = pcb.vruntime + self._vslice(pcb)
            pcb._gen += 1
            self._queued[pcb.pid] = pcb
            heapq.heappush(self._heap,
                            (pcb.deadline, pcb.vruntime, next(self._seq), pcb.pid, pcb._gen))

# Remove a task from the run queue by PID.
    def dequeue(self, pcb: PCB) -> None:
        self._queued.pop(pcb.pid, None)   # heap entries are invalidated lazily, detected through _gen
        if self.curr is pcb:
            self.curr = None

# Return the queued PCB for a PID when the generation still matches.
    def _live_entry(self, pid: int, gen: int) -> Optional[PCB]:
        pcb = self._queued.get(pid)
        if pcb is None or pcb._gen != gen or pcb.state != TASK_RUNNING:
            return None
        return pcb

# -- core vruntime / deadline formulas ---------------------------------

# Return the fair delta: exec slice scaled by NICE_0_LOAD over weight.
    @staticmethod
    def calc_delta_fair(delta_ms: float, weight: int) -> float:
        return delta_ms * NICE_0_LOAD / max(1, weight)

# Sum the weights of every queued task.
    def _total_weight(self) -> int:
        w = sum(p.weight for p in self._queued.values())
        if self.curr is not None and self.curr.pid not in self._queued:
            w += self.curr.weight
        return max(1, w)

# Return the virtual slice, the real slice normalised by weight.
    def _vslice(self, pcb: PCB) -> float:
        return self.calc_delta_fair(pcb.slice, pcb.weight)

# Return min_vruntime plus the weighted mean lag, Linux-style.
    def avg_vruntime(self) -> float:
        ents = [p for p in self._queued.values() if p.state == TASK_RUNNING]
        if self.curr is not None and self.curr.state == TASK_RUNNING \
                and self.curr.pid not in self._queued:
            ents.append(self.curr)
        if not ents:
            return self.min_vruntime
        total_w = sum(p.weight for p in ents)
        if total_w <= 0:
            return self.min_vruntime
        s = sum(p.weight * (p.vruntime - self.min_vruntime) for p in ents)
        return self.min_vruntime + s / total_w

# Recompute min_vruntime from runnable, non-preempted tasks.
    def _update_min_vruntime(self) -> None:
        cands = [p.vruntime for p in self._queued.values()
                 if p.state == TASK_RUNNING]
        if self.curr is not None and self.curr.state == TASK_RUNNING:
            cands.append(self.curr.vruntime)
        if cands:
            m = min(cands)
            if m > self.min_vruntime:
                self.min_vruntime = m

# eligible <=> lag >= 0 <=> vruntime <= avg_vruntime。
    def eligible(self, pcb: PCB) -> bool:
        return pcb.vruntime <= self.avg_vruntime() + 1e-9

# -- picking a task: pick_eevdf -----------------------------------------

# Choose the eligible task with the smallest virtual runtime.
    def pick_next(self) -> Optional[PCB]:
        avg = self.avg_vruntime()
        best = None
        best_key = None
        fallback = None
        fallback_key = None
# eligible the heap top may be stale, so pop dead entries and scan; task counts are small enough that a full scan is safer.
        cands = [p for p in self._queued.values() if p.state == TASK_RUNNING]
        for p in cands:
            key = (p.deadline, p.vruntime, p.pid)
            if p.vruntime <= avg + 1e-9:      # eligible
                if best_key is None or key < best_key:
                    best, best_key = p, key
            if fallback_key is None or key < fallback_key:
                fallback, fallback_key = p, key
        return best if best is not None else fallback

# -- slice assignment ----------------------------------------------------

# Assign the next time slice, scaled by weight and clamped to bounds.
    def assign_slice(self, pcb: PCB) -> None:
        total = self._total_weight()
        s = self.base_slice * pcb.weight / total
        pcb.slice = max(self.min_slice, min(MAX_SLICE_MS, s))
        pcb.deadline = pcb.vruntime + self._vslice(pcb)

# -- tick: update_curr plus scheduling ----------------------------------

# Advance the running task and reschedule when its slice runs out.
    def tick(self, delta_ms: float) -> Optional[PCB]:
        if self.curr is None or self.curr.state != TASK_RUNNING:
            nxt = self.pick_next()
            self._switch_to(nxt)
            return self.curr
        cur = self.curr
# update_curr: advance vruntime
        cur.sum_exec_runtime += delta_ms
        cur.vruntime += self.calc_delta_fair(delta_ms, cur.weight)
        self._update_min_vruntime()
# slice spent (vruntime passes the deadline): update the deadline and pick again
        if cur.vruntime >= cur.deadline - 1e-9:
            self._requeue_current()
            nxt = self.pick_next()
            self._switch_to(nxt)
        else:
# preemption check: if an eligible task has an earlier deadline, preempt the current one.
# a teaching simplification of the kernel's wakeup_preempt plus RUN_TO_PARITY slice protection:
# the protection collapses to a min_slice floor enforced by assign_slice.
            r = self._preempt_candidate(cur)
            if r is not None:
                self._requeue_current(preempted=True)
                self._switch_to(r)
        return self.curr

# Return the task that should take over from the current one.
    def _preempt_candidate(self, cur: PCB) -> Optional[PCB]:
        avg = self.avg_vruntime()
        best = None
        for p in self._queued.values():
            if p.state != TASK_RUNNING or p.pid == cur.pid:
                continue
            if p.vruntime <= avg + 1e-9 and p.deadline < cur.deadline - 1e-9:
                if best is None or (p.deadline, p.vruntime) < (best.deadline, best.vruntime):
                    best = p
        return best

# Put the preempted task back on the queue with its lag recorded.
    def _requeue_current(self, preempted: bool = False) -> None:
        cur = self.curr
        if cur is None:
            return
        if preempted:
            cur.nivcsw += 1
        else:
            cur.nvcsw += 1
        if cur.state == TASK_RUNNING:
# update_deadline: once the deadline has passed, push it out by one vslice
            if cur.vruntime >= cur.deadline - 1e-9:
                cur.deadline = cur.vruntime + self._vslice(cur)
            cur._gen += 1
            self._queued[cur.pid] = cur
            heapq.heappush(self._heap,
                            (cur.deadline, cur.vruntime, next(self._seq), cur.pid, cur._gen))
        self.curr = None

# Make a task current, or clear the current task when given None.
    def _switch_to(self, nxt: Optional[PCB]) -> None:
        if nxt is None:
            self.curr = None
            return
        self.dequeue(nxt)          # take from the runnable set; curr is not on the queue
        self.assign_slice(nxt)
        self.curr = nxt
        self.nr_switches += 1
        self.timeline.append((self.min_vruntime, nxt.pid, f"switch-to deadline={nxt.deadline:.3f}"))


# --------------------------------------------------------------------------
# the process table, a global singleton standing in for the kernel's PID hash plus global run queues
# --------------------------------------------------------------------------

# A background job: a command line plus the PIDs sharing its process group.
@dataclass
class Job:
    job_id: int
    cmdline: str
    pids: List[int] = field(default_factory=list)
    background: bool = True
    state: str = TASK_RUNNING       # Running | Stopped | Done
    started: float = field(default_factory=time.time)


TERMINAL_STATES = (DONE, FAILED, "Killed", EXIT_ZOMBIE, EXIT_DEAD)


# The system-wide process table, job list and run queue.
class ProcessTable:
# Create an empty process table with its PID allocator.
    def __init__(self):
        self.pids = PidAllocator()
        self.tasks: Dict[int, PCB] = {}
        self.rq = EEVDFRunQueue()
# real child handle (multiprocessing.Process), stored opaquely so the PCB stays copyable
        self.handles: Dict[int, Any] = {}
        self.jobs: Dict[int, Job] = {}
        self._job_seq = itertools.count(1)
        self.last_bg_pid: Optional[int] = None   # $!
# remote signal backend, registered by forkexec; without it remote tasks stay purely simulated
        self._remote_signal_backend = None

# Install the callback that delivers signals to host processes.
    def set_remote_signal_backend(self, fn) -> None:
        self._remote_signal_backend = fn

# -- boot: idle(0) / init(1) / shell(2) -----------------------------------

# Register idle(0), init(1) and shell(2) so ps works before any command; idempotent.
    def boot_system(self) -> Dict[str, PCB]:
        if PID_INIT in self.tasks:
            return {"idle": self.tasks[PID_IDLE], "init": self.tasks[PID_INIT],
                    "shell": self.tasks[PID_SHELL]}
        for pid in RESERVED_PIDS:
            self.pids.reserve(pid)
        idle = PCB(pid=PID_IDLE, comm="swapper/0", kind="idle",
                   state=TASK_INTERRUPTIBLE, ppid=PID_IDLE)
        init = PCB(pid=PID_INIT, comm="init", kind="init",
                   state=TASK_INTERRUPTIBLE, ppid=PID_IDLE)
        shell = PCB(pid=PID_SHELL, comm="pyspos-sh", kind="shell",
                    state=TASK_RUNNING, ppid=PID_INIT,
                    cmd="pyspos-sh")
        self.tasks[PID_IDLE] = idle
        self.tasks[PID_INIT] = init
        self.tasks[PID_SHELL] = shell
        return {"idle": idle, "init": init, "shell": shell}

# Report whether the process tree has been created.
    def is_booted(self) -> bool:
        return PID_INIT in self.tasks

# Return the shell PID, or 0 before boot.
    def current_shell_pid(self) -> int:
        return PID_SHELL if self.is_booted() else 0

# -- create / exit ------------------------------------------------------

# Create a PCB, defaulting the parent to the shell.
    def spawn(self, comm: str, kind: str = "app", nice: int = 0,
              ppid: int = 0, note: str = "", remote: bool = False,
              pgrp: int = 0, enqueue_rq: bool = True) -> PCB:
        if not ppid:
            ppid = self.current_shell_pid()
        pid = self.pids.alloc()
        pcb = PCB(pid=pid, comm=comm, kind=kind, nice=nice, ppid=ppid,
                  note=note, cmd=comm, remote=remote,
                  pgrp=pgrp or pid)
        self.tasks[pid] = pcb
        if enqueue_rq and not remote:
            self.rq.enqueue(pcb)
        return pcb

    fork_task = spawn  # alias: for teaching purposes fork is about spawn

# Retire a task into an explicit state, Zombie meaning not yet reaped.
    def exit_task(self, pid: int, exit_code: int = 0,
                  state: str = EXIT_ZOMBIE) -> Optional[PCB]:
        pcb = self.tasks.get(pid)
        if pcb is None:
            return None
        pcb.exit_code = exit_code
        pcb.state = state
        pcb.end_time = time.time()
        self.rq.dequeue(pcb)
        if state in (DONE, FAILED, "Killed", EXIT_DEAD):
# terminal state names kept compatible with the old proc.py
            pass
# Linux semantics: when a parent dies its children are re-parented to init, whose newly adopted zombies are reaped at once
        self.adopt_orphans(pid)
        return pcb

# Settle CPU time for a real child and move it to Zombie.
    def child_exited(self, pid: int, exit_code: int = 0,
                     wall_ms: float = 0.0) -> Optional[PCB]:
        pcb = self.tasks.get(pid)
        if pcb is None:
            return None
        if wall_ms > 0:
            self.charge_remote(pid, wall_ms)
        return self.exit_task(pid, exit_code=exit_code, state=EXIT_ZOMBIE)

# Book wall-clock CPU time for a host process the scheduler never saw.
    def charge_remote(self, pid: int, wall_ms: float) -> None:
        pcb = self.tasks.get(pid)
        if pcb is None or wall_ms <= 0:
            return
        pcb.sum_exec_runtime += wall_ms
        pcb.vruntime += self.rq.calc_delta_fair(wall_ms, pcb.weight)

# Re-parent the children of a dead PID, reaping those already zombies.
    def adopt_orphans(self, dead_pid: int) -> List[PCB]:
        reaped = []
        for pcb in list(self.tasks.values()):
            if pcb.ppid == dead_pid and pcb.pid != dead_pid:
                pcb.ppid = PID_INIT
                if pcb.state in TERMINAL_STATES:
                    self.reap(pcb.pid)
                    reaped.append(pcb)
        return reaped

# Reap a parent's zombie children, wait semantics, and return their PCBs.
    def reap_children(self, ppid: int) -> List[PCB]:
        done = []
        for pcb in list(self.tasks.values()):
            if pcb.ppid == ppid and pcb.state in TERMINAL_STATES:
                self.reap(pcb.pid)
                done.append(pcb)
        if done:
            self._refresh_job_states()
        return done

# Block until a PID reaches a terminal state; timeout None waits forever.
    def wait_for(self, pid: int, timeout: Optional[float] = 30.0) -> Optional[PCB]:
        deadline = None if timeout is None else time.time() + max(0.0, timeout)
        while deadline is None or time.time() < deadline:
            pcb = self.tasks.get(pid)
            if pcb is None or pcb.state in TERMINAL_STATES:
                return pcb
            time.sleep(0.02)
        return self.tasks.get(pid)

# Release a Zombie PCB and free its PID, the simple release_task equivalent.
    def reap(self, pid: int) -> Optional[PCB]:
        pcb = self.tasks.get(pid)
        if pcb is None:
            return None
        pcb.state = EXIT_DEAD
        self.rq.dequeue(pcb)
        self.pids.free(pid)
        return self.tasks.pop(pid, None)

# -- sleep / wake ------------------------------------------------------

# Move a task out of the runnable set into a blocked state.
    def block(self, pid: int, state: str = TASK_INTERRUPTIBLE) -> bool:
        pcb = self.tasks.get(pid)
        if pcb is None or pcb.state != TASK_RUNNING:
            return False
        pcb.state = state
        pcb.nvcsw += 1
        self.rq.dequeue(pcb)
        return True

# Move a blocked task back into the runnable set.
    def unblock(self, pid: int) -> bool:
        pcb = self.tasks.get(pid)
        if pcb is None or pcb.state not in (TASK_INTERRUPTIBLE, TASK_STOPPED):
            return False
        if pcb.state == TASK_STOPPED:
            return False  # only SIGCONT clears STOP
        pcb.state = TASK_RUNNING
        self.rq.enqueue(pcb)
# wakeup_preempt simplified: a woken task with an earlier deadline preempts immediately
        cur = self.rq.curr
        if cur is not None and pcb.deadline < cur.deadline - 1e-9 \
                and self.rq.eligible(pcb):
            self.rq._requeue_current(preempted=True)
            self.rq._switch_to(pcb)
        return True

# -- signals --------------------------------------------------------------

# Deliver a signal to a simulated or host process.
    def send_signal(self, pid: int, signum: int) -> Tuple[bool, str]:
        pcb = self.tasks.get(pid)
        if pcb is None:
            return False, f"没有 PID 为 {pid} 的进程"
        if pcb.state in (DONE, FAILED, EXIT_ZOMBIE, EXIT_DEAD):
            return False, f"进程 {pid} 已结束（{pcb.state}），无法发信号"
# a real child: deliver at the OS level first (terminate/kill/POSIX signal), then fold into the shared state machine
        via = ""
        if pcb.remote and self._remote_signal_backend is not None:
            try:
                delivered, note = self._remote_signal_backend(pcb, signum)
            except Exception as e:
                return False, f"向 {pid} 投递信号失败: {e}"
            if not delivered:
                return False, note
            via = f"（{note}）"
            if signum == SIGSTOP:
                pcb.signal = signum
                pcb.state = TASK_STOPPED
                self.rq.dequeue(pcb)
                return True, f"进程 {pid} 已暂停{via}"
            if signum == SIGCONT:
                pcb.signal = 0
                if pcb.state == TASK_STOPPED:
                    pcb.state = TASK_RUNNING
                return True, f"进程 {pid} 已继续{via}"
        if signum in (SIGKILL, SIGTERM, SIGINT):
            pcb.signal = signum
            self.exit_task(pid, exit_code=128 + signum, state="Killed")
            return True, f"已向 {pid} 发送信号 {signum}，进程已终止{via}"
        if signum == SIGSTOP:
            if self.block(pid, TASK_STOPPED):
                pcb.signal = signum
                return True, f"进程 {pid} 已暂停（SIGSTOP）"
            return False, f"进程 {pid} 状态为 {pcb.state}，无法暂停"
        if signum == SIGCONT:
            if pcb.state == TASK_STOPPED:
                pcb.state = TASK_RUNNING
                pcb.signal = 0
                self.rq.enqueue(pcb)
                return True, f"进程 {pid} 已继续（SIGCONT）"
            return False, f"进程 {pid} 未被暂停（{pcb.state}）"
        pcb.pending.append(signum)
        pcb.signal = signum
        if not via:
            pcb.note = (pcb.note + f" [sig{signum}]").strip()
        return True, f"已向 {pid} 发送信号 {signum}{via}"

# -- background jobs (bash jobs semantics) --------------------------------

# Register a job with its PIDs and return the Job record.
    def new_job(self, cmdline: str, pids: Optional[List[int]] = None,
                background: bool = True) -> Job:
        job = Job(job_id=next(self._job_seq), cmdline=cmdline, pids=list(pids or []))
        if not job.pids:
            job.state = DONE
        self.jobs[job.job_id] = job
        for pid in job.pids:
            pcb = self.tasks.get(pid)
            if pcb is not None:
                pcb.job_id = job.job_id
        return job

# Return one job by ID, or None.
    def get_job(self, job_id: int) -> Optional[Job]:
        return self.jobs.get(job_id)

# Return every known job.
    def list_jobs(self) -> List[Job]:
        self._refresh_job_states()
        return [self.jobs[j] for j in sorted(self.jobs)]

# Recompute each job's state from whether any of its PIDs are still alive.
    def _refresh_job_states(self) -> None:
        for job in self.jobs.values():
            live = [self.tasks[p] for p in job.pids
                    if p in self.tasks and self.tasks[p].state == TASK_RUNNING]
            stopped = [self.tasks[p] for p in job.pids
                       if p in self.tasks and self.tasks[p].state == TASK_STOPPED]
            if stopped and not live:
                job.state = TASK_STOPPED
            elif live:
                job.state = TASK_RUNNING
            else:
                job.state = DONE

# Record a PID as the most recent background job, which is what $! reports.
    def mark_last_bg(self, pid: int) -> None:
        self.last_bg_pid = pid

# -- scheduling driver ------------------------------------------------------

# Advance the scheduler by a delta and return the current task.
    def sched_tick(self, delta_ms: float = 1.0) -> Optional[PCB]:
        return self.rq.tick(delta_ms)

# Return the task the run queue would schedule next.
    def pick_next(self) -> Optional[PCB]:
        return self.rq.pick_next()

# Advance virtual time and return the milliseconds granted per PID, for teaching and tests.
    def run_virtual(self, total_ms: float, tick_ms: float = 1.0) -> Dict[int, float]:
        got: Dict[int, float] = {}
        t = 0.0
        while t < total_ms - 1e-9:
            cur = self.rq.tick(min(tick_ms, total_ms - t))
            if cur is None:
                break
            got[cur.pid] = got.get(cur.pid, 0.0) + min(tick_ms, total_ms - t)
            t += tick_ms
        return got

# -- queries ----------------------------------------------------------------

# List processes, optionally including retired ones.
    def list_procs(self, include_done: bool = False) -> List[PCB]:
        rows = sorted(self.tasks.values(), key=lambda p: p.pid)
        if include_done:
            return rows
        return [p for p in rows
                if p.state in (TASK_RUNNING, TASK_STOPPED, TASK_INTERRUPTIBLE)
                or p.remote and p.state not in TERMINAL_STATES]

# Return one PCB by PID.
    def get(self, pid: int) -> Optional[PCB]:
        return self.tasks.get(pid)

# Change a task's nice value and weight.
    def set_nice(self, pid: int, nice: int) -> bool:
        pcb = self.tasks.get(pid)
        if pcb is None or pcb.state != TASK_RUNNING:
            return False
        self.rq.dequeue(pcb)
        pcb.nice = max(-20, min(19, int(nice)))
        pcb.static_prio = 100 + pcb.nice + 20
        pcb.weight = nice_to_weight(pcb.nice)
        pcb.deadline = pcb.vruntime + self.rq._vslice(pcb)
        self.rq.enqueue(pcb)
        return True

# Clear the process table and job list.
    def reset(self) -> None:
        self.tasks.clear()
        self.handles.clear()
        self.jobs.clear()
        self._job_seq = itertools.count(1)
        self.last_bg_pid = None
        self._remote_signal_backend = None
        avg_w = self.rq
        self.rq = EEVDFRunQueue(base_slice=avg_w.base_slice,
                                min_slice=avg_w.min_slice)


# the global process table, the teaching stand-in for the kernel's init_task plus global run queues
_pt = ProcessTable()


# Return the module-level process table singleton.
def _table() -> ProcessTable:
    return _pt


# Register idle(0), init(1) and shell(2) so ps works before any command; idempotent.
def boot_system() -> Dict[str, PCB]:
    return _pt.boot_system()


# Report whether the process tree has been created.
def is_booted() -> bool:
    return _pt.is_booted()


# Install the callback that delivers signals to host processes.
def set_remote_signal_backend(fn) -> None:
    _pt.set_remote_signal_backend(fn)


# Register a job with its PIDs and return the Job record.
def new_job(cmdline: str, pids: Optional[List[int]] = None,
            background: bool = True) -> Job:
    return _pt.new_job(cmdline, pids, background)


# Return every known job.
def list_jobs() -> List[Job]:
    return _pt.list_jobs()


# Return one job by ID, or None.
def get_job(job_id: int) -> Optional[Job]:
    return _pt.get_job(job_id)


# Reap a parent's zombie children and return their PCBs.
def reap_children(ppid: int) -> List[PCB]:
    return _pt.reap_children(ppid)


# Return the shell PID, or 0 before boot.
def current_shell_pid() -> int:
    return _pt.current_shell_pid()


# Re-parent the children of a dead PID to init.
def adopt_orphans(dead_pid: int) -> List[PCB]:
    return _pt.adopt_orphans(dead_pid)


# Block until a PID reaches a terminal state.
def wait_for(pid: int, timeout: Optional[float] = 30.0) -> Optional[PCB]:
    return _pt.wait_for(pid, timeout)


# Return the most recent background PID, which is what $! expands to.
def last_bg_pid() -> Optional[int]:
    return _pt.last_bg_pid


# ---- module-level convenience API, called straight from the shell ----

# Create a PCB and optionally enqueue it.
def spawn(cmd: str, kind: str = "app", nice: int = 0, note: str = "",
          remote: bool = False, pgrp: int = 0, enqueue_rq: bool = True,
          ppid: int = 0) -> PCB:
    return _pt.spawn(comm=cmd, kind=kind, nice=nice, note=note,
                     remote=remote, pgrp=pgrp, enqueue_rq=enqueue_rq, ppid=ppid)


# Create a child PCB of the current shell with scheduler defaults.
def fork_task(comm: str, **kw) -> PCB:
    return _pt.spawn(comm=comm, **kw)


# Retire a task as done or failed and free its PID.
def finish(pid: int, exit_code: int = 0, failed: bool = False) -> Optional[PCB]:
    state = FAILED if failed else DONE
    return _pt.exit_task(pid, exit_code=exit_code, state=state)


# Retire a task into an explicit state; Zombie means not yet reaped.
def exit_task(pid: int, exit_code: int = 0,
              state: str = EXIT_ZOMBIE) -> Optional[PCB]:
    return _pt.exit_task(pid, exit_code=exit_code, state=state)


# Settle CPU time for a real child and move it to Zombie.
def child_exited(pid: int, exit_code: int = 0,
                 wall_ms: float = 0.0) -> Optional[PCB]:
    return _pt.child_exited(pid, exit_code=exit_code, wall_ms=wall_ms)


# Deliver a signal to a simulated or host process.
def send_signal(pid: int, signum: int) -> Tuple[bool, str]:
    return _pt.send_signal(pid, signum)


# List processes, optionally including retired ones.
def list_procs(include_done: bool = False) -> List[PCB]:
    return _pt.list_procs(include_done=include_done)


# Return one PCB by PID.
def get(pid: int) -> Optional[PCB]:
    return _pt.get(pid)


# Clear the process table and job list.
def reset() -> None:
    _pt.reset()


# Advance the scheduler by a delta and return the current task.
def sched_tick(delta_ms: float = 1.0) -> Optional[PCB]:
    return _pt.sched_tick(delta_ms)


# Return the task the run queue would schedule next.
def pick_next() -> Optional[PCB]:
    return _pt.pick_next()


# Change a task's nice value and weight.
def set_nice(pid: int, nice: int) -> bool:
    return _pt.set_nice(pid, nice)


# Return the run queue's weighted average virtual runtime.
def avg_vruntime() -> float:
    return _pt.rq.avg_vruntime()


# Move a task out of the runnable set into a blocked state.
def block(pid: int, state: str = TASK_INTERRUPTIBLE) -> bool:
    return _pt.block(pid, state)


# Move a blocked task back into the runnable set.
def unblock(pid: int) -> bool:
    return _pt.unblock(pid)
