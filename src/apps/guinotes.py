"""A persistent editor whose UI and file operations belong to the application."""

import os
from pathlib import Path
import tempfile

from vortexglass.application import View, run_app
from vortexglass.drawing import button, label
from vortexglass.widgets import TextEditor


class Notes(View):
    title, size, min_size = "PySpOS · Notes", (680, 460), (480, 260)

    def __init__(self, path=None):
        self.path = Path(path).expanduser() if path else Path(os.environ.get(
            "XDG_STATE_HOME", Path.home() / ".local" / "state")) / "pyspos" / "notes.txt"
        try:
            with self.path.open(encoding="utf-8") as stream:
                content = stream.read(TextEditor.limit + 1)
        except FileNotFoundError:
            content = ""
        self.editor = TextEditor(content)
        self.saved = content
        self.status = "Ctrl+S 保存 · Ctrl+Z 撤销 · Ctrl+A 全选"

    @property
    def content(self):
        return self.editor.content

    @content.setter
    def content(self, value):
        self.editor = TextEditor(value)

    def save(self):
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(self.content)
                stream.flush()
                os.fsync(stream.fileno())
            if self.path.exists():
                temporary.chmod(self.path.stat().st_mode & 0o777)
            temporary.replace(self.path)
            self.saved = self.content
            self.status = f"已保存 · {self.path}"
        except OSError as exc:
            self.status = f"保存失败 · {exc}"
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def scene(self, width, height):
        dirty = self.content != self.saved
        items = [label(20, 16, self.path.name[:48] + (" *" if dirty else ""), 16, "#9bc5e9"),
                 button("save", width - 116, 12, 96, 34, "保存")]
        items.extend(self.editor.scene(16, 56, width - 32, height - 112))
        items.append(label(20, height - 42, self.status[:76], 12, "#9bb3cb"))
        items.append(label(20, height - 24, f"{len(self.content)} 字符 · 关闭时自动保存", 12, "#9bb3cb"))
        return items

    def handle(self, event):
        control = "Control" in event.get("mods", []) or event.get("modifiers", 0) & 0x04000000
        if ((event["type"] == "click" and event.get("target") == "save")
                or (event["type"] == "key" and control and event.get("name", "").upper() == "S")
                or (event["type"] == "close" and self.content != self.saved)):
            self.save()
            return True
        changed = self.editor.handle(event)
        if changed:
            self.status = "未保存 · Ctrl+S 保存" if self.content != self.saved else "已保存"
        return changed


def main(argv=None):
    run_app(lambda options: Notes(options.file), argv,
            configure=lambda parser: parser.add_argument("file", nargs="?"))


if __name__ == "__exec__":
    main()
elif __name__ == "__main__":
    import sys
    main(sys.argv[1:])
