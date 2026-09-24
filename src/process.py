#
#   process.py
#   PySpOS 模拟进程管理 + EEVDF 调度器
#
#   建模依据（Linux 6.6+ EEVDF，Peter Zijlstra 2023）：
#   - https://docs.kernel.org/scheduler/sched-eevdf.html
#   - Earliest Eligible Virtual Deadline First：每个可运行任务维护 vruntime；
#     运行 delta 时间后 vruntime += delta * NICE_0_LOAD / weight；
#     虚拟截止期 deadline = vruntime + slice；每次挑选“eligible（lag>=0，
#     即 vruntime <= avg_vruntime）任务中 deadline 最早者”，无 eligible
#     者时退化为全局最早 deadline；用完 slice（vruntime >= deadline）则
#     更新 deadline 并重排；短 slice 任务天然 deadline 更早，从而低延迟。
#   - 为教学实现做的简化（与内核差异处均有注释标明 SIMPLIFY）：
#     单 CPU、协作式 tick 驱动、无 cgroup、无 PELT 负载追踪、
#     睡眠任务 lag 衰减简化为唤醒时 vruntime 箝位到 min_vruntime、
#     切片保护简化为 min_slice 运行保护。
#
#   对外 API（shell / 测试使用）：
#     spawn / fork_task / exit_task / block / unblock /
#     send_signal / parse_signal / list_procs / get / reset /
#     sched_tick / pick_next / set_nice
#

import heapq
import itertools
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# --------------------------------------------------------------------------
# 常量：对齐内核语义（数值按教学可读性取用，单位：毫秒浮点）
# --------------------------------------------------------------------------

NICE_0_LOAD = 1024          # 内核 NICE_0_LOAD
PID_MAX = 32768             # 内核 PID_MAX_DEFAULT（简化版位图上限）

BASE_SLICE_MS = 6.0         # sysctl_sched_base_slice（内核默认约 3~6ms 量级）
MIN_SLICE_MS = 0.75         # 最小切片保护（内核 sysctl_sched_min_granularity 思想）
MAX_SLICE_MS = 24.0         # 单个 slice 上限，防止独占

# 内核 sched_prio_to_weight[40]（nice -20..19），照搬数值保证权重比真实。
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


def nice_to_weight(nice: int) -> int:
    nice = max(-20, min(19, int(nice)))
    return _SCHED_PRIO_TO_WEIGHT[nice + 20]


# --------------------------------------------------------------------------
# 信号（沿用 proc.py 的编号，保持 shell 命令兼容）
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


def parse_signal(text: str) -> Optional[int]:
    if text is None:
        return None
    return SIGNALS.get(str(text).strip().upper())


# --------------------------------------------------------------------------
# 任务状态（对齐 Linux task_state，另保留旧 proc.py 的英文名做兼容）
# --------------------------------------------------------------------------

TASK_RUNNING = "Running"            # TASK_RUNNING：可运行/运行中
TASK_INTERRUPTIBLE = "Sleeping"     # TASK_INTERRUPTIBLE：可中断睡眠
TASK_STOPPED = "Stopped"            # TASK_STOPPED：SIGSTOP 暂停
EXIT_ZOMBIE = "Zombie"              # EXIT_ZOMBIE：已退出待回收
EXIT_DEAD = "Dead"                  # EXIT_DEAD：已回收

# 旧 proc.py 状态名兼容
RUNNING = TASK_RUNNING
DONE = "Done"
FAILED = "Failed"
KILLED = "Killed"
STOPPED = TASK_STOPPED


