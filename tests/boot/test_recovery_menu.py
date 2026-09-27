'''
 *
 *      test_recovery_menu.py
 *      Recovery menus and tui.ask_menu across the line and curses backends.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import sys

import pytest

import tui


# Replace input() with a scripted answer sequence.
def _feed(monkeypatch, *answers):
    seq = iter(answers)
    monkeypatch.setattr("builtins.input", lambda _p="": next(seq))


# The line backend takes a 1-based number, and an empty line means the default-highlighted item.
def test_line_menu_number_and_default(monkeypatch, capsys):
    monkeypatch.setenv("PYSPOS_TUI", "line")
    _feed(monkeypatch, "2")
    assert tui.ask_menu("H", ["a", "b", "c"]) == 2
    out = capsys.readouterr().out
    assert "H" in out and "Reboot" not in out

    _feed(monkeypatch, "")  # Empty input means the highlighted default
    assert tui.ask_menu("H", ["a", "b", "c"], 1) == 1


# Out-of-range or non-numeric answers are rejected with a message until a valid one arrives.
def test_line_menu_invalid_retries(monkeypatch, capsys):
    monkeypatch.setenv("PYSPOS_TUI", "line")
    _feed(monkeypatch, "9", "x", "0")
    assert tui.ask_menu("H", ["a", "b"]) == 0
    assert "无效" in capsys.readouterr().out or "invalid" in capsys.readouterr().out.lower()


# Implements only the methods _CursesUI.menu touches; getch replays a scripted key list.
class _FakeScreen:

# Hold the key script, a fixed geometry and the record of everything drawn.
    def __init__(self, keys, h=24, w=80):
        self._keys = list(keys)
        self._h, self._w = h, w
        self.drawn = []

# No-op: a fake screen has no keypad mode to set.
    def keypad(self, _flag):
        pass

# Report the fixed geometry instead of a real terminal's.
    def getmaxyx(self):
        return self._h, self._w

# No-op: nothing is really painted on a fake screen.
    def erase(self):
        pass

# No-op: there is no terminal to flush to.
    def refresh(self):
        pass

# Record the write instead of drawing it, so the test can assert on the layout.
    def addstr(self, y, x, text, _attr=0):
        self.drawn.append((y, x, text))

# Pop the next scripted key, which makes navigation replayable.
    def getch(self):
        return self._keys.pop(0)


# Build a _CursesUI around the fake screen, skipping when curses lacks the key constants.
def _make_menu_ui(keys):
    pytest.importorskip("curses")
    import curses as _c
    if not all(hasattr(_c, n) for n in ("KEY_UP", "KEY_DOWN", "KEY_HOME", "KEY_END", "KEY_ENTER")):
        pytest.skip("curses 缺少方向键常量")
    ui = tui._CursesUI.__new__(tui._CursesUI)
    ui.s = _FakeScreen(keys)
    ui.h, ui.w = 24, 80
    ui.C_TEXT = ui.C_FOOT = ui.C_SEL = 0
    return ui


# Arrow keys move the highlight down, down and back up, and Enter accepts the highlighted item.
def test_curses_menu_arrows_and_enter():
    import curses as _c
    ui = _make_menu_ui([_c.KEY_DOWN, _c.KEY_DOWN, _c.KEY_UP, 10])
    assert ui.menu("H", ["a", "b", "c", "d"]) == 1


# Moving up from the first item wraps to the last, and Esc means BACK.
def test_curses_menu_wrap_and_esc():
    import curses as _c
    ui = _make_menu_ui([_c.KEY_UP, 10])  # Moving up from the first item wraps to the last
    assert ui.menu("H", ["a", "b", "c"]) == 2

    ui = _make_menu_ui([27])
    assert ui.menu("H", ["a", "b"]) is tui.BACK


# ---------------------------------------------------------------------------
# The recovery main flow, with screen clearing and the permission check stubbed out and the real menu loop running
# ---------------------------------------------------------------------------

# Stub screen clearing, the root check and the pause prompt so the menu loop can run headless.
def _stub_recovery_env(monkeypatch):
    import recovery
    monkeypatch.setattr(recovery.kernel, "screen_clear", lambda: None)
    monkeypatch.setattr(recovery, "_require_root", lambda _op: True)
    monkeypatch.setattr(recovery, "_pause", lambda _m="": None)
    return recovery


# An empty No-command line enters the menu, a bad number re-prompts, and choosing reboot returns the reboot action.
def test_recovery_menu_to_reboot(monkeypatch, capsys):
    recovery = _stub_recovery_env(monkeypatch)
    # No-command Enter -> one bad number -> enter the command shell -> exit back to the menu -> reboot
    _feed(monkeypatch, "", "9", "7", "exit", "0")
    assert recovery.recovery_main("test") == "reboot"
    out = capsys.readouterr().out
    assert "No command." in out
    assert "Reboot system now" in out
    assert "Install version from cloud" in out
    assert "Wipe data/factory reset" in out


# The factory-reset confirmation defaults to No, so pressing Enter cancels it.
def test_recovery_wipe_defaults_to_no(monkeypatch, capsys):
    recovery = _stub_recovery_env(monkeypatch)
    # No-command Enter -> pick factory reset -> empty input (default No) -> reboot
    _feed(monkeypatch, "", "6", "", "0")
    assert recovery.recovery_main("test") == "reboot"
    assert "操作已取消" in capsys.readouterr().out


# Picking a cloud version installs into the non-current slot after one confirmation and then switches the boot slot.
def test_recovery_install_version_to_slot(monkeypatch, capsys):
    import ota
    recovery = _stub_recovery_env(monkeypatch)
    entries = [{
        "version": "3.3.0", "date": "2026-10-01", "type": "beta",
        "download_url": "https://example.invalid/ota/PySpOS-3.3.0.zip",
        "sha256": "abc", "file_size": 10, "notes": "",
    }]
    monkeypatch.setattr(ota, "list_cloud_versions", lambda: entries)
    monkeypatch.setattr(ota, "get_current_slot", lambda: "slot_a")
    monkeypatch.setattr(ota, "get_current_version", lambda: "3.2.0")
    calls = {}

# Record the install call the recovery flow makes instead of downloading anything.
    def fake_install(entry, slot, allow_downgrade=False):
        calls["entry"] = entry
        calls["slot"] = slot
        calls["downgrade"] = allow_downgrade
        return True

    monkeypatch.setattr(ota, "download_and_install_version", fake_install)
    switched = []
    monkeypatch.setattr(ota, "set_current_slot", switched.append)
    monkeypatch.setattr(recovery.printk, "confirm", lambda *a, **k: True)
    # No-command Enter -> pick install version (2) -> pick the first version -> pick a slot (the default is not the current one) -> reboot
    _feed(monkeypatch, "", "2", "", "", "0")
    assert recovery.recovery_main("test") == "reboot"
    assert calls == {"entry": entries[0], "slot": "slot_b", "downgrade": False}
    assert switched == ["slot_b"]
    assert "已安装到 slot_b" in capsys.readouterr().out


# A same-or-older version needs a second explicit confirmation, and refusing it must cancel without installing.
def test_recovery_install_version_downgrade_needs_confirm(monkeypatch, capsys):
    import ota
    recovery = _stub_recovery_env(monkeypatch)
    entries = [{
        "version": "3.1.0", "date": "2026-03-15", "type": "release",
        "download_url": "https://example.invalid/ota/old.zip",
        "sha256": None, "file_size": 0, "notes": "",
    }]
    monkeypatch.setattr(ota, "list_cloud_versions", lambda: entries)
    monkeypatch.setattr(ota, "get_current_slot", lambda: "slot_a")
    monkeypatch.setattr(ota, "get_current_version", lambda: "3.2.0")
    called = []
    monkeypatch.setattr(
        ota, "download_and_install_version",
        lambda *a, **k: called.append((a, k)) or True)
    monkeypatch.setattr(recovery.printk, "confirm", lambda *a, **k: False)
    _feed(monkeypatch, "", "2", "", "", "0")
    assert recovery.recovery_main("test") == "reboot"
    assert called == []
    out = capsys.readouterr().out
    assert "不高于当前版本" in out and "操作已取消" in out


# Regression lock: the documented recovery > ota_rollback path must still be dispatched.
def test_recovery_shell_keeps_ota_commands(monkeypatch, capsys):
    import recovery  # noqa: F401  (the import itself asserts there is no launcher guard problem)
    import inspect
    src = inspect.getsource(recovery.recovery_shell)
    for cmd in ("ota_check", "ota_update", "ota_status",
                "ota_rollback", "ota_clean", "erase", "exit"):
        assert f'prompt == "{cmd}"' in src
