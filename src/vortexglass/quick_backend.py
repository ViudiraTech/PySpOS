'''
 *
 *      quick_backend.py
 *      Portable Qt Quick desktop, internal window manager and PTY sessions.
 *
 *      2026/9/27 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

from pathlib import Path
import os
import threading

from PyQt6.QtCore import (QAbstractListModel, QModelIndex, QObject, QSize, Qt, QUrl,
                          pyqtProperty, pyqtSignal, pyqtSlot)
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtQuick import QQuickImageProvider, QQuickView
from PyQt6.QtWidgets import QApplication

import spaceglass_theme as theme

from .protocol import ENDPOINT_ENV, ProtocolError
from .qt_backend import Renderer
from .terminal import Terminal


# Preserve delegate identity while geometry, content and stacking roles change.
class WindowModel(QAbstractListModel):
    names = ("wid", "caption", "wx", "wy", "ww", "wh", "rank", "minimized", "focused",
             "foreground", "backdrop")

    def __init__(self):
        super().__init__()
        self.rows = []

    def roleNames(self):
        return {Qt.ItemDataRole.UserRole + i: name.encode() for i, name in enumerate(self.names)}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index, role):
        position = role - Qt.ItemDataRole.UserRole
        if index.isValid() and 0 <= position < len(self.names):
            return self.rows[index.row()].get(self.names[position])
        return None

    def find(self, wid):
        return next((row for row in self.rows if row["wid"] == wid), None)

    def append(self, row):
        index = len(self.rows)
        self.beginInsertRows(QModelIndex(), index, index)
        self.rows.append(row)
        self.endInsertRows()

    def remove(self, wid):
        row = self.find(wid)
        if row:
            index = self.rows.index(row)
            self.beginRemoveRows(QModelIndex(), index, index)
            self.rows.pop(index)
            self.endRemoveRows()

    def change(self, row, **fields):
        roles = []
        for name, value in fields.items():
            if row.get(name) != value:
                row[name] = value
                if name in self.names:
                    roles.append(Qt.ItemDataRole.UserRole + self.names.index(name))
        if roles:
            index = self.index(self.rows.index(row))
            self.dataChanged.emit(index, index, roles)


# Serve detached sharp images; GPU blur and refraction never read back to the CPU.
class ImageProvider(QQuickImageProvider):
    def __init__(self):
        super().__init__(QQuickImageProvider.ImageType.Image)
        self.images = {}
        self.lock = threading.Lock()

    def requestImage(self, image_id, requested_size):
        with self.lock:
            image = self.images.get(int(image_id.split("/")[0]), QImage()).copy()
        return image, image.size()

    def put(self, wid, image):
        with self.lock:
            self.images[wid] = image

    def remove(self, wid):
        with self.lock:
            self.images.pop(wid, None)


class Backend(QObject):
    changed = pyqtSignal()
    invoke = pyqtSignal(object)
    ended = pyqtSignal()

    def __init__(self, server, report=None, *, terminal=True):
        super().__init__()
        self.server = server
        self.renderer = Renderer(report)
        self.model = WindowModel()
        self.provider = ImageProvider()
        self.pending = set()
        self.pending_lock = threading.Lock()
        self.serial = 0
        self.desktop_size = (1280, 758)
        self.terminals = {}
        self.start_terminal = terminal
        self.changed.connect(self._sync, Qt.ConnectionType.QueuedConnection)
        self.invoke.connect(self._capture, Qt.ConnectionType.QueuedConnection)
        self.ended.connect(QApplication.instance().quit, Qt.ConnectionType.QueuedConnection)
        server.model.changed = self.notify
        server.capture = self.capture
        self.view = QQuickView()
        self.view.setTitle("PySpOS Desktop")
        self.view.setColor(QColor("#142237"))
        self.view.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
        self.view.engine().addImageProvider("vortexglass", self.provider)
        self.view.rootContext().setContextProperty("controller", self)
        self.view.setSource(QUrl.fromLocalFile(str(Path(__file__).with_name("qml") / "Desktop.qml")))
        if self.view.status() == QQuickView.Status.Error:
            raise RuntimeError("Desktop QML: " + "; ".join(error.toString() for error in self.view.errors()))
        self.view.resize(QSize(1280, 800))

    @pyqtProperty(QObject, constant=True)
    def windowModel(self):
        return self.model

    # Coalesce socket changes before rendering sharp appearances on the GUI thread.
    def notify(self, wid):
        with self.pending_lock:
            first = not self.pending
            self.pending.add(wid)
        if first:
            self.changed.emit()

    def _sync(self):
        with self.pending_lock:
            pending, self.pending = self.pending, set()
        for wid in pending:
            window = self.server.model.snapshot(wid)
            row = self.model.find(wid)
            if window is None:
                self.model.remove(wid)
                self.provider.remove(wid)
                terminal = self.terminals.pop(wid, None)
                if terminal:
                    terminal.close()
                continue
            if row is None:
                row = {"wid": wid, "caption": window.title, "wx": 64 + wid % 7 * 28,
                       "wy": 50 + wid % 7 * 26, "ww": window.width + 24, "wh": window.height + 48,
                       "rank": len(self.model.rows), "minimized": False, "focused": False,
                       "foreground": "", "backdrop": [], "hover": None, "restore": None}
                self.model.append(row)
                self.activate(wid)
            self.model.change(row, caption=window.title, ww=window.width + 24, wh=window.height + 48)
            self._render(row, window)
        self._backdrops()

    def _render(self, row, window=None):
        window = window or self.server.model.snapshot(row["wid"])
        if window is None:
            return
        image = self.renderer.render(window, row["hover"], row["focused"],
                                     origin=(int(row["wx"]), int(row["wy"])))
        terminal = self.terminals.get(row["wid"])
        if terminal:
            terminal.paint(image, (theme.SIDE_INSET, theme.TITLEBAR_HEIGHT))
        self.provider.put(row["wid"], image)
        self.serial += 1
        self.model.change(row, foreground=f"image://vortexglass/{row['wid']}/{self.serial}")

    # Sampling uses lower sharp layers only, following UX's non-recursive composition.
    def _backdrops(self):
        ordered = sorted(self.model.rows, key=lambda row: row["rank"])
        lower = []
        for row in ordered:
            self.model.change(row, backdrop=list(lower))
            if not row["minimized"]:
                lower.append({key: row[key] for key in ("wx", "wy", "ww", "wh", "foreground")})

    @pyqtSlot(float, float)
    def setDesktopSize(self, width, height):
        if width > 0 and height > 42:
            self.desktop_size = (width, height - 42)

    @pyqtSlot(int)
    def activate(self, wid):
        selected = self.model.find(wid)
        if selected is None:
            return
        order = sorted(self.model.rows, key=lambda row: row["rank"])
        order.remove(selected)
        order.append(selected)
        for rank, row in enumerate(order):
            changed = row["focused"] != (row is selected)
            self.model.change(row, focused=row is selected, rank=rank,
                              minimized=False if row is selected else row["minimized"])
            if changed:
                self._render(row)
        self._backdrops()

    @pyqtSlot(int, float, float)
    def moveWindow(self, wid, x, y):
        row = self.model.find(wid)
        if row and row["restore"] is None:
            width, height = self.desktop_size
            self.model.change(row, wx=max(0, min(x, max(0, width - row["ww"]))),
                              wy=max(0, min(y, max(0, height - row["wh"]))))
            self._backdrops()

    @pyqtSlot(int, float, float)
    def resizeWindow(self, wid, width, height):
        row = self.model.find(wid)
        if not row:
            return
        window = self.server.model.snapshot(wid)
        if not window:
            return
        width, height = max(160, min(1600, int(width) - 24)), max(80, min(1200, int(height) - 48))
        try:
            self.server.model.resize(window.owner, {"window": wid, "width": width, "height": height})
        except ProtocolError:
            return
        self.model.change(row, ww=width + 24, wh=height + 48)
        terminal = self.terminals.get(wid)
        if terminal:
            terminal.resize(width, height)
        else:
            self._emit(window, {"type": "resize", "width": width, "height": height})
        self._backdrops()

    def _layout(self, row):
        return theme.WindowLayout(12, 28, row["ww"] - 24, row["wh"] - 48)

    @pyqtSlot(int, float, float, result=str)
    def press(self, wid, x, y):
        row = self.model.find(wid)
        if not row:
            return ""
        button = self._layout(row).hit_button(int(x), int(y))
        if button:
            return button
        if y < 28:
            return "move"
        if x >= row["ww"] - 12 and y >= row["wh"] - 12:
            return "resize"
        return "client"

    @pyqtSlot(int, float, float)
    def hover(self, wid, x, y):
        row = self.model.find(wid)
        if row:
            hover = self._layout(row).hit_button(int(x), int(y))
            if hover != row["hover"]:
                row["hover"] = hover
                self._render(row)
                self._backdrops()

    @pyqtSlot(int, float, float, str)
    def release(self, wid, x, y, mode):
        row = self.model.find(wid)
        window = self.server.model.snapshot(wid)
        if not row or not window:
            return
        if mode in ("close", "min", "max") and self._layout(row).hit_button(int(x), int(y)) != mode:
            return
        if mode == "close":
            self.server.model.destroy(window.owner, wid)
            self._emit(window, {"type": "close"})
        elif mode == "min":
            self.model.change(row, minimized=True, focused=False)
            self._emit(window, {"type": "state", "state": "minimized"})
            self._backdrops()
        elif mode == "max":
            if row["restore"]:
                ox, oy, width, height = row.pop("restore")
                row["restore"] = None
                self.model.change(row, wx=ox, wy=oy)
            else:
                row["restore"] = (row["wx"], row["wy"], row["ww"], row["wh"])
                self.model.change(row, wx=0, wy=0)
                width, height = self.desktop_size
            self.resizeWindow(wid, width, height)
            self._emit(window, {"type": "state", "state": "maximized" if row["restore"] else "normal"})
        elif mode == "client" and wid not in self.terminals:
            x, y = int(x) - 12, int(y) - 28
            self._emit(window, {"type": "click", "target": self.server.model.button_at(wid, x, y),
                                "x": x, "y": y})

    @pyqtSlot(int, int, str, int)
    def key(self, wid, key, text, modifiers):
        if wid in self.terminals:
            self.terminals[wid].key(key, text, modifiers)
        else:
            window = self.server.model.snapshot(wid)
            if window:
                self._emit(window, {"type": "key", "key": key, "text": text, "modifiers": modifiers})

    @pyqtSlot(int, int)
    def scroll(self, wid, delta):
        terminal = self.terminals.get(wid)
        if terminal:
            terminal.screen.prev_page() if delta > 0 else terminal.screen.next_page()
            self.notify(wid)

    def _emit(self, window, event):
        if window.id not in self.terminals:
            self.server.emit(window.owner, {"window": window.id, **event})

    @pyqtSlot()
    def openTerminal(self):
        wid = self.server.model.create(0, {"title": "PTY Shell", "width": 752, "height": 448,
                                           "background": "#0c1727ee"})["window"]
        try:
            terminal = Terminal(env={**os.environ, ENDPOINT_ENV: str(self.server.endpoint)})
        except BaseException:
            self.server.model.destroy(0, wid)
            raise
        self.terminals[wid] = terminal
        terminal.output.connect(lambda data, wid=wid: self._terminal_output(wid, data))
        terminal.exited.connect(lambda wid=wid: self._terminal_exited(wid))
        terminal.start()

    def _terminal_output(self, wid, data):
        terminal = self.terminals.get(wid)
        if terminal:
            terminal.feed(data)
            self.notify(wid)

    def _terminal_exited(self, wid):
        if self.server.model.snapshot(wid):
            self.server.model.destroy(0, wid)

    @pyqtSlot()
    def exitDesktop(self):
        QApplication.instance().quit()

    # Keep socket snapshots foreground-only, independent of desktop coordinates and GPU state.
    def _capture(self, task):
        window, done, result = task
        try:
            result.append(self.renderer.png(window))
        except Exception as exc:
            result.append(exc)
        finally:
            done.set()

    def capture(self, window):
        done, result = threading.Event(), []
        self.invoke.emit((window, done, result))
        if not done.wait(5):
            raise TimeoutError("GUI capture timed out")
        if isinstance(result[0], Exception):
            raise ProtocolError(str(result[0]))
        return result[0]

    # The service owns one host window and all terminal sessions, and releases them together.
    def run(self):
        app = QApplication.instance()
        app.setQuitOnLastWindowClosed(True)
        self.view.show()
        self.server.open()
        if self.start_terminal:
            self.openTerminal()

        def serve():
            try:
                self.server.run()
            finally:
                self.ended.emit()

        thread = threading.Thread(target=serve, name="vortexglass-socket", daemon=True)
        thread.start()
        try:
            return app.exec()
        finally:
            for terminal in list(self.terminals.values()):
                terminal.close()
            self.terminals.clear()
            self.server.stop()
            thread.join(6)
            self.view.close()
            self.view.setSource(QUrl())