@dataclass
class PCB:
    """进程控制块（对齐 Linux task_struct 的教学子集）。"""
    pid: int
    comm: str                       # 任务名（Linux task_struct.comm）
    state: str = TASK_RUNNING
    ppid: int = 0
    nice: int = 0
    static_prio: int = 120          # 内核 static_prio = MAX_RT_PRIO(100) + nice + 20
    weight: int = NICE_0_LOAD
    vruntime: float = 0.0           # sched_entity.vruntime
    deadline: float = 0.0           # sched_entity.deadline（虚拟截止期）
    slice: float = BASE_SLICE_MS    # 本轮请求的时间片（真实时间 ms）
    sum_exec_runtime: float = 0.0   # se.sum_exec_runtime（累计真实运行 ms）
    nvcsw: int = 0                  # 自愿切换次数
    nivcsw: int = 0                 # 非自愿（被抢占）切换次数
    exit_code: int = 0
    signal: int = 0                 # 最后收到的致死信号
    pending: List[int] = field(default_factory=list)  # 待处理信号队列
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    kind: str = "app"               # app | elf | spf | shell | kthread
    note: str = ""
    cmd: str = ""                   # 旧 proc.py 兼容：完整命令行
    _gen: int = 0                   # runqueue 堆条目版本号（内部）

    def __post_init__(self):
        if not self.cmd:
            self.cmd = self.comm
        self.static_prio = 100 + self.nice + 20
        self.weight = nice_to_weight(self.nice)

    @property
    def lag(self) -> float:
        """lag 估算（相对 runqueue 均值由调度器计算；此处仅保留上次快照）。"""
        return getattr(self, "_lag_snapshot", 0.0)


# --------------------------------------------------------------------------
# PID 分配（Linux 位图思想的简化版：区间内顺序分配 + 回绕复用）
# --------------------------------------------------------------------------

class PidAllocator:
    def __init__(self, pid_max: int = PID_MAX):
        self.pid_max = pid_max
        self._used: set = set()
        self._next = 1

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

    def free(self, pid: int) -> None:
        self._used.discard(pid)

    def reset(self) -> None:
        self._used.clear()
        self._next = 1


# --------------------------------------------------------------------------
# EEVDF 运行队列（单 CPU，对应内核 struct cfs_rq 的 EEVDF 子集）
# --------------------------------------------------------------------------

