'''
 *
 *      test_shell.py
 *      Shell commands through the main facade: files, redirection, pipes, processes and SPC.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import contextlib
import io
import sys

sys.path.insert(0, "src")
import main
import proc


# Run one shell command and capture what it printed.
def run(cmd):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main.handle_command(cmd)
    return buf.getvalue()


# Start each test from an empty process table.
def setup_function(_):
    proc.reset()


# echo and pwd report the real state, and a command line is remembered by history.
def test_echo_pwd_history(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert "hi-shell" in run("echo hi-shell")
    assert str(tmp_path) in run("pwd")
    run("echo marked-for-history")
    assert "marked-for-history" in run("history")


# File builtins, output redirection, pipes and cp/mv all land where the shell promises.
def test_file_commands_and_redirect_pipe(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    run("mkdir sub")
    run("touch sub/a.txt")
    with open(tmp_path / "sub" / "a.txt", "w", encoding="utf-8") as f:
        f.write("foo\nbar\nfoobar\n")
    assert "foobar" in run("cat sub/a.txt")
    assert "foobar" in run("grep foo sub/a.txt")
    assert "bar" in run("cat sub/a.txt | grep bar")
    run("echo redirected > sub/out.txt")
    assert (tmp_path / "sub" / "out.txt").read_text(encoding="utf-8").strip() == "redirected"
    run("cp sub/a.txt sub/b.txt")
    assert (tmp_path / "sub" / "b.txt").exists()
    run("mv sub/b.txt sub/c.txt")
    assert (tmp_path / "sub" / "c.txt").exists()


# ps lists a live pid, signal and kill report in the shell's own Chinese wording, and the killed task stays visible under ps -a.
def test_proc_commands(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    p = proc.spawn("demo-proc", kind="shell")
    assert str(p.pid) in run("ps")
    out = run("signal %d SIGUSR1" % p.pid)
    assert "发送信号 10" in out
    out = run("kill %d" % p.pid)
    assert "已终止" in out
    assert "Killed" in run("ps -a")


# spc_show and spc_export reach the real config, and sysmon reports the product name.
def test_spc_and_sysmon(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert "[boot]" in run("spc_show")
    run("spc_export boot.spc")
    assert (tmp_path / "boot.spc").exists()
    assert "PySpOS" in run("sysmon")


# bootloader_status is refused for a non-root session.
def test_bootloader_status_requires_root(monkeypatch, capsys):
    import main
    old_root = main.rootstate
    old_persisted = main.bootcfg.get("rootstate")
    main.rootstate = False
    main.bootcfg["rootstate"] = False
    try:
        main.handle_command("bootloader_status")
        output = capsys.readouterr().out
    finally:
        main.rootstate = old_root
        main.bootcfg["rootstate"] = old_persisted
    assert "需要 ROOT" in output
