'''
 *
 *      test_vortexglass_service.py
 *      Kernel boot and exit lifecycle of the VortexGlass system service.
 *
 *      2026/9/27 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import pytest


@pytest.mark.parametrize("exit_code", [0, 42])
def test_kernel_stops_compositor_on_shutdown_and_hotreset(monkeypatch, exit_code):
    import kernel
    from vortexglass.service import manager
    calls = []
    monkeypatch.setattr("bootmode.wants_fastboot", lambda _root: False)
    monkeypatch.setattr("oobe.maybe_run_oobe", lambda _root: False)
    monkeypatch.setattr(kernel, "screen_clear", lambda: None)
    monkeypatch.setattr("ota.ota_init", lambda: None)
    monkeypatch.setattr(manager, "start", lambda: calls.append("start"))
    monkeypatch.setattr(manager, "stop", lambda: calls.append("stop"))

    def leave():
        calls.append("shell")
        raise SystemExit(exit_code)

    monkeypatch.setattr(kernel, "_command_loop", leave)
    with pytest.raises(SystemExit) as result:
        kernel.loop()
    assert result.value.code == exit_code
    assert calls == ["start", "shell", "stop"]


def test_missing_graphics_backend_does_not_prevent_shell_boot(monkeypatch):
    import kernel
    from vortexglass.service import manager
    calls = []
    monkeypatch.setattr("bootmode.wants_fastboot", lambda _root: False)
    monkeypatch.setattr("oobe.maybe_run_oobe", lambda _root: False)
    monkeypatch.setattr(kernel, "screen_clear", lambda: None)
    monkeypatch.setattr("ota.ota_init", lambda: None)
    monkeypatch.setattr(manager, "stop", lambda: calls.append("stop"))
    monkeypatch.setattr(kernel, "_command_loop", lambda: calls.append("shell"))

    def fail():
        raise RuntimeError("Qt unavailable")

    monkeypatch.setattr(manager, "start", fail)
    kernel.loop()
    assert calls == ["shell", "stop"]
