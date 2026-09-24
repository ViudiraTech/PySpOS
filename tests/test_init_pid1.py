"""进程树/PID1 语义：idle/init/shell、孤儿收养、僵尸回收、后台作业。"""
import time

import process as P


def setup_function(_):
    P.reset()


def test_boot_system_creates_linux_like_top():
    nodes = P.boot_system()
    assert nodes["idle"].pid == 0 and nodes["idle"].comm == "swapper/0"
    assert nodes["init"].pid == 1 and nodes["init"].kind == "init"
    assert nodes["shell"].pid == 2 and nodes["shell"].ppid == 1
    assert P.is_booted() is True
    # 保留 PID 不会被普通 spawn 复用
    p = P.spawn("first-app")
    assert p.pid >= 3
    assert P.get(0) is not None and P.get(1) is not None


def test_boot_system_idempotent():
    a = P.boot_system()
    b = P.boot_system()
    assert a["init"] is b["init"]


def test_remote_task_not_in_eevdf_runqueue():
    p = P.spawn("remote", remote=True)
    assert p.remote is True
    assert p.pid not in P._table().rq._queued
    sim = P.spawn("simulated", remote=False)
    assert sim.pid in P._table().rq._queued


def test_orphan_adoption_to_init():
    P.boot_system()
    parent = P.spawn("parent")
    child = P.spawn("child", ppid=parent.pid)
    P.finish(parent.pid, 0)
    assert P.get(child.pid).ppid == P.PID_INIT


def test_zombie_child_reaped_by_parent_wait():
    P.boot_system()
    parent = P.spawn("parent")
    child = P.spawn("child", ppid=parent.pid)
    P.exit_task(child.pid, 3, state=P.EXIT_ZOMBIE)   # wait() 语义：退出但未回收
    assert P.get(child.pid).state == P.EXIT_ZOMBIE
    assert P.get(child.pid).exit_code == 3
    reaped = P.reap_children(parent.pid)
    assert [r.pid for r in reaped] == [child.pid]
    assert P.get(child.pid) is None


def test_adopted_zombie_reaped_immediately():
    P.boot_system()
    parent = P.spawn("parent")
    child = P.spawn("child", ppid=parent.pid)
    P.finish(child.pid, 0)          # 先成僵尸
    P.finish(parent.pid, 0)         # 父亡 → 收养并当场回收
    assert P.get(child.pid) is None


def test_job_table_lifecycle():
    P.boot_system()
    p = P.spawn("bg-app", remote=True)
    job = P.new_job("bg-app", pids=[p.pid])
    P._table().mark_last_bg(p.pid)
    assert P.last_bg_pid() == p.pid
    assert [j.job_id for j in P.list_jobs()] == [job.job_id]
    P.finish(p.pid, 0)
    assert P.list_jobs()[0].state == P.DONE


def test_process_group_defaults():
    P.boot_system()
    p = P.spawn("x")
    assert p.pgrp == p.pid
    assert p.session == P.PID_SHELL
    q = P.spawn("y", pgrp=4242)
    assert q.pgrp == 4242
