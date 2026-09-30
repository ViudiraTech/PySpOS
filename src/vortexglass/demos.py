"""Compatibility launcher for old commands. Applications live in apps/, not in the compositor."""

import importlib
import sys

# Compatibility exports for third-party scripts and existing screenshot tools.
from apps.guicalc import Calculator, calculate
from apps.guicanvas import Canvas
from apps.guiclock import Clock
from apps.guifiles import Files
from apps.guimonitor import Monitor
from apps.guinotes import Notes
from .drawing import button, label, rectangle

DEMOS = {"calc": Calculator, "clock": Clock, "canvas": Canvas,
         "notes": Notes, "files": Files, "monitor": Monitor}
MODULES = {"calc": "guicalc", "clock": "guiclock", "canvas": "guicanvas",
           "notes": "guinotes", "files": "guifiles", "monitor": "guimonitor"}


def run_demo(kind="canvas", argv=None):
    importlib.import_module(f"apps.{MODULES[kind]}").main(argv)


if __name__ == "__main__":
    kind = sys.argv[1] if len(sys.argv) > 1 else "canvas"
    if kind not in DEMOS:
        raise SystemExit("usage: python -m vortexglass.demos calc|clock|canvas|notes|files|monitor [options]")
    run_demo(kind, sys.argv[2:])