class EEVDFRunQueue:
    def __init__(self, base_slice: float = BASE_SLICE_MS,
                 min_slice: float = MIN_SLICE_MS):
        self.base_slice = base_slice
        self.min_slice = min_slice
        self.min_vruntime = 0.0     # cfs_rq->min_vruntime（单调递增）
        self.curr: Optional[PCB] = None
        self._heap: list = []       # (deadline, vruntime, seq, pid)
        self._seq = itertools.count()
        self._queued: Dict[int, PCB] = {}   # pid -> pcb（在队可运行任务）
        self.nr_switches = 0
        self.timeline: List[Tuple[float, int, str]] = []  # (vtime, pid, event)

    # -- 入队/出队 --------------------------------------------------------

    def enqueue(self, pcb: PCB) -> None:
        # SIMPLIFY: place_entity 简化——唤醒任务 vruntime 箝位到 min_vruntime，
        # 保留“欠账者优先”，但不实现内核的 PLACE_LAG/vlag 衰减全套逻辑。
        if pcb.state == TASK_RUNNING:
            if pcb.vruntime < self.min_vruntime:
                pcb.vruntime = self.min_vruntime
            if pcb.deadline <= pcb.vruntime:
                pcb.deadline = pcb.vruntime + self._vslice(pcb)
            pcb._gen += 1
            self._queued[pcb.pid] = pcb
            heapq.heappush(self._heap,
                            (pcb.deadline, pcb.vruntime, next(self._seq), pcb.pid, pcb._gen))

    def dequeue(self, pcb: PCB) -> None:
        self._queued.pop(pcb.pid, None)   # 堆条目惰性失效（靠 _gen 识别）
        if self.curr is pcb:
            self.curr = None

    def _live_entry(self, pid: int, gen: int) -> Optional[PCB]:
        pcb = self._queued.get(pid)
        if pcb is None or pcb._gen != gen or pcb.state != TASK_RUNNING:
            return None
        return pcb

    # -- vruntime / deadline 核心公式 -------------------------------------

    @staticmethod
    def calc_delta_fair(delta_ms: float, weight: int) -> float:
        """内核 calc_delta_fair：delta_exec * NICE_0_LOAD / weight。"""
        return delta_ms * NICE_0_LOAD / max(1, weight)

    def _total_weight(self) -> int:
        w = sum(p.weight for p in self._queued.values())
        if self.curr is not None and self.curr.pid not in self._queued:
            w += self.curr.weight
        return max(1, w)

    def _vslice(self, pcb: PCB) -> float:
        """虚拟切片 = 真实 slice 经权重归一（deadline 推进量）。"""
        return self.calc_delta_fair(pcb.slice, pcb.weight)

    def avg_vruntime(self) -> float:
        """内核 avg_vruntime 加权平均思想：min_vruntime + Σw(v-min)/Σw。"""
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

    def _update_min_vruntime(self) -> None:
        cands = [p.vruntime for p in self._queued.values()
                 if p.state == TASK_RUNNING]
        if self.curr is not None and self.curr.state == TASK_RUNNING:
            cands.append(self.curr.vruntime)
        if cands:
            m = min(cands)
            if m > self.min_vruntime:
                self.min_vruntime = m

    def eligible(self, pcb: PCB) -> bool:
        """eligible <=> lag >= 0 <=> vruntime <= avg_vruntime。"""
        return pcb.vruntime <= self.avg_vruntime() + 1e-9

    # -- 选任务：pick_eevdf ----------------------------------------------

    def pick_next(self) -> Optional[PCB]:
        avg = self.avg_vruntime()
        best = None
        best_key = None
        fallback = None
        fallback_key = None
        # 堆顶可能过期，弹出失效条目后扫描（任务数小，直接全量扫描更稳）。
        cands = [p for p in self._queued.values() if p.state == TASK_RUNNING]
        for p in cands:
            key = (p.deadline, p.vruntime, p.pid)
            if p.vruntime <= avg + 1e-9:      # eligible
                if best_key is None or key < best_key:
                    best, best_key = p, key
            if fallback_key is None or key < fallback_key:
                fallback, fallback_key = p, key
        return best if best is not None else fallback

    # -- 切片分配 ----------------------------------------------------------

    def assign_slice(self, pcb: PCB) -> None:
        """sched_slice 思想：slice = base * w / total，箝位 [min, max]。"""
        total = self._total_weight()
        s = self.base_slice * pcb.weight / total
        pcb.slice = max(self.min_slice, min(MAX_SLICE_MS, s))
        pcb.deadline = pcb.vruntime + self._vslice(pcb)

    # -- tick：update_curr + 调度 ------------------------------------------

    def tick(self, delta_ms: float) -> Optional[PCB]:
        """推进当前任务 delta_ms，必要时重调度；返回调度后的 current。"""
        if self.curr is None or self.curr.state != TASK_RUNNING:
            nxt = self.pick_next()
            self._switch_to(nxt)
            return self.curr
        cur = self.curr
        # update_curr：vruntime 推进
        cur.sum_exec_runtime += delta_ms
        cur.vruntime += self.calc_delta_fair(delta_ms, cur.weight)
        self._update_min_vruntime()
        # slice 用尽（vruntime 越过 deadline）→ 更新 deadline 并重选
        if cur.vruntime >= cur.deadline - 1e-9:
            self._requeue_current()
            nxt = self.pick_next()
            self._switch_to(nxt)
        else:
            # 抢占检查：存在 eligible 且 deadline 更早的任务 → 抢占当前任务。
            # （内核 wakeup_preempt + RUN_TO_PARITY 切片保护的教学简化：
            #  保护收敛为 min_slice 运行保护，由 assign_slice 保证 slice 下限。）
            r = self._preempt_candidate(cur)
            if r is not None:
                self._requeue_current(preempted=True)
                self._switch_to(r)
        return self.curr

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

    def _requeue_current(self, preempted: bool = False) -> None:
        cur = self.curr
        if cur is None:
            return
        if preempted:
            cur.nivcsw += 1
        else:
            cur.nvcsw += 1
        if cur.state == TASK_RUNNING:
            # update_deadline：deadline 已越过则顺延一个 vslice
            if cur.vruntime >= cur.deadline - 1e-9:
                cur.deadline = cur.vruntime + self._vslice(cur)
            cur._gen += 1
            self._queued[cur.pid] = cur
            heapq.heappush(self._heap,
                            (cur.deadline, cur.vruntime, next(self._seq), cur.pid, cur._gen))
        self.curr = None

    def _switch_to(self, nxt: Optional[PCB]) -> None:
        if nxt is None:
            self.curr = None
            return
        self.dequeue(nxt)          # 从就绪队取出（curr 不在队里）
        self.assign_slice(nxt)
        self.curr = nxt
        self.nr_switches += 1
        self.timeline.append((self.min_vruntime, nxt.pid, f"switch-to deadline={nxt.deadline:.3f}"))


