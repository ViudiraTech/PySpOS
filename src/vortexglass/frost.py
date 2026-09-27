'''
 *
 *      frost.py
 *      UX-style scene frost, edge refraction and cached frame textures.
 *
 *      2026/9/27 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

from functools import lru_cache
import os

import numpy as np
from PyQt6.QtCore import QRect, QRectF, Qt
from PyQt6.QtGui import QColor, QImage, QPainter

import spaceglass_theme as theme

BLUR_RADIUS = 8
REFRACTION_PIXELS = 3
CONTEXT = BLUR_RADIUS + REFRACTION_PIXELS


# Copy straight RGBA pixels into an array without a Python loop per pixel.
def pixels(image):
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    pointer = image.constBits()
    pointer.setsize(image.sizeInBytes())
    return np.frombuffer(pointer, dtype=np.uint8).reshape(
        image.height(), image.bytesPerLine())[:, :image.width() * 4].reshape(
            image.height(), image.width(), 4).copy()


# Detach the QImage from the temporary array before returning it to Qt.
def image_from_pixels(array):
    array = np.ascontiguousarray(array, dtype=np.uint8)
    return QImage(array.data, array.shape[1], array.shape[0], array.strides[0],
                  QImage.Format.Format_RGBA8888).copy()


# Match UX's clamped, separable box filter with linear-time prefix sums.
def box_blur(array, radius=BLUR_RADIUS):
    if radius <= 0:
        return array.copy()
    if radius > 16:
        raise ValueError("blur radius must be in 0..16")
    result = array
    count = radius * 2 + 1
    for axis in (1, 0):
        pad = [(0, 0)] * result.ndim
        pad[axis] = (radius, radius)
        padded = np.pad(result, pad, mode="edge")
        shape = list(padded.shape)
        shape[axis] += 1
        sums = np.zeros(shape, dtype=np.uint32)
        tail = [slice(None)] * result.ndim
        tail[axis] = slice(1, None)
        np.cumsum(padded, axis=axis, dtype=np.uint32, out=sums[tuple(tail)])
        high, low = list(tail), list(tail)
        high[axis], low[axis] = slice(count, None), slice(None, -count)
        result = ((sums[tuple(high)] - sums[tuple(low)]) // count).astype(np.uint8)
    return result


# Cache the lens map by strip size; its edge bend vanishes toward the centre.
@lru_cache(maxsize=64)
def refraction_map(width, height, strength, context_x=CONTEXT,
                   context_y=CONTEXT, edge_pixels=12):
    yy, xx = np.mgrid[:height, :width].astype(np.float32)
    edge = max(1, min(edge_pixels, width / 2, height / 2))
    dx = strength * (np.maximum(0, 1 - xx / edge) ** 2
                     - np.maximum(0, 1 - (width - 1 - xx) / edge) ** 2)
    dy = strength * (np.maximum(0, 1 - yy / edge) ** 2
                     - np.maximum(0, 1 - (height - 1 - yy) / edge) ** 2)
    return xx + context_x + dx, yy + context_y + dy


# Bilinearly sample the blurred context through a shallow rounded edge lens.
def refract(array, width, height, strength=REFRACTION_PIXELS, *,
            context_x=CONTEXT, context_y=CONTEXT, edge_pixels=12):
    xx, yy = refraction_map(width, height, strength, context_x, context_y, edge_pixels)
    xx = np.clip(xx, 0, array.shape[1] - 1)
    yy = np.clip(yy, 0, array.shape[0] - 1)
    x0, y0 = xx.astype(np.int32), yy.astype(np.int32)
    x1, y1 = np.minimum(x0 + 1, array.shape[1] - 1), np.minimum(y0 + 1, array.shape[0] - 1)
    tx = (xx - x0.astype(np.float32))[..., None]
    ty = (yy - y0.astype(np.float32))[..., None]
    top = array[y0, x0] * (1 - tx) + array[y0, x1] * tx
    bottom = array[y1, x0] * (1 - tx) + array[y1, x1] * tx
    return (top * (1 - ty) + bottom * ty).astype(np.uint8)


# Keep the UX software reference for offscreen reviews, not desktop backdrop sampling.
class SceneFrost:
    def __init__(self, backend):
        self.backend = backend
        self.revision = 0
        self.order = []
        from PyQt6.QtWidgets import QApplication
        self.enabled = (QApplication.platformName() in ("offscreen", "minimal")
                        or os.environ.get("PYSPOS_GLASS_SOFTWARE_PREVIEW") == "1")
        self.wallpaper = QImage()
        self.scaled_wallpaper = None
        self.wallpaper_size = None
        self.cache = {}
        self.compositions = 0

    # Coalesce scene changes through Qt's normal update queue; there is no timer.
    def invalidate(self):
        self.revision += 1
        self.cache.clear()
        for widget in self.backend.windows.values():
            widget.update()

    # Track the service's stacking order without capturing its own host windows.
    def raise_window(self, window_id):
        if window_id in self.order:
            self.order.remove(window_id)
        self.order.append(window_id)
        self.invalidate()

    # Draw the fixed expanded rectangle in screen coordinates, independent of damage.
    def scene(self, target, rect):
        result = QImage(rect.size(), QImage.Format.Format_ARGB32_Premultiplied)
        result.fill(QColor("#263b54"))
        painter = QPainter(result)
        screen = target.screen().geometry()
        if not self.wallpaper.isNull():
            if self.wallpaper_size != screen.size():
                self.scaled_wallpaper = self.wallpaper.scaled(
                    screen.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation)
                self.wallpaper_size = screen.size()
            crop_x = (self.scaled_wallpaper.width() - screen.width()) // 2
            crop_y = (self.scaled_wallpaper.height() - screen.height()) // 2
            painter.drawImage(QRectF(0, 0, rect.width(), rect.height()), self.scaled_wallpaper,
                              QRectF(rect.x() - screen.x() + crop_x,
                                     rect.y() - screen.y() + crop_y, rect.width(), rect.height()))
        for window_id in self.order:
            if window_id == target.window_id:
                break
            widget = self.backend.windows.get(window_id)
            if widget is None or not widget.isVisible() or widget.isMinimized():
                continue
            geometry = QRect(widget.mapToGlobal(widget.rect().topLeft()), widget.size())
            if geometry.intersects(rect):
                window = self.backend.server.model.snapshot(window_id)
                if window:
                    # Foreground-only rendering has its own revision cache.
                    painter.drawImage(geometry.topLeft() - rect.topLeft(), widget.foreground(window))
        painter.end()
        self.compositions += 1
        return result

    # Blur and refract four narrow bands, keeping transparent client pixels untouched.
    def texture(self, widget):
        if not self.enabled:
            return None
        key = (widget.window_id, self.revision, widget.x(), widget.y(),
               widget.width(), widget.height())
        if key in self.cache:
            return self.cache[key]
        image = QImage(widget.size(), QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        frame = widget.layout().frame()
        # Large frames filter at half resolution, retaining the same screen blur radius.
        scale = 2 if widget.width() * widget.height() > 500_000 else 1
        for region in frame["frost"].values():
            x, y, width, height = region
            if width <= 0 or height <= 0:
                continue
            origin = widget.mapToGlobal(widget.rect().topLeft())
            rect = QRect(origin.x() + x - CONTEXT, origin.y() + y - CONTEXT,
                         width + CONTEXT * 2, height + CONTEXT * 2)
            scene = self.scene(widget, rect)
            if scale == 2:
                scene = scene.scaled(max(1, rect.width() // 2), max(1, rect.height() // 2),
                                     Qt.AspectRatioMode.IgnoreAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation)
            source = pixels(scene)
            blurred = box_blur(source, BLUR_RADIUS // scale)
            sample_width, sample_height = max(1, width // scale), max(1, height // scale)
            lens = refract(blurred, sample_width, sample_height, REFRACTION_PIXELS / scale,
                           context_x=(scene.width() - sample_width) / 2,
                           context_y=(scene.height() - sample_height) / 2, edge_pixels=12 / scale)
            painter.drawImage(QRectF(x, y, width, height), image_from_pixels(lens))
        painter.end()
        self.cache[key] = image
        return image
