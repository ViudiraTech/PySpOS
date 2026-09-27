'''
 *
 *      terminal.py
 *      VT terminal emulation over POSIX PTYs or Windows ConPTY.
 *
 *      2026/9/27 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import os
import codecs
from pathlib import Path
import shutil
import sys
import threading
import signal

import pyte
from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter

ANSI = {"black": "#111a26", "red": "#ef6b78", "green": "#86cd9a",
        "brown": "#d9bd7b", "blue": "#729fdb", "magenta": "#bc8bd9",
        "cyan": "#75c9cf", "white": "#d9e3ef", "default": "#d9e3ef"}
CELL_WIDTH, CELL_HEIGHT = 9, 18


# Read a real terminal on one worker and deliver output to the GUI thread.
class Terminal(QObject):
    output = pyqtSignal(str)
    exited = pyqtSignal()

    def __init__(self, columns=80, rows=24, *, argv=None, env=None):
        super().__init__()
        self.screen = pyte.HistoryScreen(columns, rows, history=1000)
        self.stream = pyte.Stream(self.screen)
        environment = dict(os.environ if env is None else env)
        environment["TERM"] = "xterm-256color"
        environment["PYSPOS_GUI_SESSION"] = "1"
        source = str(Path(__file__).resolve().parents[1])
        environment.setdefault("PYSPOS_BOOT_SYSTEM", source)
        environment["PYTHONPATH"] = os.pathsep.join(filter(None, (
            source, environment.get("PYTHONPATH"))))
        python = sys.executable
        if not python or not os.path.isfile(python) or not os.access(python, os.X_OK):
            python = shutil.which("python3" if os.name != "nt" else "python")
        if not python:
            raise RuntimeError("无法找到可执行的 Python 解释器以启动桌面 PTY shell")
        command = argv or [python, "-m", "vortexglass.terminal_shell"]
        if os.name == "nt":
            from winpty import PtyProcess
            self.process = PtyProcess.spawn(command, env=environment, dimensions=(rows, columns))
        else:
            from ptyprocess import PtyProcessUnicode
            self.process = PtyProcessUnicode.spawn(command, env=environment, dimensions=(rows, columns))
            self.process.decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self.screen.write_process_input = self.write
        self.thread = threading.Thread(target=self._read, name="vortexglass-pty", daemon=True)

    # Install output handlers before starting the reader so the first prompt cannot be lost.
    def start(self):
        self.thread.start()

    # Reader ownership ends at PTY EOF; there is no terminal polling loop.
    def _read(self):
        try:
            while True:
                data = self.process.read(4096)
                if not data:
                    continue
                self.output.emit(data)
        except (EOFError, OSError, ValueError):
            pass
        finally:
            self.exited.emit()

    def feed(self, data):
        self.stream.feed(data)

    def write(self, text):
        try:
            self.process.write(text)
        except (OSError, EOFError):
            pass

    # Resize both the terminal emulator and the kernel/ConPTY window dimensions.
    def resize(self, width, height):
        columns, rows = max(20, (width - 16) // CELL_WIDTH), max(4, (height - 16) // CELL_HEIGHT)
        if (columns, rows) != (self.screen.columns, self.screen.lines):
            self.screen.resize(lines=rows, columns=columns)
            self.process.setwinsize(rows, columns)

    # Convert Qt keys to terminal input; Ctrl-C reaches the PTY foreground process group.
    def key(self, key, text, modifiers):
        sequences = {Qt.Key.Key_Return: "\r", Qt.Key.Key_Enter: "\r",
                     Qt.Key.Key_Backspace: "\x7f", Qt.Key.Key_Tab: "\t", Qt.Key.Key_Escape: "\x1b",
                     Qt.Key.Key_Up: "\x1b[A", Qt.Key.Key_Down: "\x1b[B",
                     Qt.Key.Key_Right: "\x1b[C", Qt.Key.Key_Left: "\x1b[D",
                     Qt.Key.Key_Home: "\x1b[H", Qt.Key.Key_End: "\x1b[F",
                     Qt.Key.Key_Delete: "\x1b[3~", Qt.Key.Key_PageUp: "\x1b[5~",
                     Qt.Key.Key_PageDown: "\x1b[6~"}
        if modifiers & Qt.KeyboardModifier.ControlModifier.value and 64 <= key <= 95:
            value = chr(key - 64)
        else:
            value = sequences.get(key, text)
        if value:
            self.write(value)

    # Paint only terminal cells that contain glyphs or a non-default background.
    def paint(self, image, origin):
        painter = QPainter(image)
        font = QFont("monospace")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPixelSize(14)
        painter.setFont(font)
        ox, oy = origin
        for row in range(self.screen.lines):
            for column, cell in self.screen.buffer[row].items():
                x, y = ox + 8 + column * CELL_WIDTH, oy + 8 + row * CELL_HEIGHT
                foreground, background = cell.fg, cell.bg
                if cell.reverse:
                    foreground, background = background, foreground
                if background != "default":
                    painter.fillRect(x, y, CELL_WIDTH, CELL_HEIGHT, self._colour(background))
                if cell.data.strip():
                    font.setBold(cell.bold)
                    font.setUnderline(cell.underscore)
                    painter.setFont(font)
                    painter.setPen(self._colour(foreground))
                    painter.drawText(x, y + 14, cell.data)
        cursor = self.screen.cursor
        if not cursor.hidden:
            painter.fillRect(ox + 8 + cursor.x * CELL_WIDTH, oy + 8 + cursor.y * CELL_HEIGHT + 16,
                             CELL_WIDTH, 2, QColor("#a8d5f2"))
        painter.end()

    def _colour(self, value):
        return QColor(ANSI.get(value, "#" + value))

    # Terminate and reap the PTY session when its window or the whole desktop closes.
    def close(self):
        if os.name == "posix":
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        if self.process.isalive():
            self.process.terminate(force=True)
        self.process.close(force=True)
        if threading.current_thread() is not self.thread:
            self.thread.join(2)
