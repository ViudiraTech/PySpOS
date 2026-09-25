"""Recovery 菜单与 tui.ask_menu 测试。

覆盖三层：
  1. 行式后端：编号选择、空输入取默认、无效输入重试；
  2. curses 菜单导航逻辑（伪造 stdscr，不依赖真实终端）；
  3. recovery 主菜单流程：No-command 进菜单 → 动作 → 重启/取消。
"""
import sys

import pytest

import tui


def _feed(monkeypatch, *answers):
    seq = iter(answers)
    monkeypatch.setattr("builtins.input", lambda _p="": next(seq))


def test_line_menu_number_and_default(monkeypatch, capsys):
    monkeypatch.setenv("PYSPOS_TUI", "line")
    _feed(monkeypatch, "2")
    assert tui.ask_menu("H", ["a", "b", "c"]) == 2
    out = capsys.readouterr().out
    assert "H" in out and "Reboot" not in out

    _feed(monkeypatch, "")  # 空输入 = 默认高亮项
    assert tui.ask_menu("H", ["a", "b", "c"], 1) == 1


def test_line_menu_invalid_retries(monkeypatch, capsys):
    monkeypatch.setenv("PYSPOS_TUI", "line")
    _feed(monkeypatch, "9", "x", "0")
    assert tui.ask_menu("H", ["a", "b"]) == 0
    assert "无效" in capsys.readouterr().out or "invalid" in capsys.readouterr().out.lower()


class _FakeScreen:
    """只实现 _CursesUI.menu 触达的方法；getch 按脚本按键。"""

    def __init__(self, keys, h=24, w=80):
        self._keys = list(keys)
        self._h, self._w = h, w
        self.drawn = []

    def keypad(self, _flag):
        pass

    def getmaxyx(self):
        return self._h, self._w

    def erase(self):
        pass

    def refresh(self):
        pass

    def addstr(self, y, x, text, _attr=0):
        self.drawn.append((y, x, text))

    def getch(self):
        return self._keys.pop(0)


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


def test_curses_menu_arrows_and_enter():
    import curses as _c
    ui = _make_menu_ui([_c.KEY_DOWN, _c.KEY_DOWN, _c.KEY_UP, 10])
    assert ui.menu("H", ["a", "b", "c", "d"]) == 1


def test_curses_menu_wrap_and_esc():
    import curses as _c
    ui = _make_menu_ui([_c.KEY_UP, 10])  # 首项上移 → 循环到末项
    assert ui.menu("H", ["a", "b", "c"]) == 2

    ui = _make_menu_ui([27])
    assert ui.menu("H", ["a", "b"]) is tui.BACK


# ---------------------------------------------------------------------------
# recovery 主流程（桩掉清屏与权限，真实跑菜单循环）
# ---------------------------------------------------------------------------

def _stub_recovery_env(monkeypatch):
    import recovery
    monkeypatch.setattr(recovery.kernel, "screen_clear", lambda: None)
    monkeypatch.setattr(recovery, "_require_root", lambda _op: True)
    monkeypatch.setattr(recovery, "_pause", lambda _m="": None)
    return recovery


def test_recovery_menu_to_reboot(monkeypatch, capsys):
    recovery = _stub_recovery_env(monkeypatch)
    # No-command 回车 → 输错一次 → 进命令 shell → exit 回菜单 → 重启
    _feed(monkeypatch, "", "9", "6", "exit", "0")
    assert recovery.recovery_main("test") == "reboot"
    out = capsys.readouterr().out
    assert "No command." in out
    assert "Reboot system now" in out
    assert "Wipe data/factory reset" in out


def test_recovery_wipe_defaults_to_no(monkeypatch, capsys):
    recovery = _stub_recovery_env(monkeypatch)
    # No-command 回车 → 选出厂重置 → 空输入（默认 No）→ 重启
    _feed(monkeypatch, "", "5", "", "0")
    assert recovery.recovery_main("test") == "reboot"
    assert "操作已取消" in capsys.readouterr().out


def test_recovery_shell_keeps_ota_commands(monkeypatch, capsys):
    """文档里的 recovery > ota_rollback 路径必须继续有效。"""
    import recovery  # noqa: F401  (import 即断言无启动器保护问题)
    import inspect
    src = inspect.getsource(recovery.recovery_shell)
    for cmd in ("ota_check", "ota_update", "ota_status",
                "ota_rollback", "ota_clean", "erase", "exit"):
        assert f'prompt == "{cmd}"' in src
