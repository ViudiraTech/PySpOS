'''
 *
 *      check_vortexglass_frost.py
 *      Offscreen frost/refraction review and dirty-versus-cached frame timings.
 *
 *      2026/9/27 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import argparse
import json
import os
from pathlib import Path
import statistics
import sys
import time

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"

import numpy as np
from PyQt6.QtCore import QRect
from PyQt6.QtGui import QColor, QImage, QPainter
from PyQt6.QtWidgets import QApplication

import spaceglass_theme as theme
from vortexglass.frost import image_from_pixels
from vortexglass.qt_backend import Backend
from vortexglass.server import Server


# Render patterned scenery and overlapping windows, then measure complete frame work.
def run():
    parser = argparse.ArgumentParser(description="VortexGlass frost review")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--theme-dir")
    options = parser.parse_args()
    options.output.mkdir(parents=True, exist_ok=True)
    app = QApplication(["Frost review"])
    server = Server(options.output / "unused-endpoint.json", backend="qt")
    report = theme.load_theme(options.theme_dir) if options.theme_dir else None
    backend = Backend(server, report)
    yy, xx = np.mgrid[:1200, :1800]
    pattern = ((xx // 28 + yy // 28) % 2).astype(np.uint8)
    wallpaper = np.empty((1200, 1800, 4), dtype=np.uint8)
    wallpaper[..., 0] = 45 + pattern * 125
    wallpaper[..., 1] = 65 + (1 - pattern) * 105
    wallpaper[..., 2] = 110 + pattern * 100
    wallpaper[..., 3] = 255
    backend.frost.wallpaper = image_from_pixels(wallpaper)
    lower_id = server.model.create(1, {"title": "Background application", "width": 540,
                                       "height": 260, "background": "#3e91b9"})["window"]
    upper_id = server.model.create(2, {"title": "VortexGlass — UX frost + refraction", "width": 540,
                                       "height": 300, "background": "#17283aee"})["window"]
    app.processEvents()
    lower, upper = backend.windows[lower_id], backend.windows[upper_id]
    lower.move(30, 80)
    upper.move(70, 160)
    backend.frost.order = [lower_id, upper_id]
    backend.frost.invalidate()

    # Compare sharp PNG-only rendering with the final composed glass appearance.
    review = QImage(1300, 560, QImage.Format.Format_ARGB32_Premultiplied)
    review.fill(QColor("#182534"))
    painter = QPainter(review)
    for panel, frosted in enumerate((False, True)):
        painter.save()
        painter.translate(panel * 650, 0)
        painter.drawImage(0, 0, backend.frost.scene(lower, QRect(0, 0, 650, 560)))
        painter.drawImage(30, 80, backend.renderer.render(server.model.snapshot(lower_id)))
        painter.drawImage(70, 160, backend.renderer.render(
            server.model.snapshot(upper_id), frost=backend.frost.texture(upper) if frosted else None))
        painter.setPen(QColor("#ffffff"))
        painter.drawText(20, 25, "UX blur + refraction + PNG" if frosted else "PNG only")
        painter.restore()
    painter.end()
    review.save(str(options.output / "comparison.png"))

    timings = {}
    for width, height in ((540, 300), (1600, 1200)):
        upper.resize(width + 24, height + 48)
        app.processEvents()
        dirty, cached = [], []
        for _ in range(31):
            backend.frost.invalidate()
            start = time.perf_counter()
            backend.renderer.render(server.model.snapshot(upper_id), frost=backend.frost.texture(upper))
            dirty.append((time.perf_counter() - start) * 1000)
            start = time.perf_counter()
            backend.frost.texture(upper)
            cached.append((time.perf_counter() - start) * 1000)
        timings[f"{width}x{height}"] = {
            "dirty_frame_median_ms": round(statistics.median(dirty), 3),
            "cached_texture_median_ms": round(statistics.median(cached), 4)}
    (options.output / "review.json").write_text(json.dumps(timings, indent=2))
    print(json.dumps(timings, indent=2))
    for widget in list(backend.windows.values()):
        widget.close()
    backend.native_blur.close()
    server.close()


if __name__ == "__main__":
    run()
