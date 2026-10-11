"""Monitor: live PySpOS process and scheduler tables over the public VortexGlass SDK."""

from vortexglass.application import View, run_app
from vortexglass.drawing import button, label, rectangle


# Find the child-side RPC module however this interpreter was launched: the
# main shell and pytest have src/apps/ on the path, desktop children spawned
# with python -m only have src/ (where apps/ is a namespace package).
def _syscall_api():
    try:
        import api
        return api
    except ImportError:
        pass
    try:
        from apps import api as apps_api
        return apps_api
    except ImportError:
        return None


# Empty snapshot shell shared by every failure path, so the view never crashes.
def _blank(error):
    return {"ok": False, "error": error, "source": "?", "booted": False,
            "identity": {"version": "?", "slot": "?", "slot_version": "?",
                         "ota": "?"},
            "rq": {"queued": 0, "avg": 0.0, "min": 0.0, "switches": 0,
                   "ticks": 0, "curr_pid": None, "curr_comm": "-"},
            "tasks": [], "recent": []}


# Snapshot from the in-process table: only meaningful where the table lives
# (the host shell); anywhere else it is honest about being unbooted.
def _local_snapshot():
    try:
        import process as proc
    except ImportError as exc:
        return _blank(f"本地数据不可用: {exc}")
    table = proc._table()
    if not table.is_booted():
        return _blank("系统未启动")
    rq = table.rq
    curr = rq.curr
    return {"ok": True, "source": "local", "booted": True,
            "identity": {"version": "?", "slot": "?", "slot_version": "?",
                         "ota": "?"},
            "rq": {"queued": len(rq._queued), "avg": rq.avg_vruntime(),
                   "min": rq.min_vruntime, "switches": rq.nr_switches,
                   "ticks": rq.nr_ticks,
                   "curr_pid": curr.pid if curr is not None else None,
                   "curr_comm": curr.comm if curr is not None else "-"},
            "tasks": [{"pid": p.pid, "ppid": p.ppid, "comm": p.comm,
                       "state": p.state, "nice": p.nice,
                       "vruntime": p.vruntime, "cpu": p.sum_exec_runtime,
                       "kind": p.kind, "remote": bool(p.remote)}
                      for p in table.list_procs()],
            "recent": list(table.recent),
            "error": ""}


# Fetch the live snapshot: the host's over RPC when a channel exists, else
# the in-process table. Never raises; failures become a banner row.
def fetch_snapshot():
    api = _syscall_api()
    if api is not None and api.is_remote():
        try:
            res = api._call("sm_snapshot")
        except Exception as exc:
            return _blank(f"主机数据失败: {exc}")
        if res is None:
            return _blank("主机数据通道不可用")
        ok, val = res
        if not ok:
            return _blank(f"主机数据失败: {val}")
        snap = dict(val)
        snap["source"] = "host"
        return snap
    return _local_snapshot()


# ps-style state letters; unknown states keep their initial.
_STATES = {"Running": "R", "Sleeping": "S", "Stopped": "T",
           "Zombie": "Z", "Dead": "X"}

_TITLE = "#9bc5e9"
_TEXT = "#e6edf3"
_DIM = "#8b949e"
_HL = "#86cd9a"