# --------------------------------------------------------------------------
# 进程表（全局单例思想，对应内核 pid 哈希 + 全局 runqueue）
# --------------------------------------------------------------------------

class ProcessTable:
    def __init__(self):
        self.pids = PidAllocator()
        self.tasks: Dict[int, PCB] = {}
        self.rq = EEVDFRunQueue()

    # -- 创建 / 退出 ------------------------------------------------------

    def spawn(self, comm: str, kind: str = "app", nice: int = 0,
              ppid: int = 0, note: str = "") -> PCB:
        pid = self.pids.alloc()
        pcb = PCB(pid=pid, comm=comm, kind=kind, nice=nice, ppid=ppid,
                  note=note, cmd=comm)
        self.tasks[pid] = pcb
        self.rq.enqueue(pcb)
        return pcb

    fork_task = spawn  # 别名：教学上 fork ≈ spawn

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
            # 兼容旧 proc.py 的结束态命名
            pass
        return pcb

    def reap(self, pid: int) -> Optional[PCB]:
        """回收 ZOMBIE → 释放 pid（对应内核 release_task 简化）。"""
        pcb = self.tasks.get(pid)
        if pcb is None:
            return None
        pcb.state = EXIT_DEAD
        self.rq.dequeue(pcb)
        self.pids.free(pid)
        return self.tasks.pop(pid, None)

    # -- 睡眠 / 唤醒 -------------------------------------------------------

    def block(self, pid: int, state: str = TASK_INTERRUPTIBLE) -> bool:
        pcb = self.tasks.get(pid)
        if pcb is None or pcb.state != TASK_RUNNING:
            return False
        pcb.state = state
        pcb.nvcsw += 1
        self.rq.dequeue(pcb)
        return True

    def unblock(self, pid: int) -> bool:
        pcb = self.tasks.get(pid)
        if pcb is None or pcb.state not in (TASK_INTERRUPTIBLE, TASK_STOPPED):
            return False
        if pcb.state == TASK_STOPPED:
            return False  # STOP 只能由 SIGCONT 解除
        pcb.state = TASK_RUNNING
        self.rq.enqueue(pcb)
        # wakeup_preempt 简化：唤醒后若 deadline 更早则直接抢占
        cur = self.rq.curr
        if cur is not None and pcb.deadline < cur.deadline - 1e-9 \
                and self.rq.eligible(pcb):
            self.rq._requeue_current(preempted=True)
            self.rq._switch_to(pcb)
        return True

    # -- 信号 ---------------------------------------------------------------

    def send_signal(self, pid: int, signum: int) -> Tuple[bool, str]:
        pcb = self.tasks.get(pid)
        if pcb is None:
            return False, f"没有 PID 为 {pid} 的进程"
        if pcb.state in (DONE, FAILED, EXIT_ZOMBIE, EXIT_DEAD):
            return False, f"进程 {pid} 已结束（{pcb.state}），无法发信号"
        if signum in (SIGKILL, SIGTERM, SIGINT):
            pcb.signal = signum
            self.exit_task(pid, exit_code=128 + signum, state="Killed")
            return True, f"已向 {pid} 发送信号 {signum}，进程已终止"
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
        pcb.note = (pcb.note + f" [sig{signum}]").strip()
        return True, f"已向 {pid} 发送信号 {signum}"

    # -- 调度驱动 -------------------------------------------------------------

    def sched_tick(self, delta_ms: float = 1.0) -> Optional[PCB]:
        return self.rq.tick(delta_ms)

    def pick_next(self) -> Optional[PCB]:
        return self.rq.pick_next()

    def run_virtual(self, total_ms: float, tick_ms: float = 1.0) -> Dict[int, float]:
        """虚拟时间推进（教学/测试用）：返回 {pid: 分得的 ms}。"""
        got: Dict[int, float] = {}
        t = 0.0
        while t < total_ms - 1e-9:
            cur = self.rq.tick(min(tick_ms, total_ms - t))
            if cur is None:
                break
            got[cur.pid] = got.get(cur.pid, 0.0) + min(tick_ms, total_ms - t)
            t += tick_ms
        return got

    # -- 查询 ------------------------------------------------------------------

    def list_procs(self, include_done: bool = False) -> List[PCB]:
        rows = sorted(self.tasks.values(), key=lambda p: p.pid)
        if include_done:
            return rows
        return [p for p in rows
                if p.state in (TASK_RUNNING, TASK_STOPPED, TASK_INTERRUPTIBLE)]

    def get(self, pid: int) -> Optional[PCB]:
        return self.tasks.get(pid)

    def set_nice(self, pid: int, nice: int) -> bool:
        """renice：重算权重并重排 deadline（内核 reweight 简化）。"""
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

    def reset(self) -> None:
        self.tasks.clear()
        self.pids.reset()
        avg_w = self.rq
        self.rq = EEVDFRunQueue(base_slice=avg_w.base_slice,
                                min_slice=avg_w.min_slice)


