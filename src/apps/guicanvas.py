"""Canvas: application-owned interface using the public VortexGlass SDK."""

from vortexglass.application import View, run_app
from vortexglass.drawing import button, label, rectangle
from vortexglass.drawing import line
from pathlib import Path


class Canvas(View):
    title, size, background = "VortexGlass · Transparent canvas", (540, 340), "#00000000"

    min_size = (520, 340)

    def __init__(self):
        self.marks = []
        self.strokes = []
        self.previous = None
        self.status = "拖动绘制 · 点击落笔 · 保存窗口 PNG"
        self.alpha = 144

    def scene(self, _width, height):
        suffix = f"{self.alpha:02x}"
        return [label(22, 18, self.status[:56], 14),
                rectangle(24, 64, 240, 170, "#397aa6" + suffix, 18),
                rectangle(160, 102, 250, 172, "#7358ba" + suffix, 18),
                rectangle(310, 52, 188, 166, "#37a78b" + suffix, 18),
                label(42, 86, "Transparent sketchpad", 22),
                label(42, 126, "Draw with the mouse", 14)] + self.marks + self.strokes + [
                button("alpha", 24, height - 50, 150, 32, f"Alpha: {self.alpha}"),
                button("clear", 184, height - 50, 90, 32, "清空"),
                button("undo", 284, height - 50, 90, 32, "撤销"),
                button("save", 384, height - 50, 130, 32, "保存 PNG")]

    def handle(self, event):
        if event["type"] == "pointer":
            if event["phase"] == "release":
                self.previous = None
            elif event.get("buttons", 0) & 1 and event["y"] >= 52:
                point = (event["x"], event["y"])
                if event["phase"] == "move" and self.previous:
                    self.strokes.append(line(*self.previous, *point, "#fff1b0c0", 4))
                    self.strokes = self.strokes[-128:]
                self.previous = point
                return event["phase"] == "move"
            return False
        if event["type"] != "click":
            return False
        if event.get("target") == "alpha":
            self.alpha = 64 if self.alpha >= 224 else self.alpha + 40
        elif event.get("target") == "clear":
            self.marks.clear()
            self.strokes.clear()
        elif event.get("target") == "undo":
            if self.strokes:
                self.strokes.pop()
            elif self.marks:
                self.marks.pop()
        elif event.get("target") == "save":
            try:
                destination = Path.cwd() / "canvas.png"
                destination.write_bytes(self.window.app.client.snapshot(self.window.id))
                self.status = f"已保存 · {destination}"
            except OSError as exc:
                self.status = f"保存失败 · {exc}"
        elif not event.get("target"):
            self.marks.append(rectangle(event["x"] - 12, event["y"] - 12, 24, 24, "#fff1b0c0", 12))
            self.marks = self.marks[-96:]
        else:
            return False
        return True


def main(argv=None):
    run_app(Canvas, argv)


if __name__ == "__exec__":
    main()
elif __name__ == "__main__":
    import sys
    main(sys.argv[1:])
