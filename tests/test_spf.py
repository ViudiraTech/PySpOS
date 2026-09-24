"""SPF 2.0：向后兼容 putchar/exit + var/add/print 扩展。"""
import contextlib
import io
import sys

sys.path.insert(0, "src")


def test_spf_v2(tmp_path):
    import main  # noqa: F401 （parse_spf 依赖 main.boot_time，先导入初始化）
    import parse_spf
    spf = tmp_path / "demo.spf"
    spf.write_text(
        'putchar("v1-ok");\n'
        'var(name, "PySpOS");\n'
        'print("hello $name");\n'
        'add(40, 2, answer);\n'
        'print("answer=$answer");\n'
        'exit(0);\n',
        encoding="utf-8",
    )
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        parse_spf.run_spf(str(spf))
    out = buf.getvalue()
    assert "v1-ok" in out
    assert "hello PySpOS" in out
    assert "answer=42" in out


def test_spf_hello_still_runs():
    import os
    import main  # noqa: F401
    import parse_spf
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    hello = os.path.join(root, "src", "spfapps", "hello.spf")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        parse_spf.run_spf(hello)
    assert "spf" in buf.getvalue() or "孙浩博" in buf.getvalue()
