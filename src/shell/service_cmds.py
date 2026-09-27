'''
 *
 *      service_cmds.py
 *      Shell lifecycle controls, dependency inspection and unit journal.
 *
 *      2026/9/27 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import json
import shlex

import printk


# Accept the legacy service <unit> <action> form and systemctl action <unit>.
def cmd_service(args=""):
    from service_manager import UnitError, get_manager
    try:
        parts = shlex.split(args)
    except ValueError as exc:
        printk.error(f"service: {exc}\n")
        return 2
    try:
        manager = get_manager()
        if not parts or parts == ["list-units"]:
            for unit in manager.status():
                print(f"{unit['name']:<28} {unit['state']:<12} {unit['description']}")
            return 0
        actions = ("start", "stop", "restart", "status", "list-dependencies", "logs")
        if len(parts) != 2:
            raise ValueError("用法：systemctl start|stop|restart|status|list-dependencies|logs <unit>")
        action, name = parts if parts[0] in actions else (parts[1], parts[0])
        if action not in actions:
            raise ValueError("未知服务操作: " + action)
        if not name.endswith((".service", ".target")):
            name += ".service"
        if name not in manager.units:
            raise UnitError("Unit not found: " + name)
        if action == "logs":
            manager.status(name)
            print("\n".join(manager.journal.lines(name)))
        elif action == "list-dependencies":
            order, _, missing = manager.resolve((name,))
            print("\n".join(order))
            for owner, dependencies in missing.items():
                print(f"{owner}: missing {', '.join(dependencies)}")
        else:
            if action in ("start", "stop", "restart"):
                getattr(manager, action)(name)
            state = manager.status(name)
            print(json.dumps(state, ensure_ascii=False, indent=2))
            if action == "status" and state["state"] != "active":
                return 3
        return 0
    except ValueError as exc:
        printk.error(f"service: {exc}\n")
        return 2
    except (RuntimeError, OSError) as exc:
        printk.error(f"service: {exc}\n")
        return 1


# Print the whole runtime journal or filter it with journalctl -u <unit>.
def cmd_journalctl(args=""):
    from service_manager import get_manager
    try:
        parts = shlex.split(args)
        if not parts:
            get_manager().status()
            print("\n".join(get_manager().journal.lines()))
            return 0
        if len(parts) == 2 and parts[0] == "-u":
            return cmd_service(shlex.join(("logs", parts[1])))
        raise ValueError("用法：journalctl [-u <unit>]")
    except (RuntimeError, ValueError) as exc:
        printk.error(f"journalctl: {exc}\n")
        return 2
