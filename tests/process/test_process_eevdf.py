'''
 *
 *      test_process_eevdf.py
 *      EEVDF scheduler: fairness, nice weighting and the signal state machine.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import sys

import process as P
import proc


# Start each test from an empty process table.
def setup_function(_):
    P.reset()


# Equal nice values must yield near-equal CPU time, with no starvation.
def test_equal_nice_shares_cpu_fairly():
    P.spawn("task-a")
    P.spawn("task-b")
    P.spawn("task-c")
    got = P._table().run_virtual(60.0, 1.0)
    vals = list(got.values())
    assert max(vals) - min(vals) < 8.0


# CPU share has to follow the nice weight, in nice order.
def test_weighted_shares_follow_nice():
    hi = P.spawn("hi", nice=-10)
    mid = P.spawn("mid", nice=0)
    lo = P.spawn("lo", nice=10)
    got = P._table().run_virtual(120.0, 1.0)
    assert got[hi.pid] > got[mid.pid] > got[lo.pid]


# With equal weights the earliest virtual deadline wins, so the first spawned task runs first.
def test_pick_earliest_deadline():
    P.spawn("t1")
    P.spawn("t2")
    P._table().rq.tick(0.0)
    cur = P._table().rq.curr
    assert cur is not None and cur.comm == "t1"


# SIGSTOP and SIGCONT flip stopped and running, SIGTERM lands in Killed, and signal names resolve with or without the sig prefix.
def test_signal_state_machine():
    t1 = P.spawn("t1")
    t2 = P.spawn("t2")
    ok, _ = P.send_signal(t1.pid, P.SIGSTOP)
    assert ok and P.get(t1.pid).state == P.TASK_STOPPED
    ok, _ = P.send_signal(t1.pid, P.SIGCONT)
    assert ok and P.get(t1.pid).state == P.TASK_RUNNING
    ok, _ = P.send_signal(t2.pid, P.SIGTERM)
    assert ok and P.get(t2.pid).state == "Killed"
    assert P.parse_signal("sigkill") == 9
    assert P.parse_signal("USR1") == 10


# The old proc.py shim API still spawns, resolves and lists finished tasks.
def test_proc_shim_compat():
    p = proc.spawn("compat", kind="app")
    assert proc.get(p.pid).cmd == "compat"
    proc.finish(p.pid, 0)
    assert any(t.pid == p.pid for t in proc.list_procs(include_done=True))


# A task that spends its slice gets a later deadline, or it would keep winning the runqueue.
def test_deadline_advances_after_slice():
    P.spawn("solo")
    rq = P._table().rq
    rq.tick(0.0)
    cur = rq.curr
    d0 = cur.deadline
    rq.tick(cur.slice + 1.0)
    assert cur.deadline > d0


# Boot leaves the shell scheduled rather than parked beside the queue: it is the
# task holding the CPU, so there is a real curr to report and anything started
# later has something to contend with.
def test_boot_puts_the_shell_on_the_cpu():
    P.boot_system()
    table = P._table()
    assert table.rq.curr is P.get(P.PID_SHELL)
    assert table.rq.nr_running() == 1


# nr_running counts the task holding the CPU, the way Linux's counter does. The
# queued dict alone excludes curr, so reporting its size would read as an idle
# system while a task is running.
def test_nr_running_counts_the_current_task():
    P.boot_system()
    table = P._table()
    assert table.rq.nr_running() == 1              # the shell, as curr
    P.spawn("worker")
    assert table.rq.nr_running() == 2              # worker queued, shell still curr
    P.block(P.PID_SHELL)
    assert table.rq.nr_running() == 1


# Every task the table calls Running is on the run queue or holding the CPU. The
# shell is the case that used to break this invariant, and a caller that trusted
# the bare state reported it as owed every millisecond the queue had advanced.
def test_running_tasks_are_always_contending():
    P.boot_system()
    table = P._table()
    worker = P.spawn("worker")
    for pcb in (P.get(P.PID_SHELL), worker):
        assert pcb.state == P.TASK_RUNNING
        assert table.rq.contending(pcb) is True
    P.block(worker.pid)
    assert worker.state != P.TASK_RUNNING
    assert table.rq.contending(worker) is False


# Parking the shell hands the CPU to whatever is queued, which is what makes
# prompt idle-time accrue to a simulated task instead of to the shell.
def test_parking_the_shell_hands_the_cpu_to_a_queued_task():
    P.boot_system()
    table = P._table()
    worker = P.spawn("worker")
    P.block(P.PID_SHELL)
    for _ in range(4):
        P.sched_tick(4.0)
    assert table.rq.curr is worker
    assert worker.vruntime > 0.0 and worker.sum_exec_runtime > 0.0


# The snapshot reports lag only for tasks actually competing, measured against
# the same average it reports.
def test_snapshot_reports_lag_only_for_contending_tasks():
    P.boot_system()
    table = P._table()
    worker = P.spawn("worker")
    P.block(P.PID_SHELL)
    for _ in range(4):
        P.sched_tick(4.0)

    snap = table.snapshot()
    row = next(t for t in snap["tasks"] if t["pid"] == worker.pid)
    assert row["lag"] is not None
    assert abs((snap["rq"]["avg"] - row["vruntime"]) - row["lag"]) < 1e-6

    P.block(worker.pid)
    row = next(t for t in table.snapshot()["tasks"] if t["pid"] == worker.pid)
    assert row["lag"] is None and row["eligible"] is None
