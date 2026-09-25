"""上一轮遗留限制项的回归：引号参数、算术、默认赋值、子 shell、fd 复制、
流式管道、后台 builtin。"""
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


def run(cmd):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main.handle_command(cmd)
    return buf.getvalue()


def setup_function(_):
    proc.reset()
    shexec.reset_state()


# ---------- 带空格的引号参数 ----------

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


# ---------- 算术 / 默认值 ----------

def test_arithmetic_expansion():
    assert "14" in run("echo $((2+3*4))")
    assert "3" in run("echo $((7/2))")
    assert "1024" in run("echo $((2**10))")
    assert "-2" in run("echo $((-5%3))")
    assert "5" in run("N=3; echo $((N+2))")
    assert "ERROR" not in run("echo $((1+1))").upper()
    assert "除以零" in run("echo $((1/0))")


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


# ---------- 括号分组 / fd 复制 ----------

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


def test_fd_duplication(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = run("echo hi 1>&2")
    assert out.strip() == "hi"
    run("echo err > e.txt 2>&1")
    assert "err" in (tmp_path / "e.txt").read_text(encoding="utf-8")
    out = run("no-such-cmd-xyz 2>&1 | grep -c 未找到")
    assert out.strip() not in ("0", "")


# ---------- 流式：上游不结束、下游提前收手 ----------

@needs_posix
def test_infinite_producer_into_early_exiting_builtin():
    out = run("yes | head -2")
    assert out.split() == ["y", "y"]
    out = run("yes | grep -q y")
    assert out.strip() == ""


@needs_posix
def test_large_output_does_not_deadlock():
    out = run("seq 1 20000 | wc -l")
    assert out.strip() == "20000"
    out = run("seq 1 20000 | tail -1")
    assert out.strip() == "20000"


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


# ---------- 后台 ----------

@needs_posix
def test_background_builtin_runs_and_returns(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    marker = tmp_path / "bg.txt"
    run("echo done > bg.txt &")
    deadline = time.time() + 10
    while time.time() < deadline and not marker.exists():
        time.sleep(0.05)
    assert marker.exists()
    assert "done" in marker.read_text(encoding="utf-8")


@needs_posix
def test_background_host_registers_job():
    run(f"{sys.executable} -c 'import time;time.sleep(0.2)' &")
    assert len(process.list_jobs()) == 1
