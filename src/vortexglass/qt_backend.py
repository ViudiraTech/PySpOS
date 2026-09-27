'''
 *
 *      qt_backend.py
 *      Transparent frameless host windows owned by the VortexGlass service.
 *
 *      2026/9/27 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import threading

from PyQt6.QtCore import QByteArray, QBuffer, QIODevice, QObject, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PyQt6.QtWidgets import QApplication, QWidget

import spaceglass_theme as theme

from .protocol import ProtocolError


def rgba(value):
    rgb = value[1:7]
    alpha = int(value[7:9], 16) if len(value) == 9 else 255
    return QColor(int(rgb[0:2], 16), int(rgb[2:4], 16), int(rgb[4:6], 16), alpha)


class Renderer:
    def __init__(self, report=None):
        self.images = {}
        if report:
            for name, path in report["images"].items():
                image = QImage(path)
                if image.isNull():
                    raise ValueError(f"cannot decode theme image: {name}")
                self.images[name] = image

    def _horizontal(self, painter, name, rect):
        image = self.images.get(name)
        if image is None:
            painter.fillRect(QRectF(*rect), QColor(38, 56, 79, 170))
            return
        x, y, width, height = rect
        height = min(height, image.height())
        cap = min(theme.FRAME_CORNER, width // 2)
        painter.drawImage(QRectF(x, y, cap, height), image, QRectF(0, 0, cap, height))
        painter.drawImage(QRectF(x + width - cap, y, cap, height), image,
                          QRectF(image.width() - cap, 0, cap, height))
        painter.drawImage(QRectF(x + cap, y, width - cap * 2, height), image,
                          QRectF(image.width() // 2, 0, 1, height))

    def _vertical(self, painter, name, rect):
        image = self.images.get(name)
        if image is None:
            painter.fillRect(QRectF(*rect), QColor(38, 56, 79, 150))
            return
        x, y, width, height = rect
        cap = min(theme.FRAME_CORNER, height // 2)
        painter.drawImage(QRectF(x, y, width, cap), image, QRectF(0, 0, width, cap))
        painter.drawImage(QRectF(x, y + height - cap, width, cap), image,
                          QRectF(0, image.height() - cap, width, cap))
        painter.drawImage(QRectF(x, y + cap, width, height - cap * 2), image,
                          QRectF(0, min(theme.BORDER_MIDDLE_ROW, image.height() - 1), width, 1))

    def render(self, window, hover=None, focused=True):
        width = window.width + theme.SIDE_INSET * 2
        height = window.height + theme.TITLEBAR_HEIGHT + theme.BOTTOM_HEIGHT
        image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        layout = theme.WindowLayout(theme.SIDE_INSET, theme.TITLEBAR_HEIGHT,
                                    window.width, window.height, window.title, focused)
        frame = layout.frame()
        self._horizontal(painter, "top.png", frame["title"]["art"])
        # Preserve the source's alpha on the additional title row too.
        top = self.images.get("top.png")
        if top:
            painter.drawImage(QRectF(0, theme.TITLE_ART_HEIGHT, width, 1), top,
                              QRectF(top.width() // 2, top.height() - 1, 1, 1))
        else:
            painter.fillRect(QRectF(0, theme.TITLE_ART_HEIGHT, width, 1), QColor(38, 56, 79, 170))
        self._vertical(painter, "left.png", frame["left"])
        self._vertical(painter, "right.png", frame["right"])
        self._horizontal(painter, "bottom.png", frame["bottom"])
        reflection = self.images.get("reflection.png")
        if reflection:
            painter.save()
            painter.setClipRect(QRectF(*frame["title"]["strip"]))
            painter.setOpacity(0.22)
            painter.drawImage(QRectF(0, 0, width, theme.TITLEBAR_HEIGHT), reflection)
            painter.restore()

        painter.fillRect(QRectF(*frame["client"]), rgba(window.background))
        painter.save()
        painter.setClipRect(QRectF(*frame["client"]))
        painter.translate(theme.SIDE_INSET, theme.TITLEBAR_HEIGHT)
        for item in window.items:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(rgba(item["color"]))
            if item["type"] in ("rect", "button"):
                painter.drawRoundedRect(QRectF(item["x"], item["y"], item["width"], item["height"]),
                                        item["radius"], item["radius"])
            if item["type"] in ("text", "button"):
                font = QFont("sans-serif")
                font.setPixelSize(item["size"])
                painter.setFont(font)
                painter.setPen(rgba(item.get("foreground", item["color"])))
                if item["type"] == "button":
                    painter.drawText(QRectF(item["x"], item["y"], item["width"], item["height"]),
                                     Qt.AlignmentFlag.AlignCenter, item["text"])
                else:
                    painter.drawText(item["x"], item["y"] + item["size"], item["text"])
            if item["type"] == "line":
                painter.setPen(QPen(rgba(item["color"]), item["width"]))
                painter.drawLine(item["x"], item["y"], item["x2"], item["y2"])
        painter.restore()

        title_colour = "#e6edf3"
        if top:
            sample = top.pixelColor(top.width() // 2, min(12, top.height() - 1))
            if sample.red() * 0.2126 + sample.green() * 0.7152 + sample.blue() * 0.0722 > 150:
                title_colour = "#203249"
        painter.setPen(QColor(title_colour) if focused else QColor("#68788b"))
        font = QFont("sans-serif")
        font.setPixelSize(12)
        painter.setFont(font)
        painter.drawText(QRectF(32, 2, max(0, window.width - 116), 24),
                         Qt.AlignmentFlag.AlignVCenter, window.title)
        painter.fillRect(QRectF(12, 7, 14, 14), QColor(64, 142, 214, 210))
        for kind, rect in frame["title"]["buttons"].items():
            art = self.images.get(theme.TITLE_BUTTONS[kind]["hover" if hover == kind else "normal"])
            if art:
                painter.drawImage(QRectF(*rect), art)
            else:
                painter.fillRect(QRectF(*rect), QColor(177, 56, 69, 220) if kind == "close"
                                 else QColor(65, 95, 129, 170 if hover != kind else 230))
                painter.setPen(QColor("#ffffff"))
                painter.drawText(QRectF(*rect), Qt.AlignmentFlag.AlignCenter,
                                 {"close": "×", "min": "−", "max": "□"}[kind])
        painter.end()
        return image

    def png(self, window):
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not self.render(window).save(buffer, "PNG"):
            raise ProtocolError("PNG encoding failed")
        return bytes(data)


class GlassWindow(QWidget):
    def __init__(self, backend, window):
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.backend = backend
        self.window_id = window.id
        self.owner = window.owner
        self.hover = None
        self.pressed = None
        self.drag = None
        self.resize_origin = None
        self.cache_key = None
        self.cached_image = None
        self.syncing = True
        self.setMinimumSize(184, 128)
        self.setMaximumSize(1624, 1248)
        self.sync(window)
        self.move(80 + (window.id % 8) * 36, 70 + (window.id % 8) * 30)
        self.syncing = False
        self.show()

    def layout(self):
        return theme.WindowLayout(theme.SIDE_INSET, theme.TITLEBAR_HEIGHT,
                                  max(160, self.width() - theme.SIDE_INSET * 2),
                                  max(80, self.height() - theme.TITLEBAR_HEIGHT - theme.BOTTOM_HEIGHT))

    def sync(self, window):
        self.syncing = True
        self.setWindowTitle(window.title)
        self.resize(window.width + theme.SIDE_INSET * 2,
                    window.height + theme.TITLEBAR_HEIGHT + theme.BOTTOM_HEIGHT)
        self.syncing = False
        self.update()

    def paintEvent(self, _event):
        window = self.backend.server.model.snapshot(self.window_id)
        if window is None:
            return
        key = (window.revision, window.width, window.height, self.hover, self.isActiveWindow())
        if key != self.cache_key:
            self.cached_image = self.backend.renderer.render(window, self.hover, self.isActiveWindow())
            self.cache_key = key
        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.drawImage(0, 0, self.cached_image)
        painter.end()

    def _emit(self, event):
        self.backend.server.emit(self.owner, {"window": self.window_id, **event})

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        point = event.position().toPoint()
        self.pressed = self.layout().hit_button(point.x(), point.y())
        if self.pressed:
            return
        if self.layout().hit_title(point.x(), point.y()):
            if not self.windowHandle().startSystemMove():
                self.drag = event.globalPosition().toPoint() - self.pos()
        elif point.x() >= self.width() - 12 and point.y() >= self.height() - 12:
            if not self.windowHandle().startSystemResize(Qt.Edge.RightEdge | Qt.Edge.BottomEdge):
                self.resize_origin = (event.globalPosition().toPoint(), self.size())
        else:
            x, y = point.x() - theme.SIDE_INSET, point.y() - theme.TITLEBAR_HEIGHT
            target = self.backend.server.model.button_at(self.window_id, x, y)
            self._emit({"type": "click", "target": target, "x": x, "y": y})

    def mouseMoveEvent(self, event):
        point = event.position().toPoint()
        hover = self.layout().hit_button(point.x(), point.y())
        if hover != self.hover:
            self.hover = hover
            self.update()
        if self.drag is not None:
            self.move(event.globalPosition().toPoint() - self.drag)
        if self.resize_origin:
            origin, size = self.resize_origin
            delta = event.globalPosition().toPoint() - origin
            self.resize(size.width() + delta.x(), size.height() + delta.y())

    def leaveEvent(self, _event):
        self.hover = None
        self.update()

    def mouseReleaseEvent(self, event):
        point = event.position().toPoint()
        pressed, self.pressed = self.pressed, None
        self.drag = self.resize_origin = None
        if pressed and pressed == self.layout().hit_button(point.x(), point.y()):
            if pressed == "close":
                self.close()
            elif pressed == "min":
                self.showMinimized()
                self._emit({"type": "state", "state": "minimized"})
            else:
                self.toggle_maximize()

    def toggle_maximize(self):
        self.showNormal() if self.isMaximized() else self.showMaximized()
        self._emit({"type": "state", "state": "maximized" if self.isMaximized() else "normal"})

    def mouseDoubleClickEvent(self, event):
        point = event.position().toPoint()
        if self.layout().hit_title(point.x(), point.y()) and not self.layout().hit_button(point.x(), point.y()):
            self.toggle_maximize()

    def keyPressEvent(self, event):
        self._emit({"type": "key", "key": event.key(), "text": event.text(),
                    "modifiers": event.modifiers().value})

    def resizeEvent(self, _event):
        if self.syncing:
            return
        width, height = self.width() - 24, self.height() - 48
        try:
            self.backend.server.model.resize(self.owner, {"window": self.window_id,
                                                         "width": width, "height": height})
        except ProtocolError:
            window = self.backend.server.model.snapshot(self.window_id)
            if window:
                self.sync(window)
            return
        self._emit({"type": "resize", "width": width, "height": height})

    def closeEvent(self, event):
        window = self.backend.server.model.snapshot(self.window_id)
        if window:
            self.backend.server.model.destroy(self.owner, self.window_id)
            self._emit({"type": "close"})
        event.accept()


class Backend(QObject):
    changed = pyqtSignal()
    invoke = pyqtSignal(object)
    ended = pyqtSignal()

    def __init__(self, server, report=None):
        super().__init__()
        self.server = server
        self.renderer = Renderer(report)
        self.windows = {}
        self.pending = set()
        self.pending_lock = threading.Lock()
        self.changed.connect(self._sync, Qt.ConnectionType.QueuedConnection)
        self.invoke.connect(self._invoke, Qt.ConnectionType.QueuedConnection)
        self.ended.connect(QApplication.instance().quit, Qt.ConnectionType.QueuedConnection)
        server.model.changed = self.notify
        server.capture = self.capture

    def notify(self, window_id):
        with self.pending_lock:
            notify = not self.pending
            self.pending.add(window_id)
        if notify:
            self.changed.emit()

    def _sync(self):
        with self.pending_lock:
            pending, self.pending = self.pending, set()
        for window_id in pending:
            window = self.server.model.snapshot(window_id)
            widget = self.windows.get(window_id)
            if window is None:
                if widget:
                    widget.close()
                    widget.deleteLater()
                    del self.windows[window_id]
            elif widget:
                widget.sync(window)
            else:
                self.windows[window_id] = GlassWindow(self, window)

    def _invoke(self, task):
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

    def run(self):
        app = QApplication.instance()
        app.setQuitOnLastWindowClosed(False)

        def serve():
            try:
                self.server.run()
            finally:
                self.ended.emit()

        # Publish readiness on the GUI thread before starting the IO thread.
        self.server.open()
        thread = threading.Thread(target=serve, name="vortexglass-socket", daemon=True)
        thread.start()
        try:
            return app.exec()
        finally:
            self.server.stop()
            thread.join(6)
            for widget in list(self.windows.values()):
                widget.close()
