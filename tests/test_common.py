'''
 *
 *      test_common.py
 *      Common path resolution plus the open sandbox with the full builtin set.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import os
import sys

sys.path.insert(0, "src")


# The root is the src tree itself, and an unreadable current_slot falls back to slot_a instead of raising.
def test_common_paths():
    from common.paths import get_root_dir, read_current_slot
    here_src = os.path.join(os.getcwd(), "src")
    assert get_root_dir(here_src) == os.getcwd()
    assert get_root_dir("/tmp/xyz") == "/tmp/xyz"
    assert read_current_slot("/nonexistent-dir") == "slot_a"


# open hello must resolve apps/ through get_app_path() and run with the complete builtin set, not report an undefined name.
def test_open_apps_have_full_builtins():
    import contextlib
    import io
    import os
    import main
    old = os.getcwd()
    # open hello resolves apps/ through get_app_path(), so it has to run from src
    os.chdir(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main.handle_command("open hello")
        out = buf.getvalue()
    finally:
        os.chdir(old)
    assert "Hello from apps/hello.py" in out
    assert "is not defined" not in out


# The RPC address parser must accept IPv4, a bare IPv6 form and the
# bracketed "[::1]:port" form that a plain rsplit silently mangles.
def test_api_addr_parsing():
    import importlib
    api = importlib.import_module("apps.api")
    assert api._split_addr("127.0.0.1:5555") == ("127.0.0.1", 5555)
    assert api._split_addr("[::1]:5555") == ("::1", 5555)
    assert api._split_addr("[fe80::1%eth0]:7") == ("fe80::1%eth0", 7)
    for bad in ("nocolon", "[::1]5555", "host:notaport"):
        try:
            api._split_addr(bad)
        except ValueError:
            continue
        raise AssertionError(f"should have rejected {bad!r}")


# Two threads calling at once must get distinct request ids, and a reply
# carrying the wrong id must be refused rather than returned to the caller.
def test_api_request_ids_are_unique():
    import importlib
    import threading
    api = importlib.import_module("apps.api")

    class FakeConn:
        def __init__(self):
            self.sent = []
            self.reply_id = None

        def send(self, payload):
            self.sent.append(payload)

        def recv(self):
            rid = self.reply_id
            if rid is None:
                rid = self.sent[-1][0]
            return rid, {"ok": True, "ret": rid}

    conn = FakeConn()
    api._conn = conn
    api._req_id = 0
    try:
        results = []
        lock = threading.Lock()

        def worker():
            ok, value = api._call("noop")
            with lock:
                results.append((ok, value))

        threads = [threading.Thread(target=worker) for _ in range(16)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        ids = [payload[0] for payload in conn.sent]
        assert len(ids) == len(set(ids)) == 16, ids
        assert len(results) == 16

        conn.reply_id = 999999
        ok, error = api._call("noop")
        assert ok is False
        assert "序号" in error
    finally:
        api._conn = None
        api._req_id = 0
