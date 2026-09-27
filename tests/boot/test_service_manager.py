'''
 *
 *      test_service_manager.py
 *      Unit graph transactions, failure isolation, shutdown and journal commands.
 *
 *      2026/9/27 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import pytest

from service_manager import Journal, ServiceManager, Unit, UnitError, set_manager


# Keep unit tests independent of the desktop and the process table.
def manager():
    return ServiceManager(journal=Journal(emit=None))


# Requirement and ordering edges remain separate, including absent After units.
def test_after_does_not_pull_units_and_requires_does_not_imply_order():
    service = manager()
    calls = []
    service.add(Unit("z.service", start=lambda: calls.append("z")))
    service.add(Unit("a.service", requires=("z.service",), after=("missing.service",),
                     start=lambda: calls.append("a")))
    service.start("a.service")
    assert calls == ["a", "z"]
    assert "missing.service" not in service.units


# Validate cycles before any irreversible start callback executes.
def test_order_cycle_is_rejected_before_start():
    service = manager()
    calls = []
    service.add(Unit("a.service", requires=("b.service",), after=("b.service",),
                     start=lambda: calls.append("a")))
    service.add(Unit("b.service", after=("a.service",), start=lambda: calls.append("b")))
    with pytest.raises(UnitError, match="Ordering cycle"):
        service.start("a.service")
    assert calls == []


# A required startup failure blocks ordered dependents but optional failures do not.
def test_required_failure_and_optional_target():
    service = manager()
    calls = []

    def fail():
        raise RuntimeError("broken backend")

    service.add(Unit("bad.service", start=fail))
    service.add(Unit("required.service", requires=("bad.service",), after=("bad.service",),
                     start=lambda: calls.append("required")))
    service.add(Unit("desktop.target", kind="target", wants=("bad.service", "missing.service")))
    with pytest.raises(UnitError, match="Required unit failed"):
        service.start("required.service")
    assert service.status("required.service")["result"] == "dependency"
    assert service.start("desktop.target")["state"] == "active"
    assert calls == []
    assert any("broken backend" in line for line in service.journal.lines())


# Stops and restarts propagate to active required dependents in reverse order.
def test_stop_and_restart_order():
    service = manager()
    calls = []
    for name, dependency in (("storage.service", None), ("app.service", "storage.service")):
        service.add(Unit(name, requires=(dependency,) if dependency else (),
                         after=(dependency,) if dependency else (),
                         start=lambda name=name: calls.append("start " + name),
                         stop=lambda name=name: calls.append("stop " + name)))
    service.start("app.service")
    service.restart("storage.service")
    assert calls == ["start storage.service", "start app.service", "stop app.service",
                     "stop storage.service", "start storage.service", "start app.service"]
    service.shutdown()
    assert calls[-2:] == ["stop app.service", "stop storage.service"]


# Failed startup releases partially acquired resources exactly once.
def test_partial_start_is_cleaned_and_shutdown_continues_after_stop_error():
    service = manager()
    calls = []

    def fail():
        raise RuntimeError("cannot start")

    service.add(Unit("bad.service", start=fail, stop=lambda: calls.append("cleanup")))
    with pytest.raises(UnitError):
        service.start("bad.service")
    service.shutdown()
    assert calls == ["cleanup"]
    service.add(Unit("good.service", start=lambda: None, stop=lambda: calls.append("good")))
    service.add(Unit("stop-error.service", start=lambda: None, stop=fail))
    service.start("good.service")
    service.start("stop-error.service")
    with pytest.raises(UnitError, match="cannot start"):
        service.shutdown()
    assert "good" in calls


# A dead process is reported as failed and its stdout keeps its unit and PID.
def test_live_probe_and_child_journal():
    service = manager()
    output = ["child ready"]

    def logs():
        result = list(output)
        output.clear()
        return result

    unit = service.add(Unit("daemon.service", kind="simple", start=lambda: {"pid": 7},
                            probe=lambda: {"state": "stopped"}, read_logs=logs))
    with pytest.raises(UnitError, match="Service exited unexpectedly"):
        service.start("daemon.service")
    assert service.status("daemon.service")["state"] == "failed"
    assert unit.result == "exit-code"
    assert any(e["pid"] == 7 and e["message"] == "child ready" for e in service.journal.entries)


# Reject unsupported unit directives instead of silently ignoring dependencies.
def test_unit_files_and_commands(tmp_path, capsys):
    service = manager()
    (tmp_path / "test.service").write_text(
        "[Unit]\nDescription=Test service\n[Service]\nType=oneshot\nExecStart=test\n")
    service.load(tmp_path, {"test": lambda: None})
    set_manager(service)
    from shell.service_cmds import cmd_service, cmd_journalctl
    assert cmd_service("start test") == 0
    assert cmd_service("test status") == 0
    assert cmd_service("list-dependencies test") == 0
    assert cmd_journalctl("-u test") == 0
    assert "init[1]: test.service:" in capsys.readouterr().out
    assert cmd_service("stop test") == 0
    assert cmd_service("status test") == 3
    (tmp_path / "bad.service").write_text("[Unit]\nUnknownSetting=yes\n")
    with pytest.raises(UnitError, match="Unsupported setting"):
        manager().load(tmp_path, {})


# Stopping the tracked shell session returns input ownership to its supervisor.
def test_shell_stop_exits_the_command_loop(monkeypatch):
    import kernel
    kernel.start_shell_session()
    calls = []
    monkeypatch.setattr(kernel, "print_prompt", lambda: "test> ")
    monkeypatch.setattr("builtins.input", lambda _prompt: calls.append("input") or "stop")
    monkeypatch.setattr(kernel.main, "handle_command", lambda _line: kernel.stop_shell_session())
    kernel._command_loop()
    assert calls == ["input"]
    kernel.start_shell_session()
