"""Shell 命令（经 main facade）：文件命令 / 重定向 / 管道 / 进程 / SPC。"""
import contextlib
import io
import sys

sys.path.insert(0, "src")
import main
import proc


def run(cmd):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main.handle_command(cmd)
    return buf.getvalue()


def setup_function(_):
    proc.reset()


def test_echo_pwd_history(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert "hi-shell" in run("echo hi-shell")
    assert str(tmp_path) in run("pwd")
    run("echo marked-for-history")
    assert "marked-for-history" in run("history")


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


def test_proc_commands(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    p = proc.spawn("demo-proc", kind="shell")
    assert str(p.pid) in run("ps")
    out = run("signal %d SIGUSR1" % p.pid)
    assert "发送信号 10" in out
    out = run("kill %d" % p.pid)
    assert "已终止" in out
    assert "Killed" in run("ps -a")


def test_spc_and_sysmon(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert "[boot]" in run("spc_show")
    run("spc_export boot.spc")
    assert (tmp_path / "boot.spc").exists()
    assert "PySpOS" in run("sysmon")
