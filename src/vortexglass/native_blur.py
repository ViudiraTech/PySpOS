'''
 *
 *      native_blur.py
 *      Optional X11/KWin blur-region hints for the host compositor.
 *
 *      2026/9/27 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import ctypes
import ctypes.util

from PyQt6.QtWidgets import QApplication


# Send the standard KWin blur hint without depending on a C++ Qt/KF ABI.
class NativeBlur:
    def __init__(self):
        self.display = None
        self.xlib = None
        if QApplication.platformName() != "xcb":
            return
        name = ctypes.util.find_library("X11")
        if not name:
            return
        self.xlib = ctypes.CDLL(name)
        pointer, xid = ctypes.c_void_p, ctypes.c_ulong
        self.xlib.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self.xlib.XOpenDisplay.restype = pointer
        self.xlib.XInternAtom.argtypes = [pointer, ctypes.c_char_p, ctypes.c_int]
        self.xlib.XInternAtom.restype = xid
        self.xlib.XChangeProperty.argtypes = [pointer, xid, xid, xid, ctypes.c_int,
                                            ctypes.c_int, pointer, ctypes.c_int]
        self.xlib.XFlush.argtypes = [pointer]
        self.xlib.XCloseDisplay.argtypes = [pointer]
        self.display = self.xlib.XOpenDisplay(None)
        if self.display:
            self.atom = self.xlib.XInternAtom(self.display, b"_KDE_NET_WM_BLUR_BEHIND_REGION", 1)

    # Request GPU backdrop blur only for the actual glass bands.
    def apply(self, widget):
        if not self.display or not self.atom:
            return False
        values = [value for rect in widget.layout().frame()["frost"].values() for value in rect]
        data = (ctypes.c_ulong * len(values))(*values)
        self.xlib.XChangeProperty(self.display, int(widget.winId()), self.atom,
                                  6, 32, 0, ctypes.cast(data, ctypes.c_void_p), len(values))
        self.xlib.XFlush(self.display)
        return True

    # Release the independent X connection when the service stops.
    def close(self):
        if self.display:
            self.xlib.XCloseDisplay(self.display)
            self.display = None
