"""Service manager: unit states, dependency edges and the boot journal.

Exposes what `systemctl` shows in the shell: src/service_manager.py's units,
their Requires/Wants/After edges, and the journal the init process writes.
"""

from vortexglass import style
from vortexglass.application import View, run_app
from vortexglass.drawing import button, card, heading, label
from vortexglass.host import call

# 面板、分组和间距都走共享词汇：三个应用以前各堆各的面板，于是三套间距。
_TITLE, _TEXT, _DIM = style.TITLE, style.TEXT, style.DIM
_OK, _WARN, _BAD = style.OK, style.WARN, style.BAD

# 生命周期状态到颜色：故障要从一片 idle 里跳出来。
_STATE_COLOR = {"active": _OK, "failed": _BAD,
                "activating": _WARN, "deactivating": _WARN}

# 完全透明但可点击：合成器按坐标命中按钮，应用只拿到 id，所以整行的点击目标
# 就是一个填色全透明的按钮。
INVISIBLE = "#00000000"

_ROW_HEIGHT = 22
_MAX_ROWS = 7
_ACTIONS = (("start", "启动"), ("stop", "停止"), ("restart", "重启"))


class Services(View):
    title, size, background = "PySpOS · 服务管理器", (680, 560), style.WINDOW

    min_size = (600, 500)
    interval = 1

    def __init__(self):
        self.selected = None
        self.message = ""

    # One unit row: name, state, type, description, plus a full-width click
    # target so selecting does not require hitting the text. The highlight is
    # emitted before the text so the labels stay on top of it.
    def _unit_row(self, unit, y, width):
        name = unit["name"]
        state = unit["state"]
        items = [button(f"unit:{name}", 20, y - 3, width - 40, _ROW_HEIGHT - 1,
                        "", INVISIBLE)]
        if name == self.selected:
            items.append({"type": "rect", "x": 20, "y": y - 3, "width": width - 40,
                        "height": _ROW_HEIGHT - 1, "color": style.CONTROL_ACTIVE,
                        "radius": 4})
        items.extend([
            label(28, y, name[:22], 13, _TEXT),
            label(232, y, state, 13, _STATE_COLOR.get(state, _DIM)),
            label(324, y, unit["type"][:9], 13, _DIM),
            label(400, y, str(unit.get("description", ""))[:30], 13, _DIM),
        ])
        return items

    # The selected unit's edges. Empty groups are shown as "—" rather than
    # dropped, so an absent edge is visibly absent.
    def _detail(self, unit, width):
        def joined(key):
            return ", ".join(unit[key]) if unit[key] else "—"

        return [
            card(16, 268, width - 32, 84),
            heading(28, 278, f"依赖 · {unit['name']}"),
            label(28, 302, f"requires: {joined('requires')}"[:96], 13, _TEXT),
            label(28, 324, f"wants: {joined('wants')}"[:96], 13, _TEXT),
            label(360, 302, f"after: {joined('after')}"[:52], 13, _DIM),
            label(360, 324, f"before: {joined('before')}"[:52], 13, _DIM),
        ]

    # Journal tail. The host formats whole lines, so this only truncates and
    # takes the last few: an init journal is append-only and newest-last.
    def _journal(self, width):
        ok, lines = call("sm_journal", self.selected)
        items = [card(16, 364, width - 32, 116),
                 heading(28, 374, "JOURNAL" + (f" · {self.selected}" if self.selected else ""))]
        if not ok:
            items.append(label(28, 398, str(lines)[:90], 13, _BAD))
            return items
        tail = list(lines)[-4:]
        if not tail:
            items.append(label(28, 398, "（暂无日志）", 13, _DIM))
        for index, entry in enumerate(tail):
            items.append(label(28, 398 + index * 20, str(entry)[:96], 12, _DIM))
        return items

    def scene(self, width, height):
        items = [label(20, 16, "SERVICE MANAGER", 14, _TITLE)]
        ok, units = call("sm_status")
        if not ok:
            items.append(card(16, 60, width - 32, 120))
            items.append(label(28, 92, str(units), 14, _BAD))
            return items

        counts = {state: sum(1 for unit in units if unit["state"] == state)
                  for state in ("active", "failed")}
        items.append(label(20, 38,
                           f"共 {len(units)} 个 unit | 激活 {counts['active']}"
                           f" | 故障 {counts['failed']} | 通道 host", 12, _DIM))
        # 选中项要在画行之前定下来：行的底色是跟着它画的，晚一步就慢一帧。
        selected = next((unit for unit in units if unit["name"] == self.selected),
                        None)
        if selected is None:
            selected = units[0] if units else None
            self.selected = selected["name"] if selected else None
        items.append(card(16, 60, width - 32, 196))
        for text, x in (("名称", 28), ("状态", 232), ("类型", 324), ("说明", 400)):
            items.append(label(x, 72, text, 12, _DIM))

        shown = units[:_MAX_ROWS]
        for index, unit in enumerate(shown):
            items.extend(self._unit_row(unit, 98 + index * _ROW_HEIGHT, width))
        if len(units) > len(shown):
            items.append(label(28, 98 + len(shown) * _ROW_HEIGHT,
                               f"+{len(units) - len(shown)} more", 12, _DIM))

        if selected is not None:
            items.extend(self._detail(selected, width))
        items.extend(self._journal(width))

        if self.message:
            items.append(label(20, 492, self.message[:80], 12, _WARN))
        for index, (action, text) in enumerate(_ACTIONS):
            items.append(button(f"act:{action}", 20 + index * 96, 510, 88, 34, text))
        return items

    # Run one lifecycle action on the current selection and keep its outcome on
    # screen; the next 1 Hz repaint already shows the new state.
    def _act(self, action):
        if not self.selected:
            self.message = "先选一个 unit"
            return
        ok, value = call(f"sm_{action}", self.selected)
        self.message = (f"{self.selected}: {action} 成功" if ok
                        else f"{self.selected}: {action} 失败 — {value}")

    def handle(self, event):
        if event["type"] != "click":
            return False
        target = event.get("target") or ""
        if target.startswith("unit:"):
            self.selected = target[len("unit:"):]
            self.message = ""
            return True
        if target.startswith("act:"):
            self._act(target[len("act:"):])
            return True
        return False


def main(argv=None):
    run_app(Services, argv)


if __name__ == "__exec__":
    main()
elif __name__ == "__main__":
    import sys
    main(sys.argv[1:])
