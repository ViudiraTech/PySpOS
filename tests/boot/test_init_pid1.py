'''
 *
 *      test_init_pid1.py
 *      Process tree and PID 1 semantics: idle/init/shell, orphan adoption, zombie reaping, job table.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import time

import process as P


# Start each test from an unbooted, empty process table.
def setup_function(_):
    P.reset()


# Boot builds the idle/init/shell triple at the Linux pids, marks the device booted, and never reuses a reserved pid.
def test_boot_system_creates_linux_like_top():
    nodes = P.boot_system()
    assert nodes["idle"].pid == 0 and nodes["idle"].comm == "swapper/0"
    assert nodes["init"].pid == 1 and nodes["init"].kind == "init"
    assert nodes["shell"].pid == 2 and nodes["shell"].ppid == 1
    assert P.is_booted() is True
    # A reserved pid is never handed out again by an ordinary spawn
    p = P.spawn("first-app")
    assert p.pid >= 3
    assert P.get(0) is not None and P.get(1) is not None


# Booting twice must hand back the same init node, not a second one.
def test_boot_system_idempotent():
    a = P.boot_system()
    b = P.boot_system()
    assert a["init"] is b["init"]


# A remote (real) child is not locally schedulable, while a simulated task is queued.
def test_remote_task_not_in_eevdf_runqueue():
    p = P.spawn("remote", remote=True)
    assert p.remote is True
    assert p.pid not in P._table().rq._queued
    sim = P.spawn("simulated", remote=False)
    assert sim.pid in P._table().rq._queued


# When a parent dies, its children are reparented to PID_INIT.
def test_orphan_adoption_to_init():
    P.boot_system()
    parent = P.spawn("parent")
    child = P.spawn("child", ppid=parent.pid)
    P.finish(parent.pid, 0)
    assert P.get(child.pid).ppid == P.PID_INIT


# wait() semantics: an exited but unreaped child stays a zombie until its parent reaps it, then disappears.
def test_zombie_child_reaped_by_parent_wait():
    P.boot_system()
    parent = P.spawn("parent")
    child = P.spawn("child", ppid=parent.pid)
    P.exit_task(child.pid, 3, state=P.EXIT_ZOMBIE)   # wait() semantics: exited but not yet reaped
    assert P.get(child.pid).state == P.EXIT_ZOMBIE
    assert P.get(child.pid).exit_code == 3
    reaped = P.reap_children(parent.pid)
    assert [r.pid for r in reaped] == [child.pid]
    assert P.get(child.pid) is None


# A child already a zombie when its parent dies is reaped at adoption, with no wait() needed.
def test_adopted_zombie_reaped_immediately():
    P.boot_system()
    parent = P.spawn("parent")
    child = P.spawn("child", ppid=parent.pid)
    P.finish(child.pid, 0)          # Become a zombie first
    P.finish(parent.pid, 0)         # Parent dies -> adopt and reap on the spot
    assert P.get(child.pid) is None


# A job registers its pid, becomes the last background job, and reports Done once its task finishes.
def test_job_table_lifecycle():
    P.boot_system()
    p = P.spawn("bg-app", remote=True)
    job = P.new_job("bg-app", pids=[p.pid])
    P._table().mark_last_bg(p.pid)
    assert P.last_bg_pid() == p.pid
    assert [j.job_id for j in P.list_jobs()] == [job.job_id]
    P.finish(p.pid, 0)
    assert P.list_jobs()[0].state == P.DONE


# A new task leads its own process group and joins the shell's session, unless a group is given.
def test_process_group_defaults():
    P.boot_system()
    p = P.spawn("x")
    assert p.pgrp == p.pid
    assert p.session == P.PID_SHELL
    q = P.spawn("y", pgrp=4242)
    assert q.pgrp == 4242
