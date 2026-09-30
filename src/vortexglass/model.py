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
import base64
import binascii
import copy
from dataclasses import dataclass, field
import re
import threading

from .protocol import ProtocolError

MAX_WINDOWS = 32
MAX_OWNER_WINDOWS = 8
MAX_TOTAL_PIXELS = 8_000_000
MAX_ITEMS = 256
BUFFER_CHUNK = 64 * 1024
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
            font = item.get("font", "sans-serif")
            if font not in ("sans-serif", "monospace"):
                raise ProtocolError("font must be sans-serif or monospace")
            out["font"] = font
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
    input_events: tuple = ()
    min_width: int = 160
    min_height: int = 80
    pixels: bytes | None = None
    pixel_size: tuple = ()


@dataclass
class Upload:
    id: int
    window: int
    width: int
    height: int
    data: bytearray = field(default_factory=bytearray)


class Compositor:
    def __init__(self, changed=None):
        self.lock = threading.RLock()
        self.windows = {}
        self.next_id = 1
        self.uploads = {}
        self.next_upload = 1
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
            min_width = integer(message.get("min_width", 160), "min_width", 160, width)
            min_height = integer(message.get("min_height", 80), "min_height", 80, height)
            events = message.get("events", [])
            if (not isinstance(events, list) or len(events) > 3
                    or any(event not in ("pointer", "scroll", "focus") for event in events)):
                raise ProtocolError("events must contain pointer, scroll or focus")
            window = Window(self.next_id, owner,
                            text(message.get("title", "PySpOS"), "title", 256),
                            width, height, colour(message.get("background", "#162032e8")),
                            input_events=tuple(events), min_width=min_width, min_height=min_height)
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
            window.pixels = None
            window.pixel_size = ()
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
            if width < window.min_width or height < window.min_height:
                raise ProtocolError("size is below the application's minimum")
            window.width, window.height = width, height
            window.revision += 1
            self.changed(window.id)
            return {"width": width, "height": height}

    def set_title(self, owner, message):
        title = text(message.get("title"), "title", 256)
        with self.lock:
            window = self._owned(owner, message.get("window"))
            window.title = title
            window.revision += 1
            self.changed(window.id)
            return {}

    def buffer_begin(self, owner, message):
        """One bounded staging buffer per connection; no client filesystem access."""
        with self.lock:
            window = self._owned(owner, message.get("window"))
            if owner in self.uploads:
                raise ProtocolError("cancel or commit the current buffer first")
            width = integer(message.get("width"), "width", 160, 1600)
            height = integer(message.get("height"), "height", 80, 1200)
            if (width, height) != (window.width, window.height):
                raise ProtocolError("buffer size must match the window")
            if message.get("format") != "rgba8888":
                raise ProtocolError("buffer format must be rgba8888")
            pixels = sum(upload.width * upload.height for upload in self.uploads.values())
            if pixels + width * height > MAX_TOTAL_PIXELS:
                raise ProtocolError("staging buffer budget exhausted")
            upload = Upload(self.next_upload, window.id, width, height)
            self.next_upload += 1
            self.uploads[owner] = upload
            return {"buffer": upload.id, "chunk_size": BUFFER_CHUNK}

    def _upload(self, owner, message):
        buffer_id = integer(message.get("buffer"), "buffer", 1, 2**53)
        upload = self.uploads.get(owner)
        if upload is None or upload.id != buffer_id:
            raise ProtocolError("buffer does not belong to this connection")
        return upload

    def buffer_write(self, owner, message):
        encoded = message.get("data")
        if not isinstance(encoded, str) or len(encoded) > (BUFFER_CHUNK + 2) // 3 * 4:
            raise ProtocolError("invalid buffer chunk size")
        try:
            data = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ProtocolError("invalid base64 buffer chunk") from exc
        if not 0 < len(data) <= BUFFER_CHUNK:
            raise ProtocolError("invalid buffer chunk size")
        with self.lock:
            upload = self._upload(owner, message)
            offset = integer(message.get("offset"), "offset", 0, MAX_TOTAL_PIXELS * 4)
            if offset != len(upload.data):
                raise ProtocolError("buffer chunks must be sequential")
            if offset + len(data) > upload.width * upload.height * 4:
                raise ProtocolError("buffer chunk exceeds declared size")
            upload.data.extend(data)
            return {"offset": len(upload.data)}

    def buffer_commit(self, owner, message):
        with self.lock:
            upload = self._upload(owner, message)
            window = self._owned(owner, upload.window)
            if len(upload.data) != upload.width * upload.height * 4:
                raise ProtocolError("buffer is incomplete")
            if (upload.width, upload.height) != (window.width, window.height):
                raise ProtocolError("window resized during upload; redraw the buffer")
            window.pixels = bytes(upload.data)
            window.pixel_size = (upload.width, upload.height)
            window.items = []
            window.revision += 1
            del self.uploads[owner]
            self.changed(window.id)
            return {"revision": window.revision}

    def buffer_cancel(self, owner, message):
        with self.lock:
            self._upload(owner, message)
            del self.uploads[owner]
            return {}

    def destroy(self, owner, window_id):
        with self.lock:
            window = self._owned(owner, window_id)
            del self.windows[window.id]
            if owner in self.uploads and self.uploads[owner].window == window.id:
                del self.uploads[owner]
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
