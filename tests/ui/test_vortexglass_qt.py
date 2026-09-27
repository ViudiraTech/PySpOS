'''
 *
 *      test_vortexglass_qt.py
 *      Offscreen GUI checks for native transparency, painting and socket input.
 *
 *      2026/9/27 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

QT_PACKAGE = pytest.importorskip("PyQt6", reason="install requirements-gui.txt for compositor GUI tests")

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QImage
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

import pngcodec
import spaceglass_theme as theme
from tests.support import REPO
from vortexglass.client import Client
from vortexglass.daemon import CONTROL_ENV
from vortexglass.demos import Calculator, Canvas
from vortexglass.model import Compositor
from vortexglass.qt_backend import Backend, Renderer
from vortexglass.server import Server


@pytest.fixture(scope="module")
def qt_app():
    # A real Qt event loop and paint engine, with no windows on the user's desktop.
    old = os.environ.get("QT_QPA_PLATFORM")
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication.instance() or QApplication(["VortexGlass tests"])
    app.setQuitOnLastWindowClosed(False)
    yield app
    if old is None:
        os.environ.pop("QT_QPA_PLATFORM", None)
    else:
        os.environ["QT_QPA_PLATFORM"] = old


def spin(app, predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.003)
    app.processEvents()
    assert predicate()


@pytest.fixture
def compositor(qt_app, tmp_path, theme_dir):
    server = Server(tmp_path / "endpoint.json", backend="qt")
    backend = Backend(server, theme.load_theme(theme_dir))
    server.open()
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    yield server, backend, qt_app
    server.stop()
    spin(qt_app, lambda: not thread.is_alive())
    for widget in list(backend.windows.values()):
        widget.close()
        widget.deleteLater()
    qt_app.processEvents()


def test_host_window_is_transparent_frameless_and_owned_by_service(compositor):
    server, backend, app = compositor
    with Client(server.endpoint) as client:
        window = client.create(background="#00000000")
        client.present(window, Canvas().scene(540, 340))
        spin(app, lambda: window in backend.windows)
        widget = backend.windows[window]
        assert widget.windowFlags() & Qt.WindowType.FramelessWindowHint
        assert widget.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        assert not widget.autoFillBackground()
        assert widget.parent() is None
        image = backend.renderer.render(server.model.snapshot(window))
        assert image.pixelColor(20, theme.TITLEBAR_HEIGHT + 260).alpha() == 0
        assert 0 < image.pixelColor(80, theme.TITLEBAR_HEIGHT + 200).alpha() < 255
    spin(app, lambda: not backend.windows)


def test_png_snapshot_uses_service_renderer_and_keeps_alpha(compositor):
    server, backend, app = compositor
    with Client(server.endpoint) as client:
        window = client.create(width=540, height=340, background="#00000000")
        client.present(window, Canvas().scene(540, 340))
        output, done = [], threading.Event()

        def capture():
            try:
                output.append(client.snapshot(window))
            finally:
                done.set()

        worker = threading.Thread(target=capture)
        worker.start()
        spin(app, done.is_set)
        worker.join()
        image = QImage.fromData(output[0], "PNG")
        assert (image.width(), image.height()) == (564, 388)
        assert image.pixelColor(20, theme.TITLEBAR_HEIGHT + 260).alpha() == 0
        assert len(backend.windows) == 1


def test_native_mouse_and_keyboard_reach_only_the_owning_client(compositor):
    server, backend, app = compositor
    with Client(server.endpoint) as client, Client(server.endpoint) as other:
        demo = Calculator()
        window = client.create(demo.title, *demo.size)
        client.present(window, demo.scene(*demo.size))
        spin(app, lambda: window in backend.windows)
        widget = backend.windows[window]
        # Drain the initial resize notification, if the host platform emits it.
        while client.next_event(0.01):
            pass
        QTest.mouseClick(widget, Qt.MouseButton.LeftButton,
                         pos=QPoint(theme.SIDE_INSET + 35, theme.TITLEBAR_HEIGHT + 235))
        event = client.next_event(1)
        assert event["type"] == "click" and event["target"] == "1"
        demo.handle(event)
        assert demo.expression == "1"
        QTest.keyClicks(widget, "2")
        event = client.next_event(1)
        assert event["type"] == "key" and event["text"] == "2"
        demo.handle(event)
        assert demo.expression == "12"
        assert other.next_event(0.02) is None


def test_caption_close_and_resize_update_the_model(compositor):
    server, backend, app = compositor
    with Client(server.endpoint) as client:
        window = client.create()
        spin(app, lambda: window in backend.windows)
        widget = backend.windows[window]
        widget.resize(500, 360)
        app.processEvents()
        state = server.model.snapshot(window)
        assert (state.width, state.height) == (476, 312)
        close = widget.layout().frame()["title"]["buttons"]["close"]
        QTest.mouseClick(widget, Qt.MouseButton.LeftButton,
                         pos=QPoint(close[0] + 10, close[1] + 10))
        spin(app, lambda: server.model.snapshot(window) is None)
        events = []
        while (event := client.next_event(0.1)) is not None:
            events.append(event)
        assert any(event["type"] == "resize" for event in events)
        assert any(event["type"] == "close" for event in events)


def test_theme_transparent_corners_are_not_flattened(qt_app, theme_dir):
    renderer = Renderer(theme.load_theme(theme_dir))
    # The synthetic inventory has opaque strips. Replace only decoded artwork
    # in this renderer, leaving the shared fixture's files untouched.
    top = pngcodec.RgbaImage(336, 27, bytes((32, 65, 96, 80)) * (336 * 27))
    top.pixels = bytearray(top.pixels)
    for y in range(4):
        for x in range(4):
            top.pixels[(y * top.width + x) * 4 + 3] = 0
    renderer.images["top.png"] = QImage.fromData(pngcodec.write_png(top), "PNG")
    renderer.images.pop("reflection.png")
    server_model = Compositor()
    window_id = server_model.create(1, {"background": "#00000000"})["window"]
    image = renderer.render(server_model.snapshot(window_id))
    assert image.pixelColor(0, 0).alpha() == 0
    assert image.pixelColor(100, 0).alpha() == 80


def test_real_gui_service_renders_and_cleans_up_on_termination(tmp_path, theme_dir):
    endpoint = tmp_path / "endpoint.json"
    child = subprocess.Popen([sys.executable, "-m", "vortexglass.daemon", "--offscreen",
                              "--theme-dir", theme_dir, "--endpoint", str(endpoint)],
                             # Tests isolate HOME, which hides user-site packages
                             # in a fresh interpreter. Reuse the installed Qt location.
                             env={**os.environ, "PYTHONPATH": os.pathsep.join((
                                 str(REPO / "src"), str(Path(QT_PACKAGE.__path__[0]).parent))),
                                  CONTROL_ENV: "test-qt-termination"},
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 5
        while not endpoint.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        if not endpoint.exists():
            if child.poll() is None:
                child.kill()
            stdout, stderr = child.communicate(timeout=2)
            pytest.fail(stdout + stderr)
        with Client(endpoint) as client:
            window = client.create(background="#00000000")
            client.present(window, Canvas().scene(540, 340))
            image = QImage.fromData(client.snapshot(window), "PNG")
            assert not image.isNull()
            assert image.pixelColor(20, theme.TITLEBAR_HEIGHT + 260).alpha() == 0
        if os.name == "nt":
            # Windows TerminateProcess cannot run cleanup handlers. Exercise the
            # same graceful shutdown as PID 1 instead; POSIX also tests SIGTERM.
            with Client(endpoint) as client:
                client.request("shutdown", control="test-qt-termination")
        else:
            child.terminate()
        stdout, stderr = child.communicate(timeout=5)
        assert child.returncode == 0, stdout + stderr
        assert not endpoint.exists()
        assert not endpoint.with_suffix(".sock").exists()
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
