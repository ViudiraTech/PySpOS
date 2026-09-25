"""宿主 Linux 程序执行：PATH 解析、前台直通、后台中继、信号、重定向。

能用真 fork+exec 的地方就用真的（sys.executable -c），只在需要隔离
信号/进程表时打桩。POSIX 相关用例在非 POSIX 平台跳过。
"""
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


def run(cmd):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main.handle_command(cmd)
    return buf.getvalue()


def setup_function(_):
    proc.reset()


def _py_writer(code="import sys;sys.stdout.buffer.write(b'out\\n')"):
    return [sys.executable, "-c", code]


# ---------- PATH 解析 ----------

def test_resolve_absolute_and_path(tmp_path):
    exe = tmp_path / "myprog"
    exe.write_text("#!/bin/sh\n", encoding="utf-8")
    exe.chmod(0o755)
    assert hostexec.resolve(str(exe)) == str(exe)
    assert hostexec.resolve(str(tmp_path / "nope")) is None
    assert hostexec.resolve("") is None


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


# ---------- 前台：真进程、vt100 原样过 ----------

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


# ---------- 分发：内置优先、127 保留 ----------

def test_builtin_shadows_host(monkeypatch):
    called = []

    class Boom:
        def __init__(self, *a, **k):
            called.append((a, k))
            raise AssertionError("不应 spawn 宿主程序")

    monkeypatch.setattr(subprocess, "Popen", Boom)
    monkeypatch.setattr(hostexec, "resolve", lambda name: "/bin/echo")
    assert "hi" in run("echo hi")
    assert called == []


def test_unknown_still_127(monkeypatch):
    monkeypatch.setattr(hostexec, "resolve", lambda name: None)
    out = run("definitely-not-a-command-xyz")
    assert "未找到命令" in out


# ---------- 重定向 / 管道走 fd 级 ----------

@needs_posix
def test_redirect_host_keeps_vt100(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code = ("import sys;sys.stdout.buffer.write("
            f"'A\\n\\x1b[1mB\\x1b[0m\\n'.encode())")
    quoted = code.replace("'", "'\\''")
    run(f"{sys.executable} -c '{quoted}' > vt.txt")
    raw = (tmp_path / "vt.txt").read_bytes()
    assert raw == b"A\n\x1b[1mB\x1b[0m\n"


@needs_posix
def test_pipe_host_to_grep(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code = ("import sys;sys.stdout.write('foo\\nbar\\nfoobar\\n')")
    quoted = code.replace("'", "'\\''")
    out = run(f"{sys.executable} -c '{quoted}' | grep bar")
    assert "foobar" in out and "\nfoo\n" not in out


# ---------- 后台：作业注册 + 中继不改字节 ----------

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
    while time.time() < deadline:
        pcb = process.get(pid)
        if pcb is not None and pcb.state == "Zombie":
            break
        time.sleep(0.05)
    assert process.get(pid).state == "Zombie"
    time.sleep(0.3)  # 给中继线程留出 flush 时间
    out, _ = capfd.readouterr()
    assert "\x1b[32mbg\x1b[0m" in out
