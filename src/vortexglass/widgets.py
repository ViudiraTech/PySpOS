"""Optional text editor, implemented in the application process with public drawing APIs."""

import unicodedata

from .drawing import label, line, rectangle
from .input import KEYS


class TextEditor:
    limit = 65536

    def __init__(self, content=""):
        if len(content) > self.limit:
            raise ValueError("text is larger than 65536 characters")
        self.content, self.cursor = content, len(content)
        self.selected, self.top = False, 0
        self.columns, self.visible_rows = 50, 10
        self.bounds = (0, 0, 1, 1)
        self.undo, self.redo = [], []
        self.ensure_cursor = True

    @staticmethod
    def cells(text):
        return sum(2 if unicodedata.east_asian_width(char) in ("W", "F") else 1 for char in text)

    def rows(self):
        rows, start, value, cells = [], 0, "", 0
        for index, char in enumerate(self.content):
            if char == "\n":
                rows.append((start, value))
                start, value, cells = index + 1, "", 0
                continue
            width = self.cells(char)
            if cells + width > self.columns:
                rows.append((start, value))
                start, value, cells = index, "", 0
            value += char
            cells += width
        rows.append((start, value))
        return rows

    def cursor_row(self, rows):
        return max(index for index, (start, _) in enumerate(rows) if start <= self.cursor)

    def scene(self, x, y, width, height):
        self.bounds = x, y, width, height
        self.columns, self.visible_rows = max(1, (width - 24) // 10), max(1, (height - 20) // 24)
        rows = self.rows()
        current = self.cursor_row(rows)
        if self.ensure_cursor:
            self.top = max(min(self.top, current), current - self.visible_rows + 1)
            self.ensure_cursor = False
        self.top = max(0, min(self.top, max(0, len(rows) - self.visible_rows)))
        items = [rectangle(x, y, width, height, "#143752" if self.selected else "#0b1829de", 8)]
        for index, (_start, value) in enumerate(rows[self.top:self.top + self.visible_rows]):
            item = label(x + 12, y + 10 + index * 24, value, 16)
            item["font"] = "monospace"
            items.append(item)
        if self.top <= current < self.top + self.visible_rows:
            start, value = rows[current]
            cx = x + 12 + self.cells(value[:self.cursor - start]) * 10
            cy = y + 10 + (current - self.top) * 24
            items.append(line(cx, cy, cx, cy + 19, "#9fbeff"))
        return items

    def replace(self, value, start=None, end=None):
        if self.selected:
            start, end = 0, len(self.content)
        else:
            start = self.cursor if start is None else start
            end = self.cursor if end is None else end
        updated = self.content[:start] + value + self.content[end:]
        if len(updated) > self.limit:
            return False
        self.undo.append((self.content, self.cursor))
        self.undo = self.undo[-32:]
        self.redo.clear()
        self.content, self.cursor, self.selected = updated, start + len(value), False
        self.ensure_cursor = True
        return True

    def handle(self, event):
        if event["type"] == "scroll":
            self.top += -3 if event.get("dy", 0) > 0 else 3
            return True
        if event["type"] == "click":
            x, y, width, height = self.bounds
            if not (x <= event.get("x", -1) < x + width and y <= event.get("y", -1) < y + height):
                return False
            rows = self.rows()
            row = max(0, min(len(rows) - 1, self.top + (event["y"] - y - 10) // 24))
            start, value = rows[row]
            column, index = max(0, (event["x"] - x - 12) // 10), 0
            while index < len(value) and self.cells(value[:index + 1]) <= column:
                index += 1
            self.cursor, self.selected = start + index, False
            return True
        if event["type"] != "key":
            return False
        name = event.get("name") or KEYS.get(event.get("key"), event.get("text", ""))
        control = "Control" in event.get("mods", []) or event.get("modifiers", 0) & 0x04000000
        if control:
            if name.upper() == "A":
                self.selected = True
            elif name.upper() in ("Z", "Y"):
                stack, other = (self.undo, self.redo) if name.upper() == "Z" else (self.redo, self.undo)
                if not stack:
                    return False
                other.append((self.content, self.cursor))
                self.content, self.cursor = stack.pop()
                self.selected = False
            else:
                return False
        elif name == "Backspace":
            return self.replace("", max(0, self.cursor - 1), self.cursor)
        elif name == "Delete":
            return self.replace("", self.cursor, min(len(self.content), self.cursor + 1))
        elif name in ("Enter", "Tab"):
            return self.replace("\n" if name == "Enter" else "    ")
        elif name in ("Left", "Right", "Home", "End", "Up", "Down"):
            self.selected = False
            if name == "Left":
                self.cursor = max(0, self.cursor - 1)
            elif name == "Right":
                self.cursor = min(len(self.content), self.cursor + 1)
            elif name == "Home":
                self.cursor = self.content.rfind("\n", 0, self.cursor) + 1
            elif name == "End":
                end = self.content.find("\n", self.cursor)
                self.cursor = len(self.content) if end == -1 else end
            else:
                rows = self.rows()
                current = self.cursor_row(rows)
                column = self.cursor - rows[current][0]
                destination = max(0, min(len(rows) - 1, current + (-1 if name == "Up" else 1)))
                start, value = rows[destination]
                self.cursor = start + min(column, len(value))
        elif event.get("text") and event["text"].isprintable():
            return self.replace(event["text"])
        else:
            return False
        self.ensure_cursor = True
        return True
