'''
 *
 *      model.py
 *      Window ownership and validated display lists, independent of the GUI backend.
 *
 *      2026/9/27 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

from collections import deque
import copy
from dataclasses import dataclass, field
import re
import threading

from .protocol import ProtocolError

MAX_WINDOWS = 32
MAX_OWNER_WINDOWS = 8
MAX_TOTAL_PIXELS = 8_000_000
MAX_ITEMS = 256
COLOUR = re.compile(r"#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?\Z")


def integer(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ProtocolError(f"{name} must be an integer in {low}..{high}")
    return value


def colour(value):
    if not isinstance(value, str) or not COLOUR.fullmatch(value):
        raise ProtocolError("colour must be #RRGGBB or #RRGGBBAA")
    return value


def text(value, name, limit):
    if not isinstance(value, str) or len(value) > limit:
        raise ProtocolError(f"{name} must be text of at most {limit} characters")
    return value


def validate_scene(items):
    if not isinstance(items, list) or len(items) > MAX_ITEMS:
        raise ProtocolError(f"scene must contain at most {MAX_ITEMS} items")
    validated = []
    targets = set()
    for item in items:
        if not isinstance(item, dict):
            raise ProtocolError("scene item must be an object")
        kind = item.get("type")
        if kind not in ("rect", "text", "button", "line"):
            raise ProtocolError("unknown scene item type")
        out = {"type": kind, "x": integer(item.get("x", 0), "x", -4096, 4096),
               "y": integer(item.get("y", 0), "y", -4096, 4096)}
        out["color"] = colour(item.get("color", "#e6edf3"))
        if kind in ("rect", "button"):
            out["width"] = integer(item.get("width"), "width", 1, 4096)
            out["height"] = integer(item.get("height"), "height", 1, 4096)
            out["radius"] = integer(item.get("radius", 0), "radius", 0, 100)
        if kind in ("text", "button"):
            out["text"] = text(item.get("text", ""), "text", 2048)
            out["size"] = integer(item.get("size", 14), "size", 6, 72)
        if kind == "button":
            target = text(item.get("id"), "button id", 64)
            if not target or target in targets:
                raise ProtocolError("button ids must be nonempty and unique")
            targets.add(target)
            out["id"] = target
            out["foreground"] = colour(item.get("foreground", "#ffffff"))
        if kind == "line":
            out["x2"] = integer(item.get("x2"), "x2", -4096, 4096)
            out["y2"] = integer(item.get("y2"), "y2", -4096, 4096)
            out["width"] = integer(item.get("width", 1), "line width", 1, 32)
        validated.append(out)
    return validated


@dataclass
class Window:
    id: int
    owner: int
    title: str
    width: int
    height: int
    background: str
    items: list = field(default_factory=list)
    revision: int = 0
    visible: bool = True


class Compositor:
    def __init__(self, changed=None):
        self.lock = threading.RLock()
        self.windows = {}
        self.next_id = 1
        self.changed = changed or (lambda _window_id: None)
        # Diagnostic history is bounded; it is never the input delivery queue.
        self.history = deque(maxlen=64)

    def _owned(self, owner, window_id):
        integer(window_id, "window", 1, 2**53)
        window = self.windows.get(window_id)
        if window is None or window.owner != owner:
            raise ProtocolError("window does not belong to this connection")
        return window

    def _size(self, width, height, replacing=None):
        integer(width, "width", 160, 1600)
        integer(height, "height", 80, 1200)
        pixels = sum(w.width * w.height for w in self.windows.values()
                     if w.id != replacing)
        if pixels + width * height > MAX_TOTAL_PIXELS:
            raise ProtocolError("compositor pixel budget exhausted")

    def create(self, owner, message):
        with self.lock:
            if len(self.windows) >= MAX_WINDOWS or sum(
                    w.owner == owner for w in self.windows.values()) >= MAX_OWNER_WINDOWS:
                raise ProtocolError("window limit reached")
            width, height = message.get("width", 480), message.get("height", 320)
            self._size(width, height)
            window = Window(self.next_id, owner,
                            text(message.get("title", "PySpOS"), "title", 256),
                            width, height, colour(message.get("background", "#162032e8")))
            self.next_id += 1
            self.windows[window.id] = window
            self.changed(window.id)
            return {"window": window.id, "width": width, "height": height}

    def present(self, owner, message):
        items = validate_scene(message.get("items"))
        background = colour(message["background"]) if "background" in message else None
        with self.lock:
            window = self._owned(owner, message.get("window"))
            window.items = items
            if background is not None:
                window.background = background
            window.revision += 1
            self.changed(window.id)
            return {"revision": window.revision}

    def resize(self, owner, message):
        with self.lock:
            window = self._owned(owner, message.get("window"))
            width, height = message.get("width"), message.get("height")
            self._size(width, height, window.id)
            window.width, window.height = width, height
            window.revision += 1
            self.changed(window.id)
            return {"width": width, "height": height}

    def destroy(self, owner, window_id):
        with self.lock:
            window = self._owned(owner, window_id)
            del self.windows[window.id]
            self.changed(window.id)
            return {}

    def disconnect(self, owner):
        with self.lock:
            for window_id in [w.id for w in self.windows.values() if w.owner == owner]:
                self.destroy(owner, window_id)

    def snapshot(self, window_id):
        with self.lock:
            window = self.windows.get(window_id)
            return copy.deepcopy(window) if window else None

    def owned_snapshot(self, owner, window_id):
        with self.lock:
            self._owned(owner, window_id)
            return self.snapshot(window_id)

    def button_at(self, window_id, x, y):
        with self.lock:
            window = self.windows.get(window_id)
            if window:
                for item in reversed(window.items):
                    if (item["type"] == "button" and item["x"] <= x < item["x"] + item["width"]
                            and item["y"] <= y < item["y"] + item["height"]):
                        return item["id"]
        return None
