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


# Bullet colour per lifecycle state: the one glanceable signal in systemctl's
# most-used output. Idle states stay uncoloured so failures stand out.
_STATE_COLOR = {"active": printk.GREEN_COLOR,
                "failed": printk.RED_COLOR,
                "activating": printk.YELLOW_COLOR,
                "deactivating": printk.YELLOW_COLOR}

# Fields the status block prints itself. Anything else a unit's probe adds is
# appended after them rather than dropped.
_STATUS_FIELDS = {"name", "description", "type", "state", "result", "error",
                  "elapsed", "requires", "wants", "after", "before"}

_ACTION_VERB = {"start": "已启动", "stop": "已停止", "restart": "已重启"}


# Human-readable duration. Most units finish in microseconds and printing the
# raw float gives scientific notation like 6.199999916134402e-06.
def _duration(seconds):
    if seconds is None:
        return "—"
    if seconds < 1e-3:
        return f"{seconds * 1e6:.0f}µs"
    if seconds < 1:
        return f"{seconds * 1e3:.1f}ms"
    if seconds < 60:
        return f"{seconds:.2f}s"
    return f"{seconds / 60:.1f}分"


# One status value: dependency lists join, floats keep two decimals, the rest is
# whatever str() gives.
def _value(value):
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value)
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


# Print a unit the way systemctl status does: a coloured bullet, then the fields
# the unit actually sets. Absent dependency lists are omitted rather than shown
# blank, and probe-specific detail is appended as plain lines instead of the raw
# dict, which is what this used to dump.
def _print_status(state):
    color = _STATE_COLOR.get(state["state"], "")
    print(f"{color}●{printk.RESET_COLOR} {state['name']} - {state['description']}")
    headline = f"{state['state']} ({state['result']})"
    if state.get("error"):
        headline += f" — {state['error']}"
    print(f"状态: {color}{headline}{printk.RESET_COLOR}")
    print(f"类型: {state['type']}")
    print(f"耗时: {_duration(state.get('elapsed'))}")
    for key in ("requires", "wants", "after", "before"):
        if state.get(key):
            print(f"{key.capitalize()}: {_value(state[key])}")
    for key in sorted(set(state) - _STATUS_FIELDS):
        print(f"{key}: {_value(state[key])}")


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
        elif action == "status":
            state = manager.status(name)
            _print_status(state)
            if state["state"] != "active":
                return 3
        else:
            getattr(manager, action)(name)
            printk.ok(f"{_ACTION_VERB[action]} {name}")
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
