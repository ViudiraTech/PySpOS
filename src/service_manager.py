'''
 *
 *      service_manager.py
 *      Portable unit transactions, dependency ordering and boot journal.
 *
 *      2026/9/27 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

from collections import deque
import configparser
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import shlex
import threading
import time


# Report a unit definition or lifecycle failure to the boot or shell caller.
class UnitError(RuntimeError):
    pass


# Keep a unit's dependency definition and current lifecycle state together.
@dataclass
class Unit:
    name: str
    description: str = ""
    kind: str = "oneshot"
    requires: tuple = ()
    wants: tuple = ()
    after: tuple = ()
    before: tuple = ()
    start: object = None
    stop: object = None
    probe: object = None
    state: str = "inactive"
    result: str = "success"
    error: str = ""
    detail: dict = field(default_factory=dict)
    elapsed: float = 0.0
    cleanup_pending: bool = False
    read_logs: object = None


# Store bounded structured entries and print systemd-style boot status lines.
class Journal:
    def __init__(self, emit=print, limit=2048):
        self.entries = deque(maxlen=limit)
        self.emit = emit

    # Record one transition and optionally print its boot status badge.
    def write(self, unit, message, *, result="info", pid=1):
        entry = {"timestamp": time.time(), "unit": unit, "pid": pid,
                 "result": result, "message": str(message)}
        self.entries.append(entry)
        if self.emit:
            badges = {"success": "[  OK  ]", "failed": "[FAILED]",
                      "dependency": "[DEPEND]", "starting": "[ .... ]"}
            self.emit(f"{badges.get(result, '[ INFO ]')} {message}")
        return entry

    # Format the whole journal or the entries belonging to one unit.
    def lines(self, unit=None):
        return [f"{datetime.fromtimestamp(e['timestamp']):%b %d %H:%M:%S} "
                f"PySpOS init[{e['pid']}]: {e['unit']}: {e['message']}"
                for e in self.entries if unit is None or e["unit"] == unit]


# Pull Requires/Wants into transactions and order only by After/Before.
class ServiceManager:
    def __init__(self, *, journal=None):
        self.units = {}
        self.journal = journal if journal is not None else Journal()
        self.lock = threading.RLock()

    # Register one unit; targets order themselves after their dependencies.
    def add(self, unit):
        if unit.name in self.units:
            raise UnitError(f"Duplicate unit: {unit.name}")
        if unit.kind not in ("target", "oneshot", "simple"):
            raise UnitError(f"Unsupported unit type: {unit.kind}")
        if unit.kind == "target":
            unit.after = tuple(dict.fromkeys((*unit.after, *unit.requires, *unit.wants)))
        self.units[unit.name] = unit
        return unit

    # Load unit files, resolving ExecStart/ExecStop through registered callbacks.
    # Unknown settings fail before any callback runs.
    def load(self, directory, actions):
        allowed = {"Unit": {"Description", "Requires", "Wants", "After", "Before"},
                   "Service": {"Type", "ExecStart", "ExecStop"}}
        loaded = []
        for path in sorted(Path(directory).iterdir()):
            if path.suffix not in (".service", ".target"):
                continue
            parser = configparser.ConfigParser(interpolation=None)
            parser.optionxform = str
            try:
                with path.open(encoding="utf-8") as stream:
                    parser.read_file(stream)
                for section in parser.sections():
                    if section not in allowed or set(parser[section]) - allowed[section]:
                        raise UnitError(f"Unsupported setting in {path.name}: {section}")
                meta = parser["Unit"] if parser.has_section("Unit") else {}
                service = parser["Service"] if parser.has_section("Service") else {}
                callbacks = {}
                for setting in ("ExecStart", "ExecStop"):
                    action = service.get(setting)
                    if action and action not in actions:
                        raise UnitError(f"Unknown action {action} in {path.name}")
                    callbacks[setting] = actions.get(action)
                loaded.append(Unit(
                    path.name, meta.get("Description", path.stem),
                    "target" if path.suffix == ".target" else service.get("Type", "oneshot"),
                    tuple(shlex.split(meta.get("Requires", ""))),
                    tuple(shlex.split(meta.get("Wants", ""))),
                    tuple(shlex.split(meta.get("After", ""))),
                    tuple(shlex.split(meta.get("Before", ""))),
                    start=callbacks["ExecStart"], stop=callbacks["ExecStop"]))
            except (configparser.Error, ValueError) as exc:
                raise UnitError(f"Invalid unit {path.name}: {exc}") from exc
        for unit in loaded:
            self.add(unit)

    # Validate and order the entire transaction before starting any callback.
    def resolve(self, names):
        selected = set()
        missing = {}

        # Collect requirement edges without mistaking them for ordering edges.
        def pull(name):
            if name in selected:
                return
            if name not in self.units:
                raise UnitError(f"Unit not found: {name}")
            selected.add(name)
            unit = self.units[name]
            for dep in (*unit.requires, *unit.wants):
                if dep in self.units:
                    pull(dep)
                else:
                    missing.setdefault(name, []).append(dep)

        for name in names:
            pull(name)
        predecessors = {name: set() for name in selected}
        for name in selected:
            unit = self.units[name]
            predecessors[name].update(dep for dep in unit.after if dep in selected)
            for dep in unit.before:
                if dep in selected:
                    predecessors[dep].add(name)
        order = []
        todo = {name: set(deps) for name, deps in predecessors.items()}
        while todo:
            ready = sorted(name for name, deps in todo.items() if not deps)
            if not ready:
                raise UnitError("Ordering cycle: " + " -> ".join(sorted(todo)))
            for name in ready:
                order.append(name)
                del todo[name]
            for deps in todo.values():
                deps.difference_update(ready)
        return order, predecessors, missing

    # Start dependencies first where ordered and isolate optional failures.
    def start(self, name):
        with self.lock:
            order, predecessors, missing = self.resolve((name,))
            for current in order:
                unit = self.units[current]
                if unit.state == "active":
                    self.status(current)
                    if unit.state == "active":
                        continue
                failed = [dep for dep in unit.requires
                          if dep not in self.units or (
                              dep in predecessors[current]
                              and self.units[dep].state != "active")]
                if failed:
                    unit.state, unit.result = "failed", "dependency"
                    unit.error = "Required unit failed: " + ", ".join(failed)
                    self.journal.write(current, unit.error, result="dependency")
                    continue
                for dep in missing.get(current, ()):
                    self.journal.write(current, f"Optional unit not found: {dep}")
                unit.state, unit.result, unit.error = "activating", "success", ""
                self.journal.write(current, f"Starting {unit.description}...", result="starting")
                started = time.monotonic()
                unit.cleanup_pending = bool(unit.stop)
                try:
                    detail = unit.start() if unit.start else None
                    unit.detail = detail if isinstance(detail, dict) else {}
                    self._collect_logs(unit)
                    unit.state = "active"
                    verb = "Reached target" if unit.kind == "target" else "Started"
                    self.journal.write(current, f"{verb} {unit.description}.", result="success")
                except Exception as exc:
                    unit.state, unit.result, unit.error = "failed", "exit-code", str(exc)
                    # Partial startup still owns resources and must be unwound.
                    if unit.stop:
                        try:
                            unit.stop()
                            unit.cleanup_pending = False
                        except Exception as cleanup:
                            self.journal.write(current, f"Startup cleanup failed: {cleanup}", result="failed")
                    self.journal.write(current, f"Failed to start {unit.description}: {exc}", result="failed")
                    self._collect_logs(unit)
                except BaseException:
                    unit.state, unit.result = "failed", "interrupted"
                    raise
                finally:
                    unit.elapsed = time.monotonic() - started
            if self.units[name].state != "active":
                raise UnitError(self.units[name].error or f"Failed to start {name}")
            status = self.status(name)
            if status["state"] != "active":
                raise UnitError(status["error"] or f"Failed to start {name}")
            return status

    # Collect the requested units and their active required dependents.
    def _stop_set(self, names):
        selected = set(names)
        # Requires propagates explicit stop, even without an ordering edge.
        while True:
            additions = {name for name, unit in self.units.items()
                         if unit.state == "active" and set(unit.requires) & selected} - selected
            if not additions:
                break
            selected.update(additions)
        order, _, _ = self.resolve(selected)
        return [name for name in reversed(order) if name in selected]

    # Stop one unit and its required dependents in reverse dependency order.
    def stop(self, name):
        with self.lock:
            if name not in self.units:
                raise UnitError(f"Unit not found: {name}")
            return self._stop(self._stop_set((name,)))

    # Attempt every cleanup even if an earlier stop callback fails.
    def _stop(self, names):
        errors = []
        for name in names:
            unit = self.units[name]
            if unit.state not in ("active", "failed"):
                continue
            unit.state = "deactivating"
            try:
                if unit.stop and unit.cleanup_pending:
                    unit.stop()
                    unit.cleanup_pending = False
                self._collect_logs(unit)
                unit.state, unit.result, unit.error = "inactive", "success", ""
                self.journal.write(name, f"Stopped {unit.description}.", result="success")
            except Exception as exc:
                unit.state, unit.result, unit.error = "failed", "exit-code", str(exc)
                errors.append(f"{name}: {exc}")
                self.journal.write(name, f"Failed to stop {unit.description}: {exc}", result="failed")
        if errors:
            raise UnitError("; ".join(errors))

    # Restart the unit and restore the required dependents that were active.
    def restart(self, name):
        with self.lock:
            selected = self._stop_set((name,))
            active = {n for n in selected if self.units[n].state == "active"}
            self._stop(selected)
            self.start(name)
            for dependent in reversed(selected):
                if dependent in active and dependent != name:
                    self.start(dependent)
            return self.status(name)

    # Unwind all active and failed units when the session exits or restarts.
    def shutdown(self):
        with self.lock:
            # Include failed units, so resources from unsuccessful boots unwind.
            names = [name for name in self.units if self.units[name].state in ("active", "failed")]
            if names:
                order, _, _ = self.resolve(names)
                self._stop(reversed(order))

    # Report live state, probing a process-backed service when requested.
    def status(self, name=None):
        with self.lock:
            if name is None:
                return [self.status(n) for n in sorted(self.units)]
            if name not in self.units:
                raise UnitError(f"Unit not found: {name}")
            unit = self.units[name]
            self._collect_logs(unit)
            if unit.state == "active" and unit.probe:
                detail = unit.probe()
                unit.detail.update(detail)
                if detail.get("state") in ("failed", "stopped"):
                    unit.state, unit.result = "failed", "exit-code"
                    unit.error = detail.get("error") or "Service exited unexpectedly"
                    self.journal.write(name, unit.error, result="failed")
            return {**unit.detail, "name": name, "description": unit.description,
                    "type": unit.kind, "state": unit.state, "result": unit.result,
                    "error": unit.error, "elapsed": unit.elapsed,
                    "requires": list(unit.requires), "wants": list(unit.wants),
                    "after": list(unit.after), "before": list(unit.before)}

    # Attribute child stdout to its unit and keep it after the process stops.
    def _collect_logs(self, unit):
        if unit.read_logs:
            for line in unit.read_logs():
                self.journal.write(unit.name, line, pid=unit.detail.get("pid") or 1)


_manager = None


# Publish the runtime's manager for shell lifecycle commands.
def set_manager(manager):
    global _manager
    _manager = manager


# Return the booted manager, refusing commands before initialization.
def get_manager():
    if _manager is None:
        raise UnitError("System service manager has not booted")
    return _manager
