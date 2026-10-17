"""Scheduler visualiser: EEVDF lag, virtual deadlines and the recent switch trace.

Shows what src/process.py actually decides with rather than a generic process
list: every task's lag — vruntime minus the run queue average, which is exactly
the eligibility test — the virtual deadline its slice buys, and the sequence of
recent switches. Selecting a row opens a nice slider, so the effect of a weight
change on the lag bars is visible in the same window.
"""

from vortexglass import style
from vortexglass.application import View, run_app
from vortexglass.controls import Slider, route
from vortexglass.drawing import button, card, divider, heading, label
from vortexglass.host import call

# 托盘和面板共用的别名，读起来短一些。
_TITLE, _TEXT, _DIM = style.TITLE, style.TEXT, style.DIM
_OK, _WARN, _BAD = style.OK, style.WARN, style.BAD
_PANEL = style.CARD

# lag 条的零点在队列均值上：向右是欠 CPU，向左是超前。
_BAR_X, _BAR_W = 400, 300
_BAR_CENTER = _BAR_X + _BAR_W // 2
_BAR_TRACK = "#0e1d2f"
_BAR_AXIS = "#3a5570"

_ROW_HEIGHT = 24
_TABLE_TOP, _TABLE_HEAD = 160, 194
_SWITCH_HEIGHT, _RECENT_HEIGHT = 76, 108
_GAP = 10
_BOTTOM_MARGIN = 20
_RUNQUEUE_TOP, _RUNQUEUE_HEIGHT = 58, 92

NICE_MIN, NICE_MAX = -20, 19

# 任务状态到单字母，未知状态保留首字母。
_STATES = {"Running": "R", "Sleeping": "S", "Stopped": "T",
           "Zombie": "Z", "Dead": "X"}


