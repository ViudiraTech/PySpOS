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

sys.path.insert(0, "src")
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
