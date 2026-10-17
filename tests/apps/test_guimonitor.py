'''
 *
 *      test_guimonitor.py
 *      Scheduler view: EEVDF lag bars, live host tables, banner on failure.
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


# One runnable task that is owed CPU (lag > 0) and one that is ahead of the
# queue average (lag < 0), plus a sleeping task with no lag at all.
def _task(pid, comm, state, vruntime, lag, **over):
    task = {"pid": pid, "ppid": 2, "comm": comm, "state": state, "nice": 0,
            "weight": 1024, "vruntime": vruntime, "deadline": vruntime + 6.0,
            "slice": 6.0, "cpu": 7.0, "nvcsw": 1, "nivcsw": 0, "kind": "app",
            "remote": False, "lag": lag,
            "eligible": (lag >= 0) if lag is not None else None}
    task.update(over)
    return task


# A canned host snapshot shaped exactly like ProcessTable.snapshot() plus the
# host's identity.
def _snap(**over):
    snap = {"ok": True, "source": "host", "booted": True, "error": "",
            "identity": {"version": "3.2.0", "slot": "slot_a",
                         "slot_version": "3.2.0", "ota": "启用"},
            "rq": {"runnable": 2, "avg": 12.5, "min": 10.0, "switches": 99,
                   "ticks": 1000, "base_slice": 6.0, "curr_pid": 4,
                   "curr_comm": "task-b"},
            "timeline": [(9.5, 3, "switch-to deadline=21.500"),
                         (10.0, 4, "switch-to deadline=16.000")],
            "tasks": [_task(3, "task-a", "Sleeping", 15.0, None),
                      _task(4, "task-b", "Running", 10.0, 2.5, nice=-5,
                            weight=3351)],
            "recent": [{"pid": 2, "comm": "old-task", "exit": 0, "sig": 0,
                        "cpu": 123.0, "vruntime": 45.0, "kind": "app"}]}
    snap.update(over)
    return snap


def _texts(items):
    return [i["text"] for i in items if i.get("type") == "text"]


# A scene the view builds is one the compositor would accept.
def test_scene_matches_the_compositor_protocol(monkeypatch):
    from vortexglass import model
    monkeypatch.setattr("apps.guimonitor.fetch_snapshot", lambda: _snap())
    model.validate_scene(Monitor().scene(820, 600))


# The table shows identity, headers, every row and the run queue aggregates.
def test_table_renders_snapshot(monkeypatch):
    monkeypatch.setattr("apps.guimonitor.fetch_snapshot", lambda: _snap())
    texts = _texts(Monitor().scene(820, 600))
    joined = "\n".join(texts)
    for header in ("PID", "ST", "CMD", "NICE", "WEIGHT", "VRUNTIME", "DEADLINE"):
        assert header in texts, header
    assert "task-a" in joined and "task-b" in joined
    assert "PySpOS 3.2.0" in joined and "slot_a" in joined
    assert "runnable 2" in joined and "avg_vruntime 12.50" in joined
    assert "tick 1000" in joined
    for host_word in ("逻辑 CPU", "磁盘", "负载", "平台:"):
        assert host_word not in joined


# The current task's row is highlighted; clipped tables get a +N more footer.
def test_current_row_highlighted_and_clipping_footer(monkeypatch):
    monkeypatch.setattr("apps.guimonitor.fetch_snapshot", lambda: _snap())
    items = Monitor().scene(820, 600)
    rows = [i for i in items if i.get("type") == "text" and i["text"] == "task-b"]
    assert rows and all(i["color"] == "#86cd9a" for i in rows)
    plain = [i for i in items if i.get("type") == "text" and i["text"] == "task-a"]
    assert plain and all(i["color"] == "#e6edf3" for i in plain)
    clipped = _texts(Monitor().scene(820, 130))
    assert any("+1 more" in t for t in clipped), clipped


# The lag bar is the visual centre: it grows right from the queue average for a
# task that is owed CPU and left for one that is ahead of it, and a task with no
# lag only gets the empty track.
def test_lag_bars_encode_eligibility(monkeypatch):
    monkeypatch.setattr("apps.guimonitor.fetch_snapshot", lambda: _snap())
    items = Monitor().scene(820, 600)
    bars = [i for i in items if i.get("type") == "rect"
            and i["width"] != 300 and i["height"] == 7]
    colours = {i["color"] for i in bars}
    assert "#86cd9a" in colours, "欠 CPU 的任务应该向右出绿条"
    # Every bar stays inside the track's own span.
    for bar in bars:
        assert 400 <= bar["x"] and bar["x"] + bar["width"] <= 700


# A task ahead of the average is drawn in the ineligible colour, to the left.
def test_ineligible_task_draws_left_of_the_axis(monkeypatch):
    snap = _snap(tasks=[_task(5, "ahead", "Running", 20.0, -4.0)])
    monkeypatch.setattr("apps.guimonitor.fetch_snapshot", lambda: snap)
    items = Monitor().scene(820, 600)
    bars = [i for i in items if i.get("type") == "rect"
            and i["height"] == 7 and i["color"] == "#e8c07d"]
    assert bars and all(b["x"] + b["width"] == 550 for b in bars)


# The switch trace reads as a pid sequence, newest last.
def test_switch_trace_renders_pid_sequence(monkeypatch):
    monkeypatch.setattr("apps.guimonitor.fetch_snapshot", lambda: _snap())
    texts = _texts(Monitor().scene(820, 600))
    assert "3 → 4" in texts
    assert any(t.startswith("min_vruntime ") for t in texts)
    monkeypatch.setattr("apps.guimonitor.fetch_snapshot",
                        lambda: _snap(timeline=[]))
    assert "（暂无切换）" in _texts(Monitor().scene(820, 600))


# The RECENT section shows reaped tasks with their final CPU time.
def test_recent_section_renders_and_empty_shows_placeholder(monkeypatch):
    monkeypatch.setattr("apps.guimonitor.fetch_snapshot", lambda: _snap())
    texts = _texts(Monitor().scene(820, 600))
    joined = "\n".join(texts)
    assert "已回收" in texts and "old-task" in joined and "123" in joined
    monkeypatch.setattr("apps.guimonitor.fetch_snapshot", lambda: _snap(recent=[]))
    assert "（空）" in _texts(Monitor().scene(820, 600))


# Failures and empty tables degrade to banners, never tracebacks.
def test_failure_and_empty_degrade_gracefully(monkeypatch):
    monkeypatch.setattr("apps.guimonitor.fetch_snapshot",
                        lambda: {"ok": False, "error": "主机数据失败: 断开",
                                 "tasks": [], "timeline": [], "recent": [],
                                 "rq": {}, "identity": {}})
    assert "主机数据失败: 断开" in _texts(Monitor().scene(820, 600))


# Without a channel the in-process table is read when this process booted it.
def test_fetch_snapshot_falls_back_to_the_local_table(monkeypatch):
    from vortexglass import host as hostmod

    monkeypatch.setattr(hostmod, "is_remote", lambda: False)
    table = P.ProcessTable()
    table.boot_system()
    table.spawn("local-task")
    monkeypatch.setattr("process._pt", table)
    snap = fetch_snapshot()
    assert snap["source"] == "local" and snap["booted"] is True
    assert "local-task" in [t["comm"] for t in snap["tasks"]]


# With no booted table either, the empty shell names the reason.
def test_fetch_snapshot_without_any_table(monkeypatch):
    from vortexglass import host as hostmod

    monkeypatch.setattr(hostmod, "is_remote", lambda: False)
    monkeypatch.setattr("process._pt", P.ProcessTable())
    assert fetch_snapshot()["error"] == "系统未启动"


# A host-side refusal becomes a banner, not a traceback.
def test_fetch_snapshot_reports_host_failure(monkeypatch):
    from vortexglass import host as hostmod

    monkeypatch.setattr(hostmod, "is_remote", lambda: True)
    monkeypatch.setattr(hostmod, "call", lambda op, *a, **k: (False, "UnitError: gone"))
    assert fetch_snapshot()["error"] == "主机数据失败: UnitError: gone"


# The host snapshot and the in-process one come from the same builder, so a
# field added for one cannot go missing for the other. They used to be built
# separately and drifted.
def test_local_and_host_snapshots_share_a_shape(monkeypatch):
    table = P.ProcessTable()
    table.boot_system()
    table.spawn("shape-a", nice=-5)
    monkeypatch.setattr("process._pt", table)
    local = _local_snapshot()
    host = forkexec._sysctl_handler("sm_snapshot", [], {})
    assert set(local) <= set(host), set(local) - set(host)
    assert set(local["rq"]) == set(host["rq"])
    assert set(local["tasks"][0]) == set(host["tasks"][0])


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
    assert row["nice"] == -5
    assert set(row) >= {"pid", "state", "vruntime", "cpu",
                        "weight", "deadline", "lag", "eligible"}
    assert set(snap["rq"]) >= {"runnable", "avg", "min", "switches", "curr_pid",
                               "ticks", "base_slice"}
    assert set(snap["identity"]) >= {"version", "slot", "slot_version", "ota"}
    assert any(r["comm"] == "snap-b" and r["exit"] == 3 for r in snap["recent"])


# Selecting a row opens the nice slider for that task, already at the value the
# task has, so the first thing the user sees is not a stale default.
def test_selecting_a_row_opens_its_nice_slider(monkeypatch):
    from apps import guimonitor

    monkeypatch.setattr("apps.guimonitor.fetch_snapshot", lambda: _snap())
    monkeypatch.setattr(guimonitor, "call", lambda op, *a, **k: (True, _snap()))
    view = Monitor()
    view.scene(820, 560)
    assert view.selected is None
    assert view.handle({"type": "click", "target": "task:4"}) is True
    assert view.selected == 4 and view.nice.value == -5

    texts = _texts(view.scene(820, 560))
    assert any(t.startswith("pid 4") for t in texts)
    # 滑块范围就是 nice 的范围，step 是 1。
    assert (view.nice.minimum, view.nice.maximum, view.nice.step) == (-20, 19, 1)


# A refused nice change is reported, and the slider stays where the user put it
# rather than snapping back behind their back.
def test_refused_nice_change_is_reported(monkeypatch):
    from apps import guimonitor

    monkeypatch.setattr("apps.guimonitor.fetch_snapshot", lambda: _snap())

    def fake(op, *args, **kwargs):
        # 快照照常，只有 set_nice 被拒，才能把失败限定在这一条路径上。
        return (True, _snap()) if op == "sm_snapshot" else (False, "提高进程优先级需要 ROOT")

    monkeypatch.setattr(guimonitor, "call", fake)
    view = Monitor()
    view.scene(820, 560)
    view.handle({"type": "click", "target": "task:4"})
    # 驱动滑块本身（用户就是这么改的），_set_nice 只是它的回调。
    view.nice.set(-15)
    assert "ROOT" in view.message
    # 被拒也不回弹：用户看到原因后还能就着当前值再试。
    assert view.nice.value == -15
