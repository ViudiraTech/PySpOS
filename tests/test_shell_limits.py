'''
 *
 *      test_shell_limits.py
 *      Remaining shell limitations: quoted words, arithmetic, defaults, groups, fd copying, streaming pipes.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import contextlib
import io
import os
import sys
import time

import pytest

sys.path.insert(0, "src")
import main
import proc
import process
from shell import shexec


IS_POSIX = os.name == "posix"
needs_posix = pytest.mark.skipif(not IS_POSIX, reason="需要 POSIX 管道/信号")


# Run one shell command and capture what it printed.
def run(cmd):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main.handle_command(cmd)
    return buf.getvalue()


# Start each test from an empty process table and a fresh shexec state.
def setup_function(_):
    proc.reset()
    shexec.reset_state()


# ---------- quoted arguments containing spaces ----------

# A quoted argument containing spaces must arrive as one word, through both quote styles and into a pipeline.
def test_quoted_arg_with_spaces_survives(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "f.txt").write_text("hello world\nsecond line\n",
                                   encoding="utf-8")
    assert "hello world" in run("grep 'hello world' f.txt")
    assert "hello world" in run('grep "hello world" f.txt')
    assert "hello" not in run("grep 'hello world' f.txt | grep -c 'hello world'").replace(
        "hello world", "", 1)
    out = run("echo 'a b' | grep 'a b'")
    assert out.strip() == "a b"


# grep honours -i, -c and -v, and its exit status reaches last_status so a conditional can branch on it.
def test_grep_flags_and_status(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "f.txt").write_text("Foo\nbar\nfoo\n", encoding="utf-8")
    assert "2" in run("grep -ci foo f.txt")
    out = run("grep -i foo f.txt")
    assert "Foo" in out and "foo" in out
    assert "bar" not in out
    assert "1" in run("grep -c foo f.txt")
    assert run("grep -v foo f.txt").strip().split() == ["Foo", "bar"]
    shexec.run_line("grep -q nothing f.txt")
    assert shexec.last_status() == 1
    shexec.run_line("grep -q foo f.txt")
    assert shexec.last_status() == 0


# ---------- arithmetic and defaults ----------

# Arithmetic expansion respects precedence, integer division, power, modulo and shell variables, and reports division by zero instead of crashing.
def test_arithmetic_expansion():
    assert "14" in run("echo $((2+3*4))")
    assert "3" in run("echo $((7/2))")
    assert "1024" in run("echo $((2**10))")
    assert "-2" in run("echo $((-5%3))")
    assert "5" in run("N=3; echo $((N+2))")
    assert "ERROR" not in run("echo $((1+1))").upper()
    assert "除以零" in run("echo $((1/0))")


# Every parameter default form behaves per POSIX: unset differs from empty, and the assign and abort forms do what they say.
def test_parameter_default_forms():
    assert "[fb]" in run("echo [${NOPE:-fb}]")
    assert "[fb]" in run("V=; echo [${V:-fb}]")
    assert "[x]" in run("V=x; echo [${V:-fb}]")
    assert "[]" in run("V=; echo [${V-fb}]")
    assert "[x]" in run("V=x; echo [${V-fb}]")
    assert "[fb]" in run("echo [${NOPE-fb}]")
    assert "[x]" in run("V=x; echo [${V:-fb}]")
    assert "[alt]" in run("V=x; echo [${V:+alt}]")
    assert "[]" in run("echo [${NOPE:+alt}]")
    out = run("echo [${NOPE:=made}]")
    assert "[made]" in out
    assert "made" in run("echo $NOPE")
    assert "boom" in run("echo ${NOPE:?boom}")


# ---------- parenthesised groups and fd duplication ----------

# A parenthesised group works as a pipeline member and a redirect target, and a failed cd aborts the group without running the rest.
def test_group_as_pipeline_member(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert run("(echo a; echo b) | tail -1").strip() == "b"
    assert run("(echo one; echo two) | wc -l").strip() == "2"
    assert "only" in run("(echo only) | cat")
    (tmp_path / "g.txt").write_text("", encoding="utf-8")
    run("(echo grouped) > g.txt")
    assert "grouped" in (tmp_path / "g.txt").read_text(encoding="utf-8")
    assert "nope" not in run("(cd /definitely-not-here && echo ran)")
    assert "ran" not in run("(cd /definitely-not-here && echo ran)")


# 1>&2 and 2>&1 redirect at the fd level, and a failed command's stderr still reaches a piped filter.
def test_fd_duplication(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = run("echo hi 1>&2")
    assert out.strip() == "hi"
    run("echo err > e.txt 2>&1")
    assert "err" in (tmp_path / "e.txt").read_text(encoding="utf-8")
    out = run("no-such-cmd-xyz 2>&1 | grep -c 未找到")
    assert out.strip() not in ("0", "")


# ---------- streaming: upstream never ends, downstream quits early ----------

# A producer that never ends must not hang the shell when the downstream builtin exits early.
@needs_posix
def test_infinite_producer_into_early_exiting_builtin():
    out = run("yes | head -2")
    assert out.split() == ["y", "y"]
    out = run("yes | grep -q y")
    assert out.strip() == ""


# A zero line count must read nothing at all rather than drain to EOF.
@needs_posix
def test_head_zero_reads_nothing():
    out = run("yes | head -n 0")
    assert out.strip() == ""
    out = run("seq 1 1000000 | head -0")
    assert out.strip() == ""


# A 20000-line pipe must be consumed end to end, so the reader has to drain while the writer streams.
@needs_posix
def test_large_output_does_not_deadlock():
    out = run("seq 1 20000 | wc -l")
    assert out.strip() == "20000"
    out = run("seq 1 20000 | tail -1")
    assert out.strip() == "20000"


# Truncating, appending and input redirection all behave as the shell's own semantics require.
@needs_posix
def test_redirect_file_and_input_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    run("echo one > f.txt")
    assert (tmp_path / "f.txt").read_text(encoding="utf-8").strip() == "one"
    run("echo two >> f.txt")
    assert (tmp_path / "f.txt").read_text(encoding="utf-8").split() == [
        "one", "two"]
    assert "one" in run("cat < f.txt")
    run("true > empty.txt")
    assert (tmp_path / "empty.txt").exists()


# ---------- background ----------

# A backgrounded builtin must really run: wait for the content to land, not just for the file to appear.
@needs_posix
def test_background_builtin_runs_and_returns(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    marker = tmp_path / "bg.txt"
    run("echo done > bg.txt &")
    # The file exists the moment the redirect opens it, but the contents only land once the background thread has really run,
    # so wait for the contents, not for the existence, or the check just wins the race.
    deadline = time.time() + 10
    text = ""
    while time.time() < deadline:
        if marker.exists():
            text = marker.read_text(encoding="utf-8")
            if "done" in text:
                break
        time.sleep(0.05)
    assert "done" in text


# A backgrounded host program registers with the job table.
@needs_posix
def test_background_host_registers_job():
    run(f"{sys.executable} -c 'import time;time.sleep(0.2)' &")
    assert len(process.list_jobs()) == 1
