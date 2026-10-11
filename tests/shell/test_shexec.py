'''
 *
 *      test_shexec.py
 *      shexec and the filter set: pipelines, condition chains, redirection and expansion.
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

import pytest

import main
import proc
from shell import shexec


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


# A four-stage builtin pipeline streams through sort and uniq -c without buffering the whole stream.
def test_multistage_builtin_pipe(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "words.txt").write_text(
        "banana\napple\ncherry\napple\n", encoding="utf-8")
    out = run("cat words.txt | sort | uniq -c | sort -n")
    assert "2 apple" in out
    out = run("cat words.txt | grep apple | wc -l")
    assert out.strip().split()[0] == "2"


# A host producer piped into builtins works, and rev is available as a filter.
def test_host_builtin_mixed_pipe(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = run(f"{sys.executable} -c 'print(\"a\\nb\\na\")' | sort | uniq -c")
    assert "2 a" in out
    out = run("echo hello | rev")
    assert "olleh" in out


# Host-to-host pipelines stream stdin to stdout; buffering would deadlock on large output.
def test_host_chain_streams(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code = 'import sys;sys.stdout.write("x\\ny\\n")'
    out = run(f"{sys.executable} -c '{code}' | {sys.executable}"
              " -c 'import sys;[sys.stdout.write(l) for l in sys.stdin]'"
              " | wc -l")
    assert out.strip().split()[0] == "2"


# The and-or chain branches on the previous status, a semicolon runs unconditionally, and $? reports the last one.
def test_and_or_semicolon(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert "yes" in run("true && echo yes")
    assert "yes" not in run("false && echo yes")
    assert "fallback" in run("false || echo fallback")
    assert "bad" not in run("true || echo bad")
    assert "one" in run("echo one; echo two")
    assert "two" in run("echo one; echo two")
    assert "1" in run("false; echo $?")
    assert "0" in run("true; echo $?")


# Assignments, $(...) and backticks all work, and an undefined variable expands to nothing without a zsh-style error.
def test_variables_and_subst(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert "42" in run("A=42; echo $A")
    assert "hi-sub" in run("echo pre-$(echo hi)-sub")
    assert "back" in run("echo `echo back`")
    assert "zsh-no" not in run("echo $NO_SUCH_VAR_XYZ-9")


# The whole redirect family works for builtins and hosts, tee writes and copies, and a missing command's stderr can be piped.
def test_redirect_family(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    run("echo one > f.txt")
    assert (tmp_path / "f.txt").read_text(encoding="utf-8").strip() == "one"
    run("echo two >> f.txt")
    assert (tmp_path / "f.txt").read_text(
        encoding="utf-8").strip().split() == ["one", "two"]
    assert "one" in run("cat < f.txt")
    assert "two" in run("sort < f.txt | tail -1")
    run(f"{sys.executable} -c 'print(123)' > host.txt")
    assert (tmp_path / "host.txt").read_text(encoding="utf-8").strip() == "123"
    run("echo data | tee t.txt | wc -c")
    assert (tmp_path / "t.txt").read_text(encoding="utf-8").strip() == "data"
    out = run("definitely-missing-cmd-xyz 2>&1 | cat")
    assert "未找到命令" in out


# The filter set (sort, head, tail, tr, cut, sed, tac, nl, test and the bracket test) behaves like its Unix namesake.
def test_filters(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "n.txt").write_text("b\n1\na\n2\n", encoding="utf-8")
    assert "a" in run("sort -n n.txt | head -2")
    assert "1" in run("sort -n n.txt | tail -2 | head -1")
    assert "A" in run("echo abc | tr a-z A-Z")
    assert "b,c" in run("echo a,b,c | cut -d , -f 2,3")
    assert "4" in run("seq 1 5 | tail -n +4 | head -1")
    assert "xy" in run("echo xxy | sed 's/x+/x/g'")
    assert "3" in run("seq 1 3 | tac | head -1").split()
    assert "1" in run("seq 1 3 | nl | head -1").split()[0]
    assert run("test -f n.txt && echo isfile").strip().startswith("isfile")
    assert "yes" in run("[ 1 -eq 1 ] && echo yes")
    assert "no" not in run("[ 1 -eq 2 ] && echo no")


# Syntax errors and unknown commands report the shell's own wording instead of raising.
def test_syntax_and_127(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = run("echo a | | echo b")
    assert "语法错误" in out
    out = run("no-such-command-abc")
    assert "未找到命令" in out
    out = run("echo 'unclosed")
    assert "语法错误" in out


# A backgrounded host program registers a job.
def test_background_host_only(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import process
    code = "import time;time.sleep(0.2)"
    run(f"{sys.executable} -c '{code}' &")
    assert len(process.list_jobs()) == 1


# A redirect on any pipeline stage is honoured, not just the first one.
def test_pipeline_late_stage_redirects(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("hello\nbye\n", encoding="utf-8")
    run("cat a.txt | grep hello > out.txt")
    assert (tmp_path / "out.txt").read_text(encoding="utf-8").strip() == "hello"
    run("echo hi | cat > two.txt")
    assert (tmp_path / "two.txt").read_text(encoding="utf-8").strip() == "hi"
    # A redirect on the first stage still breaks the pipe exactly like bash.
    out = run("echo middle > mid.txt | cat")
    assert (tmp_path / "mid.txt").read_text(encoding="utf-8").strip() == "middle"
    assert "middle" not in out


# 2> takes stderr only: stdout keeps flowing, and 2>&1 merges into the sink.
def test_stderr_redirect_keeps_stdout(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = run("echo hi 2> err.txt")
    assert "hi" in out
    assert (tmp_path / "err.txt").read_text(encoding="utf-8") == ""
    run("echo both > same.txt 2>&1")
    assert (tmp_path / "same.txt").read_text(encoding="utf-8").strip() == "both"
    status, captured = shexec.run_line("echo h2 2>&1", capture=True)
    assert status == 0
    assert captured == "h2\n".encode("utf-8")


# Builtins that fail report a nonzero status, so && chains stop like bash.
def test_failing_builtins_set_status(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert "BAD" not in run("cat no-such-file-xyz && echo BAD")
    assert "1" in run("cat no-such-file-xyz; echo $?")
    assert "BAD" not in run("rm -f no-such-file-xyz && echo BAD")
    assert "BAD" not in run("finfo no-such-file-xyz && echo BAD")
    assert "BAD" not in run("touch /nope-xyz/f && echo BAD")
    assert "BAD" not in run("cp no-such-file-xyz dest-xyz && echo BAD")


# rm parses -r/-f itself, refuses directories without -r, and never climbs out.
def test_rm_flags(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "gone.txt").write_text("x", encoding="utf-8")
    run("rm -f gone.txt")
    assert not (tmp_path / "gone.txt").exists()
    tree = tmp_path / "tree"
    (tree / "sub").mkdir(parents=True)
    (tree / "sub" / "x").write_text("x", encoding="utf-8")
    out = run("rm -f tree && echo deleted")
    assert "是一个目录" in out
    assert "deleted" not in out
    assert tree.exists()
    run("rm -rf tree")
    assert not tree.exists()
    assert "survived" not in run("rm -rf .. && echo survived")
