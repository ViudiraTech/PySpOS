"""A paginated file browser that opens text files in application-owned editor windows."""

from pathlib import Path

from vortexglass.application import View, run_app
from vortexglass.drawing import button, label, rectangle


class Files(View):
    title, size, min_size = "PySpOS · Files", (700, 480), (540, 300)

    def __init__(self, path=None):
        self.directory = Path(path).expanduser().resolve() if path else Path.home()
        self.entries, self.history, self.offset = [], [], 0
        self.page_size, self.status = 10, ""
        self.refresh()

    def refresh(self):
        try:
            self.entries = sorted(self.directory.iterdir(), key=lambda entry:
                                  (not entry.is_dir(), entry.name.casefold()))
            self.status = "点击目录进入 · 点击 UTF-8 文本文件编辑"
        except OSError as exc:
            self.entries, self.status = [], str(exc)
        self.offset = min(self.offset, max(0, len(self.entries) - self.page_size))

    def navigate(self, directory):
        self.history.append(self.directory)
        self.directory, self.offset = directory, 0
        self.refresh()

    def scene(self, width, height):
        self.page_size = max(1, (height - 160) // 28)
        items = [label(20, 16, "FILES", 14, "#9bc5e9"),
                 button("back", width - 280, 10, 80, 34, "返回"),
                 button("up", width - 190, 10, 80, 34, "上级"),
                 button("refresh", width - 100, 10, 80, 34, "刷新"),
                 rectangle(16, 54, width - 32, height - 118, "#0b1829de", 8),
                 label(26, 62, str(self.directory)[-72:], 13, "#aed0ee")]
        for index, entry in enumerate(self.entries[self.offset:self.offset + self.page_size]):
            icon = "▣" if entry.is_dir() else "▤"
            items.append(button(f"entry:{self.offset + index}", 26, 90 + index * 28,
                                width - 52, 25, f"{icon}  {entry.name[:62]}", "#254058bd"))
        items.extend([button("previous", 16, height - 54, 80, 30, "上一页"),
                      button("next", 106, height - 54, 80, 30, "下一页"),
                      label(206, height - 50, f"{self.offset + 1 if self.entries else 0}–"
                            f"{min(len(self.entries), self.offset + self.page_size)} / {len(self.entries)} 项", 13),
                      label(20, height - 22, self.status[:80], 12, "#9bb3cb")])
        return items

    def handle(self, event):
        target = event.get("target")
        if event["type"] == "scroll":
            target = "previous" if event.get("dy", 0) > 0 else "next"
        elif event["type"] != "click":
            return False
        if target == "up":
            self.navigate(self.directory.parent)
        elif target == "back":
            if self.history:
                self.directory, self.offset = self.history.pop(), 0
                self.refresh()
        elif target == "refresh":
            self.refresh()
        elif target in ("previous", "next"):
            self.offset = max(0, min(max(0, len(self.entries) - self.page_size), self.offset +
                                    (-self.page_size if target == "previous" else self.page_size)))
        elif target and target.startswith("entry:"):
            try:
                entry = self.entries[int(target.split(":", 1)[1])]
                if entry.is_dir():
                    self.navigate(entry)
                elif entry.is_file():
                    from apps.guinotes import Notes
                    self.window.app.open(Notes(entry), title=f"Notes · {entry.name}")
                    self.status = f"已打开 · {entry.name}"
                else:
                    self.status = "此文件类型不能编辑"
            except (OSError, UnicodeError, ValueError, IndexError) as exc:
                self.status = f"无法打开 · {exc}"
        else:
            return False
        return True


def main(argv=None):
    run_app(lambda options: Files(options.directory), argv,
            configure=lambda parser: parser.add_argument("directory", nargs="?"))


if __name__ == "__exec__":
    main()
elif __name__ == "__main__":
    import sys
    main(sys.argv[1:])
