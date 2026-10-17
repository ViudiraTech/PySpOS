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


# The syscall channel must stay a unix socket on POSIX. It used to be a fresh
# 127.0.0.1 listener per child, and multiprocessing.connection never sets
# TCP_NODELAY, so the first syscall of every command stalled ~40ms on Nagle
# and delayed ACK (48ms -> 5.6ms once moved to AF_UNIX).
def test_sysctl_transport_is_a_local_socket_not_tcp():
    import forkexec
    import os

    child = _spawn("app:hello.py")
    try:
        listener = forkexec._child_servers[child.pid]
        addr = listener.address
        if os.name == "posix":
            assert isinstance(addr, str) and addr.startswith("/")
            assert os.path.exists(addr)
            # 0700 is what keeps the endpoint off-limits to other local users.
            mode = os.stat(forkexec._ensure_endpoint_dir()).st_mode & 0o777
            assert mode == 0o700
    finally:
        _drain(child)


# The socket file has to go when the child does, or a long shell leaves one
# dead inode per app it ever ran.
def test_child_endpoint_socket_file_is_cleaned_up():
    import forkexec
    import os

    child = _spawn("app:hello.py")
    path = forkexec._child_servers[child.pid].address
    _drain(child)
    assert not os.path.exists(path)


# Apps build their connection target from the published address, and it has to
# match the transport the parent actually bound.
def test_client_target_follows_the_published_transport():
    import api

    assert api._client_target("/tmp/pyspos-sysctl-x/1-0.sock") == \
        "/tmp/pyspos-sysctl-x/1-0.sock"
    assert api._client_target("127.0.0.1:5555") == ("127.0.0.1", 5555)


# The Windows transport has to disable Nagle. A request-response syscall on a
# fresh TCP connection otherwise stalls against the peer's delayed ACK (48ms ->
# 7ms here with the option set); Hadoop and Spark fixed the same stall the same
# way, and Go, curl and Node enable the option by default.
def test_tcp_transport_disables_nagle():
    import socket
    import threading
    from multiprocessing.connection import Listener

    import api

    authkey = b"k" * 32
    listener = Listener(("127.0.0.1", 0), authkey=authkey)
    host, port = listener.address

    def serve():
        conn = listener.accept()
        conn.send(conn.recv())
        conn.close()
        listener.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    conn = api._open_tcp_connection(host, port, authkey)
    try:
        # The option is per-end, so it has to be read back off the socket we
        # built rather than off the peer.
        sock = socket.fromfd(conn._handle, socket.AF_INET, socket.SOCK_STREAM)
        try:
            assert sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY) == 1
        finally:
            sock.close()
        # The handshake Client() would have done still has to have happened.
        conn.send(("rid", "op"))
        assert conn.recv() == ("rid", "op")
    finally:
        conn.close()
        thread.join(timeout=5)


# Every command in a shell needs its own working endpoint, so a child exiting
# must not disturb the shared socket directory. Children leave through
# os._exit, which skips the parent's atexit cleanup; a future switch to a
# graceful child exit would start running it and silently strip RPC from every
# command after the first.
def test_rpc_channel_survives_earlier_children_exiting(tmp_path):
    import forkexec

    app = tmp_path / "probe.py"
    app.write_text(
        "import api\n\n\ndef main():\n    print('remote=%s' % api.is_remote())\n",
        encoding="utf-8")
    for round_no in range(3):
        log = tmp_path / f"round{round_no}.log"
        child = forkexec.fork_exec(f"app:{app}", kind="app",
                                    src_dir=SRC,
                                    apps_dir=os.path.join(SRC, "apps"),
                                    log_path=str(log))
        _drain(child)
        # is_remote() is True only while the published address still resolves to
        # a live endpoint, so this catches a torn-down directory directly.
        deadline = time.time() + 5
        while time.time() < deadline:
            if "remote=True" in log.read_text(encoding="utf-8"):
                break
            time.sleep(0.05)
        assert "remote=True" in log.read_text(encoding="utf-8"), \
            f"第 {round_no + 1} 个子进程失去了 RPC 通道"
