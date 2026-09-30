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

from PyQt6.QtCore import QByteArray, QBuffer, QEvent, QIODevice, QObject, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PyQt6.QtWidgets import QApplication, QWidget

import spaceglass_theme as theme

from .protocol import ProtocolError
from .frost import SceneFrost
from .native_blur import NativeBlur
from .input import key_event


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

    # Draw runtime glass first, then PNG artwork, client content and controls.
    def render(self, window, hover=None, focused=True, *, frost=None,
               frost_opacity=1.0, origin=(0, 0), scale=1.0):
        width = window.width + theme.SIDE_INSET * 2
        height = window.height + theme.TITLEBAR_HEIGHT + theme.BOTTOM_HEIGHT
        image = QImage(round(width * scale), round(height * scale),
                       QImage.Format.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(scale)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if frost is not None:
            painter.setOpacity(frost_opacity)
            painter.drawImage(0, 0, frost)
            painter.setOpacity(1)
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
            # Match UX's screen-anchored, unscaled reflection texture.
            source_x = origin[0] % reflection.width()
            x = 0
            while x < width:
                span = min(width - x, reflection.width() - source_x)
                painter.drawImage(QRectF(x, 0, span, theme.TITLEBAR_HEIGHT), reflection,
                                  QRectF(source_x, 0, span, theme.TITLEBAR_HEIGHT))
                x += span
                source_x = 0
            painter.restore()

        painter.fillRect(QRectF(*frame["client"]), rgba(window.background))
        painter.save()
        painter.setClipRect(QRectF(*frame["client"]))
        painter.translate(theme.SIDE_INSET, theme.TITLEBAR_HEIGHT)
        if window.pixels is not None:
            pw, ph = window.pixel_size
            surface = QImage(window.pixels, pw, ph, pw * 4, QImage.Format.Format_RGBA8888)
            painter.drawImage(0, 0, surface)
        for item in window.items:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(rgba(item["color"]))
            if item["type"] in ("rect", "button"):
                painter.drawRoundedRect(QRectF(item["x"], item["y"], item["width"], item["height"]),
                                        item["radius"], item["radius"])
            if item["type"] in ("text", "button"):
                font = QFont(item.get("font", "sans-serif"))
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
        self.foreground_key = None
        self.foreground_image = None
        self.native_blur_requested = False
        self.syncing = True
        self.setMinimumSize(window.min_width + 24, window.min_height + 48)
        self.setMaximumSize(1624, 1248)
        self.sync(window)
        self.move(80 + (window.id % 8) * 36, 70 + (window.id % 8) * 30)
        self.syncing = False
        self.show()
        self.native_blur_requested = self.backend.native_blur.apply(self)

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

    # Cache sharp appearances separately so backdrop composition cannot recurse.
    def foreground(self, window):
        key = (window.revision, window.width, window.height, self.hover, self.isActiveWindow())
        if key != self.foreground_key:
            self.foreground_image = self.backend.renderer.render(window, self.hover, self.isActiveWindow())
            self.foreground_key = key
        return self.foreground_image

    # Cache the foreground; the Mutter extension paints live glass behind this surface.
    def paintEvent(self, _event):
        window = self.backend.server.model.snapshot(self.window_id)
        if window is None:
            return
        origin = self.mapToGlobal(self.rect().topLeft())
        key = (window.revision, window.width, window.height, self.hover,
               self.isActiveWindow(), self.backend.frost.revision, origin.x(), origin.y())
        if key != self.cache_key:
            self.cached_image = self.backend.renderer.render(
                window, self.hover, self.isActiveWindow(), frost=self.backend.frost.texture(self),
                frost_opacity=0.35 if self.native_blur_requested else 1,
                origin=(origin.x(), origin.y()))
            self.cache_key = key
        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.drawImage(0, 0, self.cached_image)
        painter.end()

    # Moving the glass changes background sampling, even for an unchanged app scene.
    def moveEvent(self, _event):
        if hasattr(self, "backend"):
            self.backend.frost.invalidate()

    # Keep service-owned stacking and focus changes in the sharp scene cache.
    def event(self, event):
        if hasattr(self, "window_id") and event.type() in (
                QEvent.Type.WindowActivate, QEvent.Type.ZOrderChange):
            self.backend.frost.raise_window(self.window_id)
        if hasattr(self, "backend") and event.type() == QEvent.Type.WindowStateChange:
            self.backend.frost.invalidate()
        return super().event(event)

    def _emit(self, event):
        self.backend.server.emit(self.owner, {"window": self.window_id, **event})

    def _optional(self, event):
        window = self.backend.server.model.snapshot(self.window_id)
        if window and event["type"] in window.input_events:
            self._emit(event)

    def _pointer(self, event, phase):
        point = event.position().toPoint()
        x, y = point.x() - theme.SIDE_INSET, point.y() - theme.TITLEBAR_HEIGHT
        if 0 <= x < self.width() - 24 and 0 <= y < self.height() - 48:
            self._optional({"type": "pointer", "phase": phase, "x": x, "y": y,
                            "button": {1: "left", 2: "right", 4: "middle"}.get(event.button().value),
                            "buttons": event.buttons().value, "modifiers": event.modifiers().value})

    def focusInEvent(self, event):
        self._optional({"type": "focus", "focused": True})
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        self._optional({"type": "focus", "focused": False})
        super().focusOutEvent(event)

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            self._pointer(event, "press")
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
            self._pointer(event, "press")

    def mouseMoveEvent(self, event):
        point = event.position().toPoint()
        hover = self.layout().hit_button(point.x(), point.y())
        if hover != self.hover:
            self.hover = hover
            self.backend.frost.invalidate()
        if self.drag is not None:
            self.move(event.globalPosition().toPoint() - self.drag)
        if self.resize_origin:
            origin, size = self.resize_origin
            delta = event.globalPosition().toPoint() - origin
            self.resize(size.width() + delta.x(), size.height() + delta.y())
        if self.drag is None and self.resize_origin is None and not self.pressed:
            self._pointer(event, "move")

    def leaveEvent(self, _event):
        self.hover = None
        self.backend.frost.invalidate()

    def mouseReleaseEvent(self, event):
        if not self.pressed and self.drag is None and self.resize_origin is None:
            self._pointer(event, "release")
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
        self._emit(key_event(event.key(), event.text(), event.modifiers().value))

    def wheelEvent(self, event):
        point = event.position().toPoint()
        self._optional({"type": "scroll", "x": point.x() - theme.SIDE_INSET,
                        "y": point.y() - theme.TITLEBAR_HEIGHT,
                        "dx": event.angleDelta().x(), "dy": event.angleDelta().y(),
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
        self.backend.native_blur.apply(self)
        self.backend.frost.invalidate()

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
        self.frost = SceneFrost(self)
        self.native_blur = NativeBlur()
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
                self.frost.raise_window(window_id)
        self.frost.order = [window_id for window_id in self.frost.order if window_id in self.windows]
        self.frost.invalidate()

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
            self.native_blur.close()
            self.server.stop()
            thread.join(6)
            for widget in list(self.windows.values()):
                widget.close()
