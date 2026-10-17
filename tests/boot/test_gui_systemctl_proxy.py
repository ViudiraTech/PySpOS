'''
 *
 *      test_gui_systemctl_proxy.py
 *      Desktop PTY shells borrow the host's service manager over the
 *      forkexec RPC channel: handler ops, session server and the shell proxy.
 *
 *      2026/10/11 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import base64
import re

import pytest

import api
import forkexec
from service_manager import Journal, ServiceManager, Unit, set_manager
from shell import service_cmds as svc_cmds


# Build an isolated manager with two units and publish it as the host's.
# monkeypatch restores the previous global on teardown.
@pytest.fixture()
def host_manager(monkeypatch):
    service = ServiceManager(journal=Journal(emit=None))
    service.add(Unit("demo.service", "Demo service", start=lambda: None,
                     stop=lambda: None))
    service.add(Unit("other.service", "Other service", start=lambda: None))
    set_manager(service)
    monkeypatch.setattr("service_manager._manager", service)
    yield service


# Reset the child-side cached connection so one test's server never leaks
# a stale socket into the next test in this process (both module instances:
# top-level api and the apps.api namespace-package view).
@pytest.fixture(autouse=True)
def _clean_api_conn():
    yield
    api._conn = None
    try:
        from apps import api as apps_api
        apps_api._conn = None
    except ImportError:
        pass


# The sm_* handler ops answer from the host's live manager, no sockets needed.
def test_handler_ops_read_live_manager(host_manager):
    assert {u["name"] for u in forkexec._sysctl_handler("sm_status", [None], {})} == \
        {"demo.service", "other.service"}
    assert forkexec._sysctl_handler("sm_status", ["demo.service"], {})["state"] == "inactive"
    assert forkexec._sysctl_handler("sm_has_unit", ["demo.service"], {}) is True
    assert forkexec._sysctl_handler("sm_has_unit", ["missing.service"], {}) is False
    order, _, missing = forkexec._sysctl_handler("sm_resolve", [["demo.service"]], {})
    assert order == ["demo.service"] and missing == {}
    assert forkexec._sysctl_handler("sm_start", ["demo.service"], {})["state"] == "active"
    assert "demo.service" in host_manager.journal.lines("demo.service")[0]
    assert forkexec._sysctl_handler("sm_stop", ["demo.service"], {}) is None
    assert host_manager.status("demo.service")["state"] == "inactive"
    assert forkexec._sysctl_handler("sm_journal", ["demo.service"], {})


# Unknown units surface as errors, not tracebacks, for the shell to report.
def test_handler_ops_report_missing_units(host_manager):
    with pytest.raises(Exception, match="Unit not found"):
        forkexec._sysctl_handler("sm_status", ["missing.service"], {})


# The session server answers the same ops over a real socket with the auth key.
def test_session_server_round_trip(host_manager):
    from multiprocessing.connection import Client
    handle = forkexec.open_session_server("test-desktop")
    assert handle is not None
    try:
        import os
        addr = os.environ[forkexec.SYSCTL_ENV]
        authkey = base64.b64decode(os.environ[forkexec.AUTHKEY_ENV])
        conn = Client(api._client_target(addr), authkey=authkey)
        conn.send((7, "sm_has_unit", ["demo.service"], {}))
        rid, payload = conn.recv()
        assert (rid, payload) == (7, {"ok": True, "ret": True})
        conn.send((8, "sm_status", ["demo.service"], {}))
        _, payload = conn.recv()
        assert payload["ok"] and payload["ret"]["name"] == "demo.service"
        conn.send((9, "no_such_op", [], {}))
        _, payload = conn.recv()
        assert payload["ok"] is False
        conn.close()
    finally:
        forkexec.close_session_server(handle)
    import os
    assert forkexec.SYSCTL_ENV not in os.environ
    assert forkexec.AUTHKEY_ENV not in os.environ


# The shell proxy speaks the manager subset over an injected transport.
def test_remote_manager_proxy_shape():
    calls = []

    def fake(op, *args):
        calls.append((op, args))
        if op == "sm_status" and args[0] is None:
            return (True, [{"name": "a.service", "state": "active",
                            "description": "A"}])
        if op == "sm_has_unit":
            return (True, args[0] == "a.service")
        if op == "sm_resolve":
            return (True, (["a.service"], {}, {}))
        if op == "sm_journal":
            return (True, ["line one"])
        if op == "sm_start":
            return (True, {"name": args[0], "state": "active"})
        raise AssertionError(op)

    manager = svc_cmds._RemoteManager(fake)
    assert [u["name"] for u in manager.status()] == ["a.service"]
    assert ("a.service" in manager.units) and ("b.service" not in manager.units)
    assert manager.resolve(("a.service",))[0] == ["a.service"]
    assert manager.journal.lines("a.service") == ["line one"]
    assert manager.start("a.service")["state"] == "active"

    def failing(op, *args):
        return (False, "UnitError: Unit not found: ghost.service")

    with pytest.raises(RuntimeError, match="Unit not found"):
        svc_cmds._RemoteManager(failing).status("ghost.service")
    with pytest.raises(Exception, match="not booted"):
        svc_cmds._RemoteManager(lambda op, *a: None).status()


# End to end: systemctl in a manager-less shell drives the host over RPC.
def test_systemctl_through_proxy(host_manager, monkeypatch, capsys):
    handle = forkexec.open_session_server("test-desktop")
    assert handle is not None
    monkeypatch.setattr(svc_cmds, "_manager",
                        lambda: svc_cmds._RemoteManager(api._call))
    try:
        assert svc_cmds.cmd_service("list-units") == 0
        out = capsys.readouterr().out
        assert "demo.service" in out and "other.service" in out
        assert svc_cmds.cmd_service("start demo") == 0
        assert host_manager.status("demo.service")["state"] == "active"
        assert svc_cmds.cmd_service("status demo") == 0
        status_out = re.sub(r"\x1b\[[0-9;]*m", "", capsys.readouterr().out)
        assert "demo.service" in status_out
        assert "状态: active (success)" in status_out
        # The status block is for a person reading a terminal, not for a parser:
        # it used to dump the raw status dict as JSON.
        assert "{" not in status_out and '"state"' not in status_out
        assert svc_cmds.cmd_service("status other") == 3
        assert svc_cmds.cmd_service("status ghost") == 1
        assert "Unit not found" in capsys.readouterr().out
        assert svc_cmds.cmd_journalctl("-u demo") == 0
    finally:
        forkexec.close_session_server(handle)


# Without a manager and without a channel, the original error is preserved.
def test_no_manager_no_channel_keeps_original_error(monkeypatch):
    monkeypatch.setattr("service_manager._manager", None)
    monkeypatch.delenv(forkexec.SYSCTL_ENV, raising=False)
    monkeypatch.delenv(forkexec.AUTHKEY_ENV, raising=False)
    with pytest.raises(Exception, match="not booted"):
        svc_cmds._manager()