class Monitor(View):
    title, size, background = "PySpOS · System Monitor", (560, 470), "#132033ec"

    min_size = (480, 400)
    interval = 1

    def scene(self, width, height):
        snap = fetch_snapshot()
        items = [label(20, 16, "SYSTEM MONITOR", 14, _TITLE)]
        if not snap["ok"]:
            items.append(rectangle(16, 54, width - 32, 120, "#0b1829de", 8))
            items.append(label(28, 92, snap["error"] or "数据不可用", 14))
            return items
        ident = snap["identity"]
        items.append(label(20, 38,
                           f"PySpOS {ident['version']} | 槽位 {ident['slot']}"
                           f"({ident['slot_version']}) | OTA{ident['ota']}",
                           12, _DIM))
        recent = snap.get("recent", [])
        recent_rows = min(3, len(recent)) if recent else 1
        recent_h = 22 + recent_rows * 22 + 8
        proc_bottom = height - 64 - recent_h
        items.extend(self._proc_table(snap, width, proc_bottom))
        items.extend(self._recent_table(recent, width, height - 64 - recent_h))
        items.extend(self._sched_strip(snap, width, height))
        return items

    # Process table with fixed x columns and truncation, so rows line up
    # without needing a monospace font. bottom is where the table must end
    # to leave room for the sections below it.
    def _proc_table(self, snap, width, bottom):
        header_y, first_y, row_h = 64, 88, 22
        cols = (("PID", 20), ("ST", 72), ("NICE", 112), ("VRUNTIME", 162),
                ("CPU", 248), ("CMD", 328))
        items = [rectangle(16, 54, width - 32, max(10, bottom - 54), "#0b1829de", 8)]
        items.extend(label(x, header_y, name, 12, _DIM) for name, x in cols)
        tasks = snap["tasks"]
        curr_pid = snap["rq"]["curr_pid"]
        room = max(1, (bottom - first_y) // row_h)
        clipped = len(tasks) > room
        shown = tasks[:room - 1] if clipped and room > 1 else tasks[:room]
        y = first_y
        for task in shown:
            color = _HL if task["pid"] == curr_pid else _TEXT
            state = _STATES.get(task["state"], (task["state"] or "?")[:1])
            items.append(label(20, y, f"{task['pid']:>5}", 13, color))
            items.append(label(72, y, state, 13, color))
            items.append(label(112, y, f"{task['nice']:>4}", 13, color))
            items.append(label(162, y, f"{task['vruntime']:>8.1f}", 13, color))
            items.append(label(248, y, f"{task['cpu']:>7.0f}", 13, color))
            items.append(label(328, y, str(task["comm"])[:20], 13, color))
            y += row_h
        if clipped:
            items.append(label(28, y, f"+{len(tasks) - len(shown)} more", 12, _DIM))
        return items

    # Recently reaped tasks with the CPU time they took to the grave: without
    # this, zombies reaped in the same command that waited for them would be
    # invisible to a 1 Hz monitor.
    def _recent_table(self, recent, width, top):
        items = [label(20, top, "RECENT", 12, _DIM)]
        if not recent:
            items.append(label(28, top + 24, "(空)", 12, _DIM))
            return items
        items.append(label(110, top, "EXIT", 12, _DIM))
        items.append(label(180, top, "CPU", 12, _DIM))
        items.append(label(260, top, "CMD", 12, _DIM))
        y = top + 24
        for record in recent[:3]:
            exit_text = f"sig{record['sig']}" if record["sig"] else f"{record['exit']}"
            items.append(label(20, y, f"{record['pid']:>5}", 13))
            items.append(label(110, y, exit_text, 13))
            items.append(label(180, y, f"{record['cpu']:>7.0f}", 13))
            items.append(label(260, y, str(record["comm"])[:24], 13))
            y += 22
        return items

    # One-glance scheduler estimators under the table.
    def _sched_strip(self, snap, width, height):
        rq = snap["rq"]
        y = height - 64
        return [label(20, y,
                      f"runnable {rq['queued']} | curr {rq['curr_pid']}/"
                      f"{rq['curr_comm']} | 切换 {rq['switches']} | "
                      f"tick {rq.get('ticks', 0)}", 12, _DIM),
                label(20, y + 22,
                      f"avg_vruntime {rq['avg']:.2f} | "
                      f"min_vruntime {rq['min']:.2f}", 12, _DIM)]

    def handle(self, _event):
        return False


def main(argv=None):
    run_app(Monitor, argv)


if __name__ == "__exec__":
    main()
elif __name__ == "__main__":
    import sys
    main(sys.argv[1:])
