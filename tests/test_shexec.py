"""shexec + filters：管线 / 条件链 / 重定向 / 展开的端到端。"""
import contextlib
import io
import os
import sys

import pytest

sys.path.insert(0, "src")
import main
import proc
from shell import shexec


def run(cmd):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main.handle_command(cmd)
    return buf.getvalue()


def setup_function(_):
    proc.reset()
    shexec.reset_state()


def test_multistage_builtin_pipe(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "words.txt").write_text(
        "banana\napple\ncherry\napple\n", encoding="utf-8")
    out = run("cat words.txt | sort | uniq -c | sort -n")
    assert "2 apple" in out
    out = run("cat words.txt | grep apple | wc -l")
    assert out.strip().split()[0] == "2"


def test_host_builtin_mixed_pipe(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = run(f"{sys.executable} -c 'print(\"a\\nb\\na\")' | sort | uniq -c")
    assert "2 a" in out
    out = run("echo hello | rev")
    assert "olleh" in out


def test_host_chain_streams(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code = 'import sys;sys.stdout.write("x\\ny\\n")'
    out = run(f"{sys.executable} -c '{code}' | {sys.executable}"
              " -c 'import sys;[sys.stdout.write(l) for l in sys.stdin]'"
              " | wc -l")
    assert out.strip().split()[0] == "2"


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


def test_variables_and_subst(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert "42" in run("A=42; echo $A")
    assert "hi-sub" in run("echo pre-$(echo hi)-sub")
    assert "back" in run("echo `echo back`")
    assert "zsh-no" not in run("echo $NO_SUCH_VAR_XYZ-9")


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


def test_syntax_and_127(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = run("echo a | | echo b")
    assert "语法错误" in out
    out = run("no-such-command-abc")
    assert "未找到命令" in out
    out = run("echo 'unclosed")
    assert "语法错误" in out


def test_background_host_only(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import process
    code = "import time;time.sleep(0.2)"
    run(f"{sys.executable} -c '{code}' &")
    assert len(process.list_jobs()) == 1
