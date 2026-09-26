'''
 *
 *      test_hostexec.py
 *      Host program execution: PATH lookup, foreground passthrough, background relay, signals and redirection.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import contextlib
import io
import os
import signal
import subprocess
import sys
import time

import pytest

sys.path.insert(0, "src")
import main
import proc
import process
from shell import dispatch, hostexec


IS_POSIX = os.name == "posix"
needs_posix = pytest.mark.skipif(not IS_POSIX, reason="需要 fork/exec")


# Run one shell command and capture what it printed.
def run(cmd):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main.handle_command(cmd)
    return buf.getvalue()


# Start each test from an empty process table.
def setup_function(_):
    proc.reset()


# Build a real host argv around this interpreter, so no fixture binary is needed.
def _py_writer(code="import sys;sys.stdout.buffer.write(b'out\\n')"):
    return [sys.executable, "-c", code]


# ---------- PATH lookup ----------

# An absolute path resolves to itself, while a missing file and an empty name both resolve to None.
def test_resolve_absolute_and_path(tmp_path):
    exe = tmp_path / "myprog"
    exe.write_text("#!/bin/sh\n", encoding="utf-8")
    exe.chmod(0o755)
    assert hostexec.resolve(str(exe)) == str(exe)
    assert hostexec.resolve(str(tmp_path / "nope")) is None
    assert hostexec.resolve("") is None


# PATH lookup finds an executable, rejects a non-executable file, and still reports the directory as a known command source.
def test_resolve_uses_path_and_rejects_dirs(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    exe = bindir / "greet"
    exe.write_text("#!/bin/sh\n", encoding="utf-8")
    exe.chmod(0o755)
    (bindir / "notexec").write_text("x", encoding="utf-8")
    monkeypatch.setenv("PATH", str(bindir))
    hostexec._PATH_BIN_CACHE = None
    try:
        assert hostexec.resolve("greet") == str(exe)
        assert hostexec.resolve("notexec") is None
        assert hostexec.resolve("missing-xyz") is None
        assert "greet" in hostexec.path_commands()
    finally:
        hostexec._PATH_BIN_CACHE = None


# ---------- foreground: a real process, vt100 bytes untouched ----------

# A foreground host program really runs, its bytes pass through untouched, and its PCB ends in Done.
@needs_posix
def test_foreground_exec_real_process(tmp_path):
    out = tmp_path / "o.bin"
    prog = [sys.executable, "-c",
            "import sys;sys.stdout.buffer.write(b'\\x1b[31mred\\x1b[0m\\n')"]
    r, w = os.pipe()
    hostexec.set_override(w)
    try:
        assert hostexec.run(prog, False) is True
    finally:
        hostexec.clear_override()
        os.close(w)
    with open(out, "wb") as f:
        pass
    data = b""
    while True:
        chunk = os.read(r, 65536)
        if not chunk:
            break
        data += chunk
    os.close(r)
    assert data == b"\x1b[31mred\x1b[0m\n"
    hosts = [p for p in proc.list_procs(include_done=True) if p.kind == "host"]
    assert hosts and all(p.state == "Done" for p in hosts)


# The parent's own SIGINT handler must survive running a foreground child.
@needs_posix
def test_parent_sigint_handler_restored():
    if os.name != "posix":
        pytest.skip("需要 POSIX 信号")
    sentinel = lambda *a: None  # noqa: E731
    old = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, sentinel)
    try:
        prog = [sys.executable, "-c", "pass"]
        assert hostexec.run(prog, False) is True
        assert signal.getsignal(signal.SIGINT) is sentinel
    finally:
        signal.signal(signal.SIGINT, old)


# An ignored disposition is turned into a catchable handler for the child and restored exactly afterwards.
@needs_posix
def test_make_catchable_roundtrip():
    old = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        saved = hostexec._make_catchable((signal.SIGINT,))
        assert saved == {signal.SIGINT: signal.SIG_IGN}
        assert signal.getsignal(signal.SIGINT) not in (
            signal.SIG_IGN, signal.SIG_DFL)
        hostexec._restore_signals(saved)
        assert signal.getsignal(signal.SIGINT) is signal.SIG_IGN
    finally:
        signal.signal(signal.SIGINT, old)


# The child must see the default SIGINT disposition, not the parent's ignored one.
@needs_posix
def test_spawned_child_gets_default_sigint():
    old = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        prog = [sys.executable, "-c",
                ("import signal;"
                 "print(signal.getsignal(signal.SIGINT) is signal.SIG_IGN)")]
        r, w = os.pipe()
        hostexec.set_override(w)
        try:
            assert hostexec.run(prog, False) is True
        finally:
            hostexec.clear_override()
            os.close(w)
        data = b""
        while True:
            chunk = os.read(r, 65536)
            if not chunk:
                break
            data += chunk
        os.close(r)
        assert data.strip() == b"False"
    finally:
        signal.signal(signal.SIGINT, old)


# ---------- dispatch: builtins first, 127 reserved ----------

# A builtin of the same name wins: echo must not exec the host binary even when one is resolvable.
def test_builtin_shadows_host(monkeypatch):
    called = []

# Popen stand-in that fails the test if a builtin ever reaches the host exec path.
    class Boom:
# Record the attempt and abort: no host spawn was expected here.
        def __init__(self, *a, **k):
            called.append((a, k))
            raise AssertionError("不应 spawn 宿主程序")

    monkeypatch.setattr(subprocess, "Popen", Boom)
    monkeypatch.setattr(hostexec, "resolve", lambda name: "/bin/echo")
    assert "hi" in run("echo hi")
    assert called == []


# An unresolvable command keeps the shell's own not-found wording and the reserved 127 status.
def test_unknown_still_127(monkeypatch):
    from shell import shexec
    monkeypatch.setattr(hostexec, "resolve", lambda name: None)
    out = run("definitely-not-a-command-xyz")
    assert "未找到命令" in out
    assert shexec.last_status() == 127


# ---------- redirection and pipes at the fd level ----------

# Redirecting a host program to a file keeps its escape bytes instead of stripping them.
@needs_posix
def test_redirect_host_keeps_vt100(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code = ("import sys;sys.stdout.buffer.write("
            f"'A\\n\\x1b[1mB\\x1b[0m\\n'.encode())")
    quoted = code.replace("'", "'\\''")
    run(f"{sys.executable} -c '{quoted}' > vt.txt")
    raw = (tmp_path / "vt.txt").read_bytes()
    assert raw == b"A\n\x1b[1mB\x1b[0m\n"


# A host producer piped into a builtin filter has to work at the fd level.
@needs_posix
def test_pipe_host_to_grep(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code = ("import sys;sys.stdout.write('foo\\nbar\\nfoobar\\n')")
    quoted = code.replace("'", "'\\''")
    out = run(f"{sys.executable} -c '{quoted}' | grep bar")
    assert "foobar" in out and "\nfoo\n" not in out


# ---------- background: job registration and a byte-exact relay ----------

# A background host job registers with the job table, becomes a zombie, and its bytes still reach the terminal.
@needs_posix
def test_background_registers_job_and_reaps(capfd):
    prog = [sys.executable, "-c",
            "import sys;sys.stdout.buffer.write(b'\\x1b[32mbg\\x1b[0m\\n')"]
    assert hostexec.run(prog, True) is True
    jobs = process.list_jobs()
    assert len(jobs) == 1
    pid = jobs[0].pids[0]
    assert process.last_bg_pid() == pid
    deadline = time.time() + 10
    zombie = None
    while time.time() < deadline:
        pcb = process.get(pid)
        if pcb is None:
            # already reaped: nothing left to inspect, so stop looking
            break
        if pcb.state == "Zombie":
            zombie = pcb
            break
        time.sleep(0.05)
    assert zombie is not None and zombie.state == "Zombie", \
        f"作业 {pid} 未变成僵尸: {getattr(zombie, 'state', None)!r}"
    time.sleep(0.3)  # Leave the relay thread time to flush
    out, _ = capfd.readouterr()
    assert "\x1b[32mbg\x1b[0m" in out
