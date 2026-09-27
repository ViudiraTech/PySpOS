'''
 *
 *      daemon.py
 *      VortexGlass service entry point with desktop, offscreen and headless modes.
 *
 *      2026/9/27 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import argparse
import os
import signal
import socket
import sys

from .protocol import endpoint_path
from .server import Server

CONTROL_ENV = "PYSPOS_VORTEXGLASS_CONTROL"


def parser():
    result = argparse.ArgumentParser(description="VortexGlass system compositor")
    result.add_argument("--endpoint", default=str(endpoint_path()))
    result.add_argument("--theme-dir")
    modes = result.add_mutually_exclusive_group()
    modes.add_argument("--headless", action="store_true", help="socket/model only, no display required")
    modes.add_argument("--offscreen", action="store_true", help="Qt rendering without visible host windows")
    return result


def run(argv=None):
    options = parser().parse_args(argv)
    graphical = options.offscreen or (not options.headless and (
        os.name == "nt" or sys.platform == "darwin" or os.environ.get("DISPLAY")
        or os.environ.get("WAYLAND_DISPLAY")))
    server = Server(options.endpoint, control_token=os.environ.pop(CONTROL_ENV, None),
                    backend="qt" if graphical else "headless")
    if not graphical:
        signal.signal(signal.SIGTERM, lambda *_args: server.stop())
        signal.signal(signal.SIGINT, lambda *_args: server.stop())
        print(f"VortexGlass headless service: {options.endpoint}", flush=True)
        server.run()
        return

    if options.offscreen:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    try:
        from PyQt6.QtWidgets import QApplication
        if options.offscreen:
            from .qt_backend import Backend
        else:
            from .quick_backend import Backend
    except ImportError as exc:
        if options.offscreen:
            server.close()
            raise SystemExit(f"VortexGlass Qt backend unavailable: {exc}; "
                             "install requirements-gui.txt and Qt runtime libraries") from exc
        server.backend = "headless"
        signal.signal(signal.SIGTERM, lambda *_args: server.stop())
        signal.signal(signal.SIGINT, lambda *_args: server.stop())
        print(f"VortexGlass: Qt backend unavailable ({exc}); starting headless socket service. "
              "Install requirements-gui.txt and Qt runtime libraries for desktop windows.", flush=True)
        server.run()
        return
    import spaceglass_theme as theme
    report = None
    try:
        loaded = theme.load_theme(options.theme_dir)
        if theme.theme_complete(loaded):
            report = loaded
        else:
            print("VortexGlass: incomplete theme, using built-in translucent frame", flush=True)
    except FileNotFoundError:
        if options.theme_dir:
            server.close()
            raise
        print("VortexGlass: theme not installed, using built-in translucent frame", flush=True)
    app = QApplication(["VortexGlass"])
    app.setApplicationName("VortexGlass")
    app.setDesktopFileName("org.pyspos.VortexGlass")
    backend = Backend(server, report)
    print(f"VortexGlass Qt service: {options.endpoint}", flush=True)
    # Wake Qt on OS signals without a periodic Python timer. Otherwise an idle
    # app.exec() can leave SIGINT pending until another GUI event reaches Python.
    from PyQt6.QtCore import QSocketNotifier
    signal_read, signal_write = socket.socketpair()
    signal_read.setblocking(False)
    signal_write.setblocking(False)
    notifier = QSocketNotifier(signal_read.fileno(), QSocketNotifier.Type.Read)

    def received_signal(*_args):
        try:
            signal_read.recv(4096)
        except BlockingIOError:
            pass
        server.stop()

    notifier.activated.connect(received_signal)
    previous_fd = signal.set_wakeup_fd(signal_write.fileno())
    previous_handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    for sig in previous_handlers:
        signal.signal(sig, lambda *_args: server.stop())
    try:
        return backend.run()
    finally:
        notifier.setEnabled(False)
        signal.set_wakeup_fd(previous_fd)
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)
        signal_read.close()
        signal_write.close()
        server.close()
        del app


if __name__ == "__main__":
    run()
