'''
 *
 *      test_spf.py
 *      SPF 2.0: putchar/exit stay compatible and the var/add/print extensions work.
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


# SPF 2.0 keeps the v1 putchar and exit calls working while the var/add/print extensions resolve to the right values.
def test_spf_v2(tmp_path):
    import main  # noqa: F401 (parse_spf needs main.boot_time, so import it first to initialise)
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


# The bundled hello.spf still runs under the v2 interpreter.
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
