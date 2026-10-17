"""Package manager: what is installed, what it provides, and removing it.

The GUI counterpart of the `pkg` command's read side. Installing needs a package
file to point at, which a window with no file picker cannot supply, so the
action here is removal — and that is gated on ROOT in the host, exactly as the
shell command is.
"""

from vortexglass import style
from vortexglass.application import View, run_app
from vortexglass.drawing import button, card, heading, label
from vortexglass.host import call

_TITLE, _TEXT, _DIM = style.TITLE, style.TEXT, style.DIM
_OK, _WARN, _BAD = style.OK, style.WARN, style.BAD

INVISIBLE = "#00000000"

_ROW_HEIGHT = 26
_MAX_ROWS = 7
_LEFT = 20


class Packages(View):
    title, size, background = "PySpOS · 包管理器", (760, 520), style.WINDOW

    min_size = (680, 460)
    interval = 2

    def __init__(self):
        self.selected = None
        self.message = ""
        self.tone = _DIM

    # 列表和详情都来自宿主；卸载同样走宿主，ROOT 判定在那一侧。
    def _remove(self):
        if not self.selected:
            return False
        ok, result = call("pkg_remove", self.selected)
        if ok:
            self.message, self.tone = f"已卸载 {self.selected}", _OK
            self.selected = None
        else:
            self.message, self.tone = f"卸载失败 — {result}", _BAD
        return True

    # 一行一个包：id 贴左，版本和说明跟着，整行可点。空列表时给出怎么装包的
    # 提示——一个空白窗口不会告诉用户下一步做什么。
    def _row(self, package, y, width):
        selected = package["id"] == self.selected
        items = [button(f"pkg:{package['id']}", _LEFT, y - 3, width - 40,
                        _ROW_HEIGHT - 1, "",
                        style.CONTROL_ACTIVE if selected else INVISIBLE)]
        items.extend([
            label(28, y, str(package["id"])[:24], 13, _TEXT),
            label(232, y, str(package.get("version", "?"))[:10], 13, _DIM),
            label(316, y, str(package.get("description", ""))[:40], 13, _DIM),
        ])
        return items

    def _details(self, package, inner):
        top = 320
        entries = package.get("entrypoints") or []
        names = ", ".join(str(entry.get("name", "?")) for entry in entries[:6]) or "—"
        return [
            card(_LEFT, top, inner, 96),
            heading(28, top + 10, f"详情 · {package['id']}"),
            label(28, top + 36, f"版本  {package.get('version', '?')}", 13, _TEXT),
            label(28, top + 58, f"命令  {names}"[:96], 13, _TEXT),
            label(28, top + 78, str(package.get("description", ""))[:96], 12, _DIM),
        ]

    def scene(self, width, height):
        items = [label(_LEFT, 20, "包管理器", 14, _TITLE)]
        ok, packages = call("pkg_list")
        if not ok:
            items.append(card(_LEFT, 66, width - _LEFT * 2, 96))
            items.append(label(_LEFT + style.PAD, 100, str(packages), 14, _BAD))
            return items

        inner = width - _LEFT * 2
        items.append(label(_LEFT, 42, f"已安装 {len(packages)} 个包", 12, _DIM))
        items.append(card(_LEFT, 66, inner, 236))
        items.append(heading(28, 76, "已安装"))

        if not packages:
            items.append(label(28, 116, "尚未安装任何包", 14, _TEXT))
            items.append(label(28, 142, "在 shell 里用 pkg install <文件> 安装", 12, _DIM))
            items.append(label(28, 164, "本窗口负责查看与卸载", 12, _DIM))
            if self.message:
                items.append(label(28, 476, self.message[:96], 12, self.tone))
            return items

        # 选中项先定下来，行的底色跟着它画，否则会慢一帧。
        selected = next((p for p in packages if p["id"] == self.selected), None)
        if selected is None:
            selected = packages[0]
            self.selected = selected["id"]
        for text, x in (("包名", 28), ("版本", 232), ("说明", 316)):
            items.append(label(x, 98, text, 12, _DIM))

        shown = packages[:_MAX_ROWS]
        for index, package in enumerate(shown):
            items.extend(self._row(package, 124 + index * _ROW_HEIGHT, inner))
        if len(packages) > len(shown):
            items.append(label(28, 124 + len(shown) * _ROW_HEIGHT,
                               f"+{len(packages) - len(shown)} more", 12, _DIM))

        detail_ok, detail = call("pkg_info", selected["id"])
        items.extend(self._details(detail if detail_ok and detail else selected, inner))

        items.append(button("remove", _LEFT, 436, 120, 34, "卸载",
                            "#503442e8"))
        items.append(label(_LEFT + 136, 446,
                           "卸载需要 ROOT；LOCKED 模式一律拒绝", 12, _DIM))
        if self.message:
            items.append(label(_LEFT, 486, self.message[:96], 12, self.tone))
        return items

    def handle(self, event):
        if event["type"] != "click":
            return False
        target = event.get("target") or ""
        if target.startswith("pkg:"):
            self.selected = target[len("pkg:"):]
            self.message = ""
            return True
        if target == "remove":
            return self._remove()
        return False


def main(argv=None):
    run_app(Packages, argv)


if __name__ == "__exec__":
    main()
elif __name__ == "__main__":
    import sys
    main(sys.argv[1:])
