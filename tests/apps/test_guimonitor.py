'''
 *
 *      test_guimonitor.py
 *      System Monitor: live PySpOS tables, never host numbers; banner on failure.
 *
 *      2026/10/11 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import pytest

import forkexec
import process as P
from apps.guimonitor import Monitor, _local_snapshot, fetch_snapshot


# Keep the shared process table clean for the rest of the suite.
def setup_function(_):
    P.reset()


def teardown_function(_):
    P.reset()


# A canned host snapshot with two tasks, one of them current.
def _snap(**over):
    snap = {"ok": True, "source": "host", "booted": True, "error": "",
            "identity": {"version": "3.2.0", "slot": "slot_a",
                         "slot_version": "3.2.0", "ota": "启用"},
            "rq": {"queued": 2, "avg": 12.5, "min": 10.0, "switches": 99,
                   "ticks": 1000, "curr_pid": 4, "curr_comm": "task-b"},
            "tasks": [{"pid": 3, "ppid": 2, "comm": "task-a", "state": "Sleeping",
                       "nice": 0, "vruntime": 15.0, "cpu": 42.0,
                       "kind": "app", "remote": False},
                      {"pid": 4, "ppid": 2, "comm": "task-b", "state": "Running",
                       "nice": -5, "vruntime": 10.0, "cpu": 7.0,
                       "kind": "app", "remote": True}],
            "recent": [{"pid": 2, "comm": "old-task", "exit": 0, "sig": 0,
                        "cpu": 123.0, "vruntime": 45.0, "kind": "app"}]}
    snap.update(over)
    return snap


def _texts(items):
    return [i["text"] for i in items if i.get("type") == "text"]


# The table shows identity, headers, every row and the scheduler strip.
def test_table_renders_snapshot(monkeypatch):
    monkeypatch.setattr("apps.guimonitor.fetch_snapshot", lambda: _snap())
    texts = _texts(Monitor().scene(560, 430))
    joined = "\n".join(texts)
    assert "PID" in texts and "VRUNTIME" in texts and "CMD" in texts
    assert "task-a" in joined and "task-b" in joined
    assert "PySpOS 3.2.0" in joined and "slot_a" in joined
    assert "runnable 2" in joined and "avg_vruntime 12.50" in joined
    assert "tick 1000" in joined
    for host_word in ("逻辑 CPU", "磁盘", "负载", "平台:"):
        assert host_word not in joined


# The current task's row is highlighted; clipped tables get a +N more footer.
def test_current_row_highlighted_and_clipping_footer(monkeypatch):
    monkeypatch.setattr("apps.guimonitor.fetch_snapshot", lambda: _snap())
    items = Monitor().scene(560, 430)
    rows = [i for i in items if i.get("type") == "text" and i["text"] == "task-b"]
    assert rows and all(i["color"] == "#86cd9a" for i in rows)
    plain = [i for i in items if i.get("type") == "text" and i["text"] == "task-a"]
    assert plain and all(i["color"] == "#e6edf3" for i in plain)
    clipped = _texts(Monitor().scene(560, 130))
    assert any("+1 more" in t for t in clipped)
    assert "task-b" not in "\n".join(t for t in clipped if "curr" not in t)


# The RECENT section shows reaped tasks with their final CPU time.
def test_recent_section_renders_and_empty_shows_placeholder(monkeypatch):
    monkeypatch.setattr("apps.guimonitor.fetch_snapshot", lambda: _snap())
    texts = _texts(Monitor().scene(560, 470))
    joined = "\n".join(texts)
    assert "RECENT" in texts and "old-task" in joined and "123" in joined
    snap = _snap(recent=[])
    monkeypatch.setattr("apps.guimonitor.fetch_snapshot", lambda: snap)
    assert "(空)" in _texts(Monitor().scene(560, 470))


# Failures and empty tables degrade to banners, never tracebacks.
def test_failure_and_empty_degrade_gracefully(monkeypatch):
    monkeypatch.setattr("apps.guimonitor.fetch_snapshot",
                        lambda: {"ok": False, "error": "主机数据失败: 断开",
                                 "tasks": []})
    assert "主机数据失败: 断开" in _texts(Monitor().scene(560, 430))
    monkeypatch.setattr("apps.guimonitor.fetch_snapshot", lambda: _snap(tasks=[]))
    texts = _texts(Monitor().scene(560, 430))
    assert "PID" in texts and "task-a" not in "\n".join(texts)


# Remote fetch wins when a channel exists; its failures become banners too.
def test_fetch_snapshot_remote_paths(monkeypatch):
    class FakeApi:
        def __init__(self, res):
            self._res = res

        def is_remote(self):
            return True

        def _call(self, op):
            assert op == "sm_snapshot"
            return self._res

    monkeypatch.setattr("apps.guimonitor._syscall_api",
                        lambda: FakeApi((True, _snap())))
    assert fetch_snapshot()["source"] == "host"
    monkeypatch.setattr("apps.guimonitor._syscall_api",
                        lambda: FakeApi((False, "UnitError: gone")))
    assert fetch_snapshot()["error"] == "主机数据失败: UnitError: gone"
    monkeypatch.setattr("apps.guimonitor._syscall_api", lambda: None)
    monkeypatch.setattr("process._pt", P.ProcessTable())
    assert fetch_snapshot()["error"] == "系统未启动"


# Without a channel the local table is read when this process booted it.
def test_fetch_snapshot_local_table(monkeypatch):
    monkeypatch.setattr("apps.guimonitor._syscall_api", lambda: None)
    table = P.ProcessTable()
    table.boot_system()
    table.spawn("local-task")
    monkeypatch.setattr("process._pt", table)
    snap = fetch_snapshot()
    assert snap["source"] == "local" and snap["booted"] is True
    assert "local-task" in [t["comm"] for t in snap["tasks"]]
    assert _local_snapshot()["rq"]["queued"] == 1


# The sm_snapshot handler answers with the host's live rows and estimators.
def test_sm_snapshot_handler_reports_live_state():
    P.boot_system()
    P.spawn("snap-a", nice=-5)
    other = P.spawn("snap-b")
    P.exit_task(other.pid, 3)
    P._table().reap(other.pid)
    snap = forkexec._sysctl_handler("sm_snapshot", [], {})
    assert snap["ok"] is True and snap["booted"] is True
    assert "snap-a" in {t["comm"] for t in snap["tasks"]}
    row = next(t for t in snap["tasks"] if t["comm"] == "snap-a")
    assert row["nice"] == -5 and set(row) >= {"pid", "state", "vruntime", "cpu"}
    assert set(snap["rq"]) >= {"queued", "avg", "min", "switches", "curr_pid",
                               "ticks"}
    assert set(snap["identity"]) >= {"version", "slot", "slot_version", "ota"}
    assert any(r["comm"] == "snap-b" and r["exit"] == 3 for r in snap["recent"])
