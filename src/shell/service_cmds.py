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


class _RemoteJournal:
    # Journal subset answered by the host's manager over RPC.
    def __init__(self, call):
        self._call = call

    def lines(self, unit=None):
        return _remote_call(self._call, "sm_journal", unit)


class _RemoteUnits:
    # Unit-name set answered by the host's manager over RPC.
    def __init__(self, call):
        self._call = call

    def __contains__(self, name):
        return bool(_remote_call(self._call, "sm_has_unit", name))


# service_manager.ServiceManager subset answered by the host over RPC.
# Used inside the desktop PTY shell, which is a fresh interpreter without
# the host's in-process manager; every call runs on the host's live manager,
# so lifecycle stays single-owner. The transport is injected for tests.
class _RemoteManager:
    def __init__(self, call):
        self._call = call
        self.journal = _RemoteJournal(call)
        self.units = _RemoteUnits(call)

    def status(self, name=None):
        return _remote_call(self._call, "sm_status", name)

    def resolve(self, names):
        return _remote_call(self._call, "sm_resolve", list(names))

    def start(self, name):
        return _remote_call(self._call, "sm_start", name)

    def stop(self, name):
        return _remote_call(self._call, "sm_stop", name)

    def restart(self, name):
        return _remote_call(self._call, "sm_restart", name)


# Run one RPC call, turning transport and host-side failures into exceptions
# the shell commands already know how to report.
def _remote_call(call, op, *args):
    from service_manager import UnitError
    res = call(op, *args)
    if res is None:
        raise UnitError("System service manager has not booted")
    ok, val = res
    if not ok:
        raise RuntimeError(val)
    return val


# Return the in-process manager, or borrow the host's over RPC inside the
# desktop shell, where no in-process manager exists.
def _manager():
    from service_manager import UnitError, get_manager
    try:
        return get_manager()
    except UnitError:
        pass
    api = _syscall_api()
    if api is not None and api.is_remote():
        return _RemoteManager(api._call)
    raise UnitError("System service manager has not booted")


# Find the child-side RPC module however this interpreter was launched: the
# main shell and pytest have src/apps/ on the path, the desktop PTY shell
# only has src/ (where apps/ resolves as a namespace package).
def _syscall_api():
    try:
        import api
        return api
    except ImportError:
        pass
    try:
        from apps import api as apps_api
        return apps_api
    except ImportError:
        return None


# Accept the legacy service <unit> <action> form and systemctl action <unit>.
def cmd_service(args=""):
    from service_manager import UnitError
    try:
        parts = shlex.split(args)
    except ValueError as exc:
        printk.error(f"service: {exc}\n")
        return 2
    try:
        manager = _manager()
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
    try:
        parts = shlex.split(args)
        if not parts:
            manager = _manager()
            manager.status()
            print("\n".join(manager.journal.lines()))
            return 0
        if len(parts) == 2 and parts[0] == "-u":
            return cmd_service(shlex.join(("logs", parts[1])))
        raise ValueError("用法：journalctl [-u <unit>]")
    except (RuntimeError, ValueError) as exc:
        printk.error(f"journalctl: {exc}\n")
        return 2
