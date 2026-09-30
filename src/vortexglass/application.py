"""Public application SDK: connection-owned surfaces, event dispatch and timers.

Applications own their views and rendering. The compositor never imports them.
Use display lists for small interfaces or present_pixels for arbitrary renderers.
"""

import argparse
import math
import os
from pathlib import Path
import shlex
import time

from .client import Client


class View:
    title = "PySpOS application"
    size = (480, 320)
    min_size = (160, 80)
    background = "#162032e8"
    interval = None

    def on_mount(self, window):
        self.window = window

    def scene(self, width, height):
        return []

    def paint(self, window):
        window.present(self.scene(window.width, window.height))

    def handle(self, event):
        """Return True to request a redraw. Events include their window id."""
        return False


class Surface:
    """An application-owned client area; all dimensions exclude decorations."""

    def __init__(self, app, view, window_id, width, height):
        self.app, self.view, self.id = app, view, window_id
        self.width, self.height = width, height
        self.closed = False
        self.dirty = True
        self.next_tick = None if view.interval is None else time.monotonic() + view.interval

    def invalidate(self):
        self.dirty = True

    def present(self, items, **options):
        return self.app.client.present(self.id, items, **options)

    def present_pixels(self, pixels):
        return self.app.client.present_pixels(self.id, self.width, self.height, pixels)

    def set_title(self, title):
        return self.app.client.set_title(self.id, title)

    def resize(self, width, height):
        result = self.app.client.resize(self.id, width, height)
        self.width, self.height = result["width"], result["height"]
        self.invalidate()

    def close(self):
        if not self.closed:
            self.view.handle({"type": "close", "window": self.id})
            self.app.client.destroy(self.id)
            self.closed = True
            self.app.windows.pop(self.id, None)


class Application:
    def __init__(self, endpoint=None):
        self.client = Client(endpoint)
        self.windows = {}

    def open(self, view, *, title=None, size=None):
        interval = view.interval
        if interval is not None and (not math.isfinite(interval) or interval <= 0):
            raise ValueError("view interval must be finite and positive")
        width, height = size or view.size
        window_id = self.client.create(title or view.title, width, height, view.background,
                                       min_width=view.min_size[0], min_height=view.min_size[1],
                                       events=["pointer", "scroll", "focus"])
        window = Surface(self, view, window_id, width, height)
        self.windows[window_id] = window
        try:
            view.on_mount(window)
        except BaseException:
            window.close()
            raise
        return window

    def dispatch(self, event):
        window = self.windows.get(event.get("window"))
        if window is None:
            return
        if event["type"] == "close":
            window.closed = True
            self.windows.pop(window.id, None)
        elif event["type"] == "resize":
            window.width, window.height = event["width"], event["height"]
            window.invalidate()
        elif ((event["type"] == "click" and event.get("target") == "close")
              or (event["type"] == "key" and event.get("key") == 16777216)):
            window.close()
            return
        if window.view.handle(event):
            window.invalidate()

    def flush(self):
        now = time.monotonic()
        for window in list(self.windows.values()):
            if window.next_tick is not None and now >= window.next_tick:
                window.invalidate()
                window.next_tick = now + window.view.interval
            if window.dirty and not window.closed:
                window.dirty = False
                window.view.paint(window)

    def run(self, duration=None):
        if duration is not None and (not math.isfinite(duration) or not 0 <= duration <= 3600):
            raise ValueError("duration must be in 0..3600 seconds")
        deadline = None if duration is None else time.monotonic() + duration
        self.flush()
        while self.windows:
            now = time.monotonic()
            if deadline is not None and now >= deadline:
                break
            deadlines = [window.next_tick for window in self.windows.values()
                         if window.next_tick is not None]
            if deadline is not None:
                deadlines.append(deadline)
            timeout = max(0, min(deadlines) - now) if deadlines else None
            event = self.client.next_event(timeout)
            if event is not None:
                self.dispatch(event)
            self.flush()

    def close(self):
        try:
            for window in list(self.windows.values()):
                window.view.handle({"type": "close", "window": window.id})
        finally:
            self.client.close()
            for window in self.windows.values():
                window.closed = True
            self.windows.clear()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()


def run_app(factory, argv=None, *, configure=None):
    """Shared CLI/lifecycle only. UI and business logic remain in the app module."""
    parser = argparse.ArgumentParser(description="PySpOS GUI application")
    parser.add_argument("--endpoint")
    parser.add_argument("--capture", help="save a compositor PNG")
    parser.add_argument("--duration", type=float)
    parser.add_argument("--title")
    parser.add_argument("--size", help="WIDTHxHEIGHT")
    if configure:
        configure(parser)
    arguments = shlex.split(os.environ.get("PYSPOS_APP_ARGS", "")) if argv is None else argv
    options = parser.parse_args(arguments)
    if options.duration is not None and (not math.isfinite(options.duration)
                                        or not 0 <= options.duration <= 3600):
        parser.error("duration must be in 0..3600 seconds")
    size = None
    if options.size:
        try:
            width, height = map(int, options.size.lower().split("x"))
            size = (width, height)
        except ValueError:
            parser.error("size must be WIDTHxHEIGHT")
    try:
        view = factory(options) if configure else factory()
        with Application(options.endpoint) as app:
            window = app.open(view, title=options.title, size=size)
            app.flush()
            if options.capture:
                Path(options.capture).write_bytes(app.client.snapshot(window.id))
                if options.duration is None:
                    return
            print(f"{view.title}: window {window.id}, compositor={app.client.info['backend']}", flush=True)
            app.run(options.duration)
    except KeyboardInterrupt:
        return
    except (OSError, ValueError, ConnectionError) as exc:
        raise SystemExit(f"GUI client: {exc}. 请先运行 gui，或指定运行中的 --endpoint。") from exc