# 全局进程表（内核 init_task + 全局 runqueue 的教学对应物）
_pt = ProcessTable()


def _table() -> ProcessTable:
    return _pt


# ---- 模块级便捷 API（shell 直接调用） ----

def spawn(cmd: str, kind: str = "app", nice: int = 0, note: str = "") -> PCB:
    return _pt.spawn(comm=cmd, kind=kind, nice=nice, note=note)


def fork_task(comm: str, **kw) -> PCB:
    return _pt.spawn(comm=comm, **kw)


def finish(pid: int, exit_code: int = 0, failed: bool = False) -> Optional[PCB]:
    state = FAILED if failed else DONE
    return _pt.exit_task(pid, exit_code=exit_code, state=state)


def send_signal(pid: int, signum: int) -> Tuple[bool, str]:
    return _pt.send_signal(pid, signum)


def list_procs(include_done: bool = False) -> List[PCB]:
    return _pt.list_procs(include_done=include_done)


def get(pid: int) -> Optional[PCB]:
    return _pt.get(pid)


def reset() -> None:
    _pt.reset()


def sched_tick(delta_ms: float = 1.0) -> Optional[PCB]:
    return _pt.sched_tick(delta_ms)


def pick_next() -> Optional[PCB]:
    return _pt.pick_next()


def set_nice(pid: int, nice: int) -> bool:
    return _pt.set_nice(pid, nice)


def avg_vruntime() -> float:
    return _pt.rq.avg_vruntime()


def block(pid: int, state: str = TASK_INTERRUPTIBLE) -> bool:
    return _pt.block(pid, state)


def unblock(pid: int) -> bool:
    return _pt.unblock(pid)
