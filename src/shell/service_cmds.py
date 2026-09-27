'''
 *
 *      service_cmds.py
 *      Shell lifecycle controls for the system-owned VortexGlass compositor.
 *
 *      2026/9/27 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import json
import shlex

import printk


def cmd_service(args=""):
    from vortexglass.service import manager
    try:
        parts = shlex.split(args)
    except ValueError as exc:
        printk.error(f"service: {exc}\n")
        return 2
    if not parts:
        print(json.dumps(manager.status(), ensure_ascii=False, indent=2))
        return 0
    if len(parts) != 2 or parts[0] != "vortexglass" or parts[1] not in (
            "start", "stop", "restart", "status"):
        printk.error("用法：service vortexglass start|stop|restart|status\n")
        return 2
    try:
        if parts[1] in ("stop", "restart"):
            manager.stop()
        if parts[1] in ("start", "restart"):
            manager.start()
        print(json.dumps(manager.status(), ensure_ascii=False, indent=2))
        return 0
    except RuntimeError as exc:
        printk.error(f"service: {exc}\n")
        return 1