# Compute the vertical layout for one window height: the two lower panels sit on
# the bottom edge and the table gets the remainder.
def _layout(height):
    recent_y = height - _BOTTOM_MARGIN - _RECENT_HEIGHT
    switches_y = recent_y - _GAP - _SWITCH_HEIGHT
    table_bottom = switches_y - _GAP
    rows = max(1, (table_bottom - _TABLE_HEAD) // _ROW_HEIGHT)
    return {"recent": recent_y, "switches": switches_y,
            "table": max(1, table_bottom - _TABLE_TOP), "rows": rows}


# Empty snapshot shell shared by every failure path, so the view never crashes.
def _blank(error):
    return {"ok": False, "error": error, "source": "?", "booted": False,
            "identity": {"version": "?", "slot": "?", "slot_version": "?",
                         "ota": "?"},
            "rq": {"runnable": 0, "avg": 0.0, "min": 0.0, "switches": 0, "ticks": 0,
                   "base_slice": 0.0, "curr_pid": None, "curr_comm": "-"},
            "timeline": [], "tasks": [], "recent": []}


# The in-process table, for a GUI app run without a host channel. Only carries
# state where this process is the one that booted it.
def _local_snapshot():
    try:
        import process as proc
    except ImportError as exc:
        return _blank(f"本地数据不可用: {exc}")
    table = proc._table()
    if not table.is_booted():
        return _blank("系统未启动")
    return {"ok": True, "source": "local", "error": "", **table.snapshot()}


# The host's snapshot over RPC, falling back to the in-process table.
def fetch_snapshot():
    from vortexglass import host
    if not host.is_remote():
        return _local_snapshot()
    ok, value = host.call("sm_snapshot")
    if not ok:
        return _blank(f"主机数据失败: {value}")
    snap = dict(value)
    snap["source"] = "host"
    return snap


class Monitor(View):
    title, size, background = "PySpOS · 调度器", (820, 560), style.WINDOW

    min_size = (720, 520)
    interval = 1

    def __init__(self):
        self.selected = None
        self.message = ""
        self.tone = _DIM
        self.nice = Slider(NICE_MIN, NICE_MAX, 0, label_width=34,
                           on_change=self._set_nice)

    # 改 nice 走宿主，权限判定也在宿主：降优先级随时可以，抬优先级要 ROOT。
    def _set_nice(self, value):
        if self.selected is None:
            return
        ok, result = call("set_nice", self.selected, value)
        if ok:
            self.message, self.tone = f"pid {self.selected} nice={value}", _OK
        else:
            self.message, self.tone = f"nice 调整失败 — {result}", _BAD

    def scene(self, width, height):
        snap = fetch_snapshot()
        items = [label(20, 16, "EEVDF SCHEDULER", 14, _TITLE)]
        if not snap["ok"]:
            items.append(card(16, _RUNQUEUE_TOP, width - 32, 96))
            items.append(label(28, 92, snap["error"] or "数据不可用", 14, _BAD))
            return items
        ident = snap["identity"]
        items.append(label(20, 38,
                           f"PySpOS {ident['version']} | 槽位 {ident['slot']}"
                           f"({ident['slot_version']}) | OTA{ident['ota']}",
                           12, _DIM))
        layout = _layout(height)
        items.extend(self._runqueue(snap, width))
        items.extend(self._task_table(snap, width, layout))
        items.extend(self._switches(snap, width, layout["switches"]))
        items.extend(self._recent(snap, width, layout["recent"]))
        return items

    # 运行队列聚合量，外加选中任务的 nice 滑块——改权重能当场看到 lag 条移动。
    def _runqueue(self, snap, width):
        rq = snap["rq"]
        items = [
            card(16, _RUNQUEUE_TOP, width - 32, _RUNQUEUE_HEIGHT),
            label(28, 68, f"runnable {rq['runnable']} | curr {rq['curr_pid']}/"
                          f"{rq['curr_comm']} | 切换 {rq['switches']} | "
                          f"tick {rq['ticks']}", 12, _TEXT),
            label(28, 90, f"avg_vruntime {rq['avg']:.2f} | "
                          f"min_vruntime {rq['min']:.2f} | "
                          f"base_slice {rq['base_slice']:.1f}ms", 12, _DIM),
        ]
        task = next((t for t in snap["tasks"] if t["pid"] == self.selected), None)
        if task is None:
            items.append(label(28, 120, "选中一行以调整其 nice 值", 12, _DIM))
            return items
        items.append(label(28, 120, f"pid {task['pid']} {str(task['comm'])[:14]}"
                                    f"  权重 {task['weight']}", 12, _TEXT))
        items.extend(self.nice.scene(300, 116, 190, 24))
        if self.message:
            items.append(label(510, 120, self.message[:40], 12, self.tone))
        return items

    # 任务表。每行都是点击目标，选中后上方出现该任务的 nice 滑块。lag 条的长度
    # 按全场最大 |lag| 归一，所以行与行之间可以直接比长度。
    def _task_table(self, snap, width, layout):
        items = [card(16, _TABLE_TOP, width - 32, layout["table"])]
        for text, x in (("PID", 28), ("ST", 74), ("CMD", 104), ("NICE", 212),
                        ("WEIGHT", 250), ("VRUNTIME", 310)):
            items.append(label(x, 172, text, 12, _DIM))
        items.append(label(_BAR_X, 172, "LAG（相对 avg_vruntime）", 12, _DIM))
        items.append(label(712, 172, "DEADLINE", 12, _DIM))

        tasks = snap["tasks"]
        lags = [abs(task["lag"]) for task in tasks if task.get("lag") is not None]
        scale = max(lags, default=1.0) or 1.0
        shown = tasks[:layout["rows"]]
        y = _TABLE_HEAD
        for task in shown:
            items.extend(self._task_row(task, y, snap["rq"]["curr_pid"], scale))
            y += _ROW_HEIGHT
        if len(tasks) > len(shown):
            items.append(label(28, y, f"+{len(tasks) - len(shown)} more", 12, _DIM))
        return items

    def _task_row(self, task, y, curr_pid, scale):
        current = task["pid"] == curr_pid
        color = _OK if current else _TEXT
        # 选中行铺一层底色，未选中的也保留整行点击目标。
        items = [button(f"task:{task['pid']}", 20, y - 3, 780, _ROW_HEIGHT - 1, "",
                        style.CONTROL_ACTIVE if task["pid"] == self.selected
                        else "#00000000")]
        items.extend([
            label(28, y, f"{task['pid']:>5}", 13, color),
            label(74, y, _STATES.get(task["state"], (task["state"] or "?")[:1]), 13, color),
            label(104, y, str(task["comm"])[:14], 13, color),
            label(212, y, f"{task['nice']:>4}", 13, color),
            label(250, y, f"{task['weight']:>6}", 13, color),
            label(310, y, f"{task['vruntime']:>9.2f}", 13, color),
        ])
        items.extend(self._lag_bar(task.get("lag"), y, scale))
        items.append(label(712, y, f"{task['deadline']:>9.2f}", 13, color))
        return items

    # 零点在中间的条：lag >= 0 向右用能跑的绿色，lag < 0 向左。不在队列里的任务
    # 没有 lag，只画空轨道。
    def _lag_bar(self, lag, y, scale):
        items = [{"type": "rect", "x": _BAR_X, "y": y + 8, "width": _BAR_W,
                  "height": 7, "color": _BAR_TRACK, "radius": 3},
                 {"type": "rect", "x": _BAR_CENTER, "y": y + 5, "width": 1,
                  "height": 13, "color": _BAR_AXIS, "radius": 0}]
        if lag is None:
            return items
        extent = max(2, int(abs(lag) / scale * (_BAR_W // 2 - 4)))
        start = _BAR_CENTER if lag >= 0 else _BAR_CENTER - extent
        items.append({"type": "rect", "x": start, "y": y + 8, "width": extent,
                      "height": 7, "color": _OK if lag >= 0 else _WARN, "radius": 3})
        return items

    # 最近的调度轨迹：每次切换记一条 (min_vruntime, pid, 说明)。
    def _switches(self, snap, width, top):
        entries = snap.get("timeline", [])
        items = [card(16, top, width - 32, _SWITCH_HEIGHT),
                 heading(28, top + 10, "最近的调度")]
        if not entries:
            items.append(label(28, top + 34, "（暂无切换）", 12, _DIM))
            return items
        items.append(label(28, top + 34,
                           " → ".join(str(entry[1]) for entry in entries[-18:])[:96],
                           13, _OK))
        last = entries[-1]
        items.append(label(28, top + 56, f"min_vruntime {last[0]:.2f} | {last[2]}"[:96],
                           12, _DIM))
        return items

    # 已回收的任务和它们带走的 CPU 时间：同一条命令里被 wait 掉的僵尸进程，
    # 1 Hz 的监视器否则根本看不到。
    def _recent(self, snap, width, top):
        recent = snap.get("recent", [])
        items = [card(16, top, width - 32, _RECENT_HEIGHT),
                 heading(28, top + 10, "已回收")]
        if not recent:
            items.append(label(28, top + 34, "（空）", 12, _DIM))
            return items
        for text, x in (("EXIT", 110), ("CPU", 180), ("CMD", 260)):
            items.append(label(x, top + 10, text, 12, _DIM))
        y = top + 34
        for record in recent[:3]:
            exit_text = f"sig{record['sig']}" if record["sig"] else f"{record['exit']}"
            items.append(label(28, y, f"{record['pid']:>5}", 13))
            items.append(label(110, y, exit_text, 13))
            items.append(label(180, y, f"{record['cpu']:>7.0f}", 13))
            items.append(label(260, y, str(record["comm"])[:24], 13))
            y += 22
        return items

    # 指针先给滑块（拖动要靠它），点选行再交给平台的按钮目标。
    def handle(self, event):
        if route([self.nice], event):
            return True
        if event["type"] != "click":
            return False
        target = event.get("target") or ""
        if target.startswith("task:"):
            pid = int(target[5:])
            if pid == self.selected:
                return False
            self.selected = pid
            self.message = ""
            ok, value = call("sm_snapshot")
            if ok:
                task = next((t for t in value["tasks"] if t["pid"] == pid), None)
                if task is not None:
                    self.nice.set(task["nice"])
            return True
        return False


def main(argv=None):
    run_app(Monitor, argv)


if __name__ == "__exec__":
    main()
elif __name__ == "__main__":
    import sys
    main(sys.argv[1:])
