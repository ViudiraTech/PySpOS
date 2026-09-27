'''
 *
 *      gui_cmd.py
 *      Start the optional desktop service and return when its session closes.
 *
 *      2026/9/27 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import os
import sys

import printk


# Start GUI only on an explicit command; applications launch from its PTY shell.
def cmd_gui():
    if os.environ.get("PYSPOS_GUI_SESSION") == "1":
        printk.info("桌面已经启动，可运行 guicalc、guiclock 或 guicanvas。\n")
        return 0
    if os.name != "nt" and sys.platform != "darwin" and not (
            os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        printk.error("gui: 当前没有可用的图形显示。\n")
        return 1
    from service_manager import get_manager
    from vortexglass.service import manager as graphics
    manager = get_manager()
    try:
        manager.start("vortexglass.service")
        while graphics.handle and graphics.handle.is_alive():
            graphics.handle.join(0.5)
        return 0
    except KeyboardInterrupt:
        return 130
    except (RuntimeError, OSError) as exc:
        printk.error(f"gui: {exc}\n")
        return 1
    finally:
        manager.stop("vortexglass.service")
