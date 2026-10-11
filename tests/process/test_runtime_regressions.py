"""Accounting invariants and event-driven process lifecycle regressions."""

import math
import random
import threading

import pytest

import process as p


def assert_accounting(rq):
    queued = list(rq._queued.values())
    assert rq._queued_weight == sum(task.weight for task in queued)
    if rq.curr is not None:
        queued.append(rq.curr)
    if queued:
        expected = rq.min_vruntime + sum(
            task.weight * (task.vruntime - rq.min_vruntime) for task in queued
        ) / sum(task.weight for task in queued)
        assert math.isclose(rq.avg_vruntime(), expected, abs_tol=1e-7)
    eligible = [task for task in rq._queued.values()
                if task.vruntime <= rq.avg_vruntime() + 1e-9]
    candidates = eligible or list(rq._queued.values())
    expected = min(candidates, key=lambda task: (task.deadline, task.vruntime, task.pid),
                   default=None)
    assert rq.pick_next() is expected


def test_cached_accounting_survives_wakeup_stop_exit_and_nice_changes():
    table = p.ProcessTable()
    tasks = [table.spawn(f"task-{i}", nice=(i % 20) - 10) for i in range(32)]
    randomizer = random.Random(42)
    previous_min = 0
    for i in range(1200):
        task = randomizer.choice(tasks)
        if i % 17 == 0:
            table.set_nice(task.pid, randomizer.randrange(-20, 20))
        if i % 23 == 0:
            table.block(task.pid)
        if i % 29 == 0:
            table.unblock(task.pid)
        if i % 47 == 0:
            table.send_signal(task.pid, p.SIGSTOP)
        if i % 53 == 0:
            table.send_signal(task.pid, p.SIGCONT)
        if i % 31 == 0:
            table.charge_task(task.pid, 2.5)
        if i % 101 == 0:
            table.exit_task(task.pid)
        table.sched_tick(0.5)
        assert table.rq.min_vruntime >= previous_min
        previous_min = table.rq.min_vruntime
        assert_accounting(table.rq)
        if i % 50 == 0:
            table.rq._deadlines.check()


def test_duplicate_enqueue_and_pid_reuse_do_not_duplicate_weight_or_minimum():
    rq = p.EEVDFRunQueue()
    old = p.PCB(pid=3, comm="old", vruntime=10)
    rq.enqueue(old)
    rq.enqueue(old)
    assert rq._queued_weight == old.weight
    rq.dequeue(old)
    new = p.PCB(pid=3, comm="new", vruntime=100)
    rq.enqueue(new)
    rq._update_min_vruntime()
    assert rq.min_vruntime == 100
    assert_accounting(rq)


def test_history_and_lazy_heap_stay_bounded_during_long_runs():
    rq = p.EEVDFRunQueue()
    rq.enqueue(p.PCB(pid=3, comm="solo"))
    for _ in range(30000):
        rq.tick(10)
    assert len(rq.timeline) == rq.timeline.maxlen == 2048
    assert len(rq._heap) <= 2 * len(rq._queued) + 64


@pytest.mark.parametrize("change", ["exit", "reap", "reset"])
def test_process_state_change_wakes_an_unbounded_waiter(change, monkeypatch):
    table = p.ProcessTable()
    task = table.spawn("waiter")
    waiting = threading.Event()
    original_wait = table._state_changed.wait

    def observe_wait(timeout=None):
        waiting.set()
        return original_wait(timeout)

    monkeypatch.setattr(table._state_changed, "wait", observe_wait)
    result = []
    thread = threading.Thread(target=lambda: result.append(table.wait_for(task.pid, None)),
                              daemon=True)
    thread.start()
    assert waiting.wait(2)
    if change == "exit":
        table.exit_task(task.pid, 7)
    elif change == "reap":
        table.reap(task.pid)
    else:
        table.reset()
    thread.join(2)
    assert not thread.is_alive()
    assert result == ([task] if change == "exit" else [None])


def test_zero_timeout_returns_live_task_and_missing_pid_returns_none():
    table = p.ProcessTable()
    task = table.spawn("running")
    assert table.wait_for(task.pid, 0) is task
    assert table.wait_for(99999, None) is None


# Measured wall time lands on CPU and vruntime through the fair scaling.
def test_charge_task_books_cpu_and_vruntime():
    table = p.ProcessTable()
    task = table.spawn("charged", nice=0)
    table.charge_task(task.pid, 10.0)
    assert task.sum_exec_runtime == 10.0
    assert task.vruntime == p.EEVDFRunQueue.calc_delta_fair(10.0, task.weight)
    table.charge_task(task.pid, 0.0)
    table.charge_task(99999, 5.0)
    assert task.sum_exec_runtime == 10.0


# Reaping records the final accounting in a bounded recent ring.
def test_reap_records_recent_ring_bounded():
    table = p.ProcessTable()
    for i in range(20):
        task = table.spawn(f"job-{i}")
        table.charge_task(task.pid, float(i))
        table.exit_task(task.pid, exit_code=i)
        table.reap(task.pid)
    assert len(table.recent) == table.recent.maxlen == 16
    kept = list(table.recent)
    assert kept[0]["comm"] == "job-4" and kept[-1]["comm"] == "job-19"
    assert kept[-1]["exit"] == 19 and kept[-1]["cpu"] == 19.0
    assert set(kept[0]) >= {"pid", "comm", "exit", "sig", "cpu", "vruntime",
                            "kind"}
    table.reset()
    assert len(table.recent) == 0


# The interactive loop advances virtual time, so queued simulated tasks
# accrue vruntime in production instead of only under tests.
def test_command_loop_ticks_scheduler(monkeypatch):
    import kernel
    kernel.start_shell_session()
    table = p.ProcessTable()
    table.boot_system()
    task = table.spawn("simmer")
    monkeypatch.setattr("process._pt", table)
    calls = []
    script = iter(["", "", EOFError()])

    def fake_input(_prompt):
        calls.append("input")
        value = next(script)
        if isinstance(value, BaseException):
            raise value
        return value

    monkeypatch.setattr(kernel, "print_prompt", lambda: "test> ")
    monkeypatch.setattr("builtins.input", fake_input)
    monkeypatch.setattr(kernel.main, "handle_command", lambda _line: None)
    kernel._command_loop()
    assert len(calls) == 3
    assert task.vruntime > 0.0
    assert task.sum_exec_runtime > 0.0
    assert table.rq.nr_ticks >= 2
    kernel.start_shell_session()


# Two equal-weight tasks split the base slice: the incoming task's own share
# counts, so each gets half instead of a whole base slice.
def test_switch_slice_counts_incoming_task_weight():
    rq = p.EEVDFRunQueue()
    first = p.PCB(pid=1, comm="first")
    second = p.PCB(pid=2, comm="second")
    rq.enqueue(first)
    rq.enqueue(second)
    rq._switch_to(rq.pick_next())
    assert rq.curr.slice == pytest.approx(rq.base_slice / 2)
    rq.tick(rq.curr.slice + 1)
    assert rq.curr.slice == pytest.approx(rq.base_slice / 2)
    assert_accounting(rq)


# A signal to an already-terminated task is refused, including the Killed
# state that exit_task leaves behind.
def test_signal_to_terminated_task_is_refused():
    table = p.ProcessTable()
    task = table.spawn("victim")
    ok, _ = table.send_signal(task.pid, p.SIGKILL)
    assert ok is True
    assert task.state == "Killed"
    ok, message = table.send_signal(task.pid, p.SIGKILL)
    assert ok is False
    assert "已结束" in message
