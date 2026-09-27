'''
 *
 *      check_vortexglass_desktop.py
 *      GPU desktop review with real PTY input, live sampling and window controls.
 *
 *      2026/9/27 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import json
import os
from pathlib import Path
import sys
import threading
import time

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from PyQt6.QtCore import QObject, QUrl
from PyQt6.QtWidgets import QApplication

import spaceglass_theme as theme
from vortexglass.client import Client
from vortexglass.quick_backend import Backend
from vortexglass.server import Server


# Run through the normal Qt event queue and fail with a bounded diagnostic timeout.
def spin(app, predicate, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("desktop review timed out")


# Repeater delegates belong to the visual tree, which differs from QObject ownership.
def items(root):
    yield root
    for child in root.childItems():
        yield from items(child)


# Review the actual Qt Quick render target; socket PNG captures remain sharp foregrounds.
def review(output, theme_dir=None):
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication(["VortexGlass desktop review"])
    server = Server(output / "endpoint.json", backend="qt-quick")
    backend = Backend(server, theme.load_theme(theme_dir) if theme_dir else None)
    server.open()
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    backend.view.show()
    backend.openTerminal()
    clients = []
    try:
        spin(app, lambda: bool(backend.terminals) and bool(backend.model.rows))
        terminal_id, terminal = next(iter(backend.terminals.items()))
        spin(app, lambda: any("PTY shell" in row for row in terminal.screen.display))
        terminal.write("echo PTY中文输入完整\r")
        spin(app, lambda: sum("PTY中文输入完整" in row for row in terminal.screen.display) >= 2)
        # GUI applications must be launched from this real PySpOS shell session.
        terminal.write("guicalc &\r")
        spin(app, lambda: any("Calculator" in row["caption"] for row in backend.model.rows))
        calculator = next(row for row in backend.model.rows if "Calculator" in row["caption"])
        backend.moveWindow(calculator["wid"], 850, 70)

        lower = Client(server.endpoint)
        upper = Client(server.endpoint)
        clients.extend((lower, upper))
        lower_id = lower.create("Live background application", 620, 430, "#f02a4cff")
        upper_id = upper.create("Live GPU glass + UX PNG", 540, 300, "#142538ee")
        stripes = [{"type": "rect", "x": i * 20, "y": 0, "width": 10, "height": 430,
                    "color": "#ffffff"} for i in range(31)]
        lower.present(lower_id, stripes)
        spin(app, lambda: backend.model.find(upper_id) is not None)
        backend.moveWindow(terminal_id, 40, 280)
        backend.moveWindow(lower_id, 100, 70)
        backend.moveWindow(upper_id, 150, 140)
        backend.activate(upper_id)
        # Let both texture dependency stages settle before reviewing the same live frame.
        start = time.monotonic()
        spin(app, lambda: time.monotonic() - start > 0.25)
        before = backend.view.grabWindow()
        print("Graphics API:", backend.view.rendererInterface().graphicsApi(), flush=True)
        item = next(i for i in items(backend.view.rootObject()) if i.objectName() == "window-" + str(upper_id))
        glass = next(i for i in items(item) if i.objectName() == "glass-band")
        blur_source = glass.property("source")
        effect = blur_source.property("sourceItem")
        sharp = effect.property("source")
        print("Glass:", glass.property("width"), glass.property("height"),
              "blur:", effect.property("width"), effect.property("height"),
              "sharp:", sharp.property("width"), sharp.property("height"), sharp.property("sourceRect"),
              flush=True)
        before.save(str(output / "desktop-red.png"))
        foreground = backend.model.find(upper_id)["foreground"]
        lower.present(lower_id, stripes, background="#1aaf62ff")
        spin(app, lambda: backend.model.find(upper_id)["backdrop"][-1]["foreground"]
             == backend.model.find(lower_id)["foreground"])
        start = time.monotonic()
        spin(app, lambda: time.monotonic() - start > 0.2)
        after = backend.view.grabWindow()
        after.save(str(output / "desktop-green.png"))
        assert backend.model.find(upper_id)["foreground"] == foreground
        old, new = before.pixelColor(200, 158), after.pixelColor(200, 158)
        assert abs(old.red() - new.red()) + abs(old.green() - new.green()) > 20, (old.name(), new.name())

        row = backend.model.find(upper_id)
        maximum = backend._layout(row).frame()["title"]["buttons"]["max"]
        backend.release(upper_id, maximum[0] + 5, maximum[1] + 5, "max")
        spin(app, lambda: backend.model.find(upper_id)["ww"] > 1000)
        maximum = backend._layout(row).frame()["title"]["buttons"]["max"]
        backend.release(upper_id, maximum[0] + 5, maximum[1] + 5, "max")
        spin(app, lambda: backend.model.find(upper_id)["ww"] == 564)
        minimum = backend._layout(row).frame()["title"]["buttons"]["min"]
        backend.release(upper_id, minimum[0] + 5, minimum[1] + 5, "min")
        assert row["minimized"]
        backend.activate(upper_id)
        assert not row["minimized"]

        result = {"backend": str(backend.view.rendererInterface().graphicsApi()),
                  "pty_pid": terminal.process.pid, "pty_unicode_input": True,
                  "gui_started_from_pty": True, "live_background_changed": True,
                  "upper_foreground_unchanged": True, "minimize_restore_maximize": True,
                  "windows": len(backend.model.rows),
                  "glass_items": sum(i.objectName() == "glass-band" for i in items(backend.view.rootObject()))}
        assert result["glass_items"] == result["windows"] * 4
        (output / "review.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except BaseException:
        if backend.terminals:
            display = "\n".join(next(iter(backend.terminals.values())).screen.display)
            (output / "terminal-failure.txt").write_text(display)
            print(display)
        raise
    finally:
        for client in clients:
            client.close()
        for terminal in list(backend.terminals.values()):
            terminal.close()
        backend.terminals.clear()
        server.stop()
        thread.join(6)
        backend.view.close()
        backend.view.setSource(QUrl())
        server.close()
