'''
 *
 *      demos.py
 *      Socket-only calculator, clock and transparent canvas demo applications.
 *
 *      2026/9/27 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import argparse
import ast
from datetime import datetime
from decimal import Decimal, DecimalException
import math
import operator
import os
from pathlib import Path
import shlex
import sys
import time

from .client import Client


def label(x, y, value, size=16, color="#e6edf3"):
    return {"type": "text", "x": x, "y": y, "text": value, "size": size, "color": color}


def rectangle(x, y, width, height, color, radius=0):
    return {"type": "rect", "x": x, "y": y, "width": width, "height": height,
            "color": color, "radius": radius}


def button(target, x, y, width, height, value, color="#30465fdc"):
    return {"type": "button", "id": target, "x": x, "y": y, "width": width,
            "height": height, "text": value, "color": color, "size": 18, "radius": 6}


def calculate(expression):
    if not expression or len(expression) > 64:
        raise ValueError("expression length")
    operators = {ast.Add: operator.add, ast.Sub: operator.sub,
                 ast.Mult: operator.mul, ast.Div: operator.truediv}

    def evaluate(node, depth=0):
        if depth > 12:
            raise ValueError("expression depth")
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            result = Decimal(str(node.value))
        elif isinstance(node, ast.BinOp) and type(node.op) in operators:
            result = operators[type(node.op)](evaluate(node.left, depth + 1),
                                               evaluate(node.right, depth + 1))
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            result = evaluate(node.operand, depth + 1)
            if isinstance(node.op, ast.USub):
                result = -result
        else:
            raise ValueError("unsupported expression")
        if not result.is_finite() or abs(result) > Decimal("1e100"):
            raise ValueError("result out of range")
        return result

    return format(evaluate(ast.parse(expression, mode="eval").body).normalize(), "f")


class Calculator:
    title, size, background = "VortexGlass · Calculator", (340, 380), "#132033ec"

    def __init__(self):
        self.expression = ""

    def scene(self, width, _height):
        items = [label(20, 16, "SOCKET CALCULATOR", 12, "#8daacb"),
                 rectangle(16, 44, width - 32, 66, "#091322dc", 8),
                 label(28, 60, self.expression[-22:] or "0", 28)]
        keys = ("7", "8", "9", "/", "4", "5", "6", "*",
                "1", "2", "3", "-", "C", "0", ".", "+")
        cell = (width - 40) // 4
        for index, key in enumerate(keys):
            items.append(button(key, 16 + index % 4 * (cell + 2),
                                126 + index // 4 * 47, cell, 42, key))
        items.append(button("=", 16, 320, width - 32, 42, "=", "#2f7ca6e8"))
        return items

    def handle(self, event):
        key = event.get("target") if event["type"] == "click" else event.get("text", "")
        if event["type"] == "key" and event.get("key") in (16777220, 16777221):
            key = "="
        if key == "C":
            self.expression = ""
        elif key == "=":
            try:
                self.expression = calculate(self.expression)
            except (ValueError, SyntaxError, DecimalException):
                self.expression = "Error"
        elif key and key in "0123456789.+-*/()" and len(self.expression) < 64:
            if self.expression == "Error":
                self.expression = ""
            self.expression += key
        else:
            return False
        return True


class Clock:
    title, size, background = "VortexGlass · Clock", (440, 190), "#142136a8"

    def scene(self, width, _height):
        now = datetime.now()
        return [label(24, 18, "LOCAL SOCKET · SYSTEM CLOCK", 12, "#a7bfd9"),
                label(24, 48, now.strftime("%H:%M:%S"), 54),
                label(26, 120, now.strftime("%A, %Y-%m-%d"), 17),
                button("close", width - 106, 145, 80, 30, "Close")]

    def handle(self, _event):
        return False


class Canvas:
    title, size, background = "VortexGlass · Transparent canvas", (540, 340), "#00000000"

    def __init__(self):
        self.marks = []
        self.alpha = 144

    def scene(self, _width, _height):
        suffix = f"{self.alpha:02x}"
        return [label(22, 18, "The desktop remains visible between shapes", 16),
                rectangle(24, 64, 240, 170, "#397aa6" + suffix, 18),
                rectangle(160, 102, 250, 172, "#7358ba" + suffix, 18),
                rectangle(310, 52, 188, 166, "#37a78b" + suffix, 18),
                label(42, 86, "RGBA through a socket", 22),
                label(42, 126, "Click the canvas to add a mark", 14),
                button("alpha", 24, 290, 170, 32, f"Alpha: {self.alpha}"),
                button("clear", 204, 290, 130, 32, "Clear"),
                button("close", 344, 290, 130, 32, "Close")] + self.marks

    def handle(self, event):
        if event["type"] != "click":
            return False
        if event.get("target") == "alpha":
            self.alpha = 64 if self.alpha >= 224 else self.alpha + 40
        elif event.get("target") == "clear":
            self.marks.clear()
        elif not event.get("target"):
            self.marks.append(rectangle(event["x"] - 12, event["y"] - 12, 24, 24, "#fff1b0c0", 12))
            self.marks = self.marks[-96:]
        else:
            return False
        return True


DEMOS = {"calc": Calculator, "clock": Clock, "canvas": Canvas}


def run_demo(kind="canvas", argv=None):
    parser = argparse.ArgumentParser(description="VortexGlass socket GUI client")
    parser.add_argument("--endpoint")
    parser.add_argument("--capture", help="save a service-rendered PNG and exit")
    parser.add_argument("--duration", type=float, help="exit after N seconds")
    parser.add_argument("--title")
    parser.add_argument("--size")
    if argv is None:
        argv = shlex.split(os.environ.get("PYSPOS_APP_ARGS", ""))
    options = parser.parse_args(argv)
    if options.duration is not None and (not math.isfinite(options.duration) or not 0 <= options.duration <= 3600):
        parser.error("duration must be in 0..3600 seconds")
    demo = DEMOS[kind]()
    width, height = demo.size
    if options.size:
        try:
            width, height = map(int, options.size.lower().split("x"))
        except ValueError:
            parser.error("size must be WIDTHxHEIGHT")
    try:
        with Client(options.endpoint) as client:
            window = client.create(options.title or demo.title, width, height, demo.background)
            client.present(window, demo.scene(width, height))
            if options.capture:
                Path(options.capture).write_bytes(client.snapshot(window))
                if options.duration is None:
                    return
            print(f"{demo.title}: window {window}, compositor={client.info['backend']}", flush=True)
            deadline = None if options.duration is None else time.monotonic() + options.duration
            while deadline is None or time.monotonic() < deadline:
                wait = None if deadline is None else max(0, deadline - time.monotonic())
                if kind == "clock":
                    wait = min(wait, 1) if wait is not None else 1
                event = client.next_event(wait)
                if event is None:
                    if kind == "clock":
                        client.present(window, demo.scene(width, height))
                    continue
                if event["type"] == "close":
                    break
                if event.get("target") == "close" or (event["type"] == "key" and event.get("key") == 16777216):
                    client.destroy(window)
                    break
                if event["type"] == "resize":
                    width, height = event["width"], event["height"]
                if event["type"] == "resize" or demo.handle(event):
                    client.present(window, demo.scene(width, height))
    except KeyboardInterrupt:
        return
    except (OSError, ValueError, ConnectionError) as exc:
        raise SystemExit(f"GUI client: {exc}. Start it with service vortexglass start.") from exc


if __name__ == "__main__":
    kind = sys.argv[1] if len(sys.argv) > 1 else "canvas"
    if kind not in DEMOS:
        raise SystemExit("usage: python -m vortexglass.demos calc|clock|canvas [options]")
    run_demo(kind, sys.argv[2:])
