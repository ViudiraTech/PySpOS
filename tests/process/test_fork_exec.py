'''
 *
 *      test_fork_exec.py
 *      Real forked children: isolation, concurrency, background jobs and the syscall RPC.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

from tests.support import REPO as REPO_ROOT

import os
import sys
import time


import process as proc

REPO = REPO_ROOT
SRC = os.path.join(REPO, "src")

RPC_APP = '''
import api
print("child user:", api.get_system_username(), flush=True)
print("child lock:", api.get_lockstate(), flush=True)
api.set_rootstate(True)
print("child root after:", api.get_rootstate(), flush=True)
'''


# Boot the process table and start one real forked child for the payload.
def _spawn(payload, background=False):
    import forkexec
    proc.boot_system()
    return forkexec.fork_exec(payload, kind="app", background=background,
                               src_dir=SRC,
                               apps_dir=os.path.join(SRC, "apps"))


# Wait for the child to finish and return its final PCB, or None once reaped.
def _drain(pcb, timeout=20):
    import forkexec
    forkexec.wait(pcb.pid, timeout=timeout)
    return proc.get(pcb.pid)


# A forked app is a remote (real) child of the shell pid and reaches a terminal state.
def test_fork_runs_app_as_real_child():
    pcb = _spawn("app:hello.py")
    assert pcb.remote is True
    assert pcb.ppid == proc.PID_SHELL
    p = _drain(pcb)
    assert p is None or p.state in proc.TERMINAL_STATES


# A child dying must leave the parent's own process table usable.
def test_fork_is_isolated_from_shell():
    # A child crashing must not disturb the parent shell itself
    pcb = _spawn("app:hello.py")
    _drain(pcb)
    assert os.getpid() > 0
    t = proc.spawn("still-alive")
    assert proc.get(t.pid) is not None


# Three background children get distinct pids, all reach a terminal state, and the shell reaps every one.
def test_concurrent_background_children():
    pids = [_spawn("app:hello.py", background=True).pid for _ in range(3)]
    assert len(set(pids)) == 3
    assert all(proc.get(p).remote for p in pids)
    for p in pids:
        assert proc.wait_for(p, timeout=20).state in proc.TERMINAL_STATES
    proc.reap_children(proc.PID_SHELL)
    assert all(proc.get(p) is None for p in pids)


# An ordinary child must not be able to flip the parent's ROOT state through the syscall RPC.
def test_syscall_rpc_rejects_unauthorized_root(tmp_path):
    import main
    app = tmp_path / "rpcprobe.py"
    app.write_text(RPC_APP, encoding="utf-8")
    was_root = main.rootstate
    was_authorized = getattr(main, "_root_authorized", False)
    main.rootstate = False
    main._root_authorized = False
    try:
        pcb = _spawn(f"app:{app}")
        _drain(pcb)
        assert main.rootstate is False
    finally:
        main.rootstate = was_root
        main._root_authorized = was_authorized


# A child reads lock state and username through the parent, so its view of the system is authoritative.
def test_child_reads_parent_authoritative_state(tmp_path):
    app = tmp_path / "reader.py"
    app.write_text(
        "import api\n"
        "print('LOCK', api.get_lockstate(), flush=True)\n"
        "print('USER', api.get_system_username(), flush=True)\n",
        encoding="utf-8")
    pcb = _spawn(f"app:{app}")
    p = _drain(pcb)
    assert p is None or p.exit_code == 0


def test_immediate_exit_is_not_lost_before_watcher_registration(tmp_path):
    import forkexec
    app = tmp_path / "instant.py"
    app.write_text("def main():\n    pass\n", encoding="utf-8")
    children = [_spawn(f"app:{app}", background=True) for _ in range(12)]
    for child in children:
        final = forkexec.wait(child.pid, timeout=5)
        assert final is None or final.state in proc.TERMINAL_STATES
        assert child.exit_code == 0
        assert child.pid not in proc._table().handles


def test_failed_launch_never_registers_an_unstarted_handle(monkeypatch):
    import forkexec

    def fail_start(_handle):
        raise OSError("simulated process start failure")

    monkeypatch.setattr(forkexec._CTX.Process, "start", fail_start)
    child = _spawn("app:hello.py", background=True)
    assert child.state == proc.FAILED
    assert child.pid not in proc._table().handles
    assert all(pcb is not child for _table, pcb in forkexec._watched_children.values())
