'''
 *
 *      test_fastboot_gui_layout.py
 *      Build the fastboot GUI in both looks against a real Tk root.
 *
 *      Skipped when there is no display, because the point of these checks is
 *      exactly the widget construction that only fails once Tk is involved,
 *      such as handing a ttk-only option to a plain tk widget.
 *
 *      2026/9/26 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import os
import tkinter as tk

import pytest

import fastboot_gui as gui

pytestmark = pytest.mark.skipif(not os.environ.get("DISPLAY"),
                                reason="需要显示环境才能创建 Tk 根窗口")


@pytest.fixture
def root():
    try:
        window = tk.Tk()
    except Exception as exc:  # pragma: no cover - depends on the environment
        pytest.skip(f"无法创建 Tk 窗口: {exc}")
    window.withdraw()
    yield window
    try:
        window.destroy()
    except tk.TclError:
        pass


@pytest.mark.parametrize("style", gui.STYLE_CHOICES)
def test_gui_builds_in_both_styles(root, style, tmp_path):
    app = gui.FastbootGui(root, gui.DEFAULT_HOST, gui.DEFAULT_PORT, style,
                          settings_file=str(tmp_path / "settings.json"))
    # Every variable row must have a value label to update later.
    assert set(app.value_labels) == {name for name, _ in gui.VARIABLE_ROWS}
    assert app.style_name == style


def test_switching_style_rebuilds_cleanly(root, tmp_path):
    app = gui.FastbootGui(root, gui.DEFAULT_HOST, gui.DEFAULT_PORT,
                          gui.STYLE_CLASSIC,
                          settings_file=str(tmp_path / "settings.json"))
    app._log("切换前", "INFO")
    app.style_name = gui.STYLE_MODERN
    app._rebuild()
    assert app.style_name == gui.STYLE_MODERN
    # The log survives the rebuild instead of vanishing with the widgets.
    assert any("切换前" in text for _level, text in app.log_lines)
    app.style_name = gui.STYLE_CLASSIC
    app._rebuild()
    assert app.style_name == gui.STYLE_CLASSIC


def test_buttons_start_disabled_until_connected(root, tmp_path):
    app = gui.FastbootGui(root, gui.DEFAULT_HOST, gui.DEFAULT_PORT,
                          gui.STYLE_CLASSIC,
                          settings_file=str(tmp_path / "settings.json"))

    def disabled(widget):
        return str(widget.cget("state")) == "disabled"

    # Nothing that touches the device may be live before connecting.
    assert app.connected is False
    assert disabled(app.connect_btn) is False
    assert disabled(app.disconnect_btn) is True
    assert all(disabled(w) for w in app.device_buttons)
    app.connected = True
    app._sync_state()
    # While connected the connect button is disabled, so it cannot reconnect.
    assert disabled(app.connect_btn) is True
    assert disabled(app.disconnect_btn) is False
    assert not any(disabled(w) for w in app.device_buttons)
    app.connected = False
    app._sync_state()
    assert disabled(app.connect_btn) is False


def test_modern_buttons_follow_the_same_state_rules(root, tmp_path):
    app = gui.FastbootGui(root, gui.DEFAULT_HOST, gui.DEFAULT_PORT,
                          gui.STYLE_MODERN,
                          settings_file=str(tmp_path / "settings.json"))
    app.connected = True
    app._sync_state()
    assert str(app.connect_btn.cget("state")) == "disabled"
    assert str(app.disconnect_btn.cget("state")) == "normal"


def test_log_levels_are_tagged(root, tmp_path):
    app = gui.FastbootGui(root, gui.DEFAULT_HOST, gui.DEFAULT_PORT,
                          gui.STYLE_MODERN,
                          settings_file=str(tmp_path / "settings.json"))
    for level in gui.LEVELS:
        app._log(f"{level} 测试", level)
    content = app.log_text.get("1.0", "end")
    for level in gui.LEVELS:
        assert level in content
    app._on_clear_log()
    assert app.log_text.get("1.0", "end").strip() == ""
    assert app.log_lines == []


def test_settings_round_trip(root, tmp_path):
    path = str(tmp_path / "nested" / "settings.json")
    assert gui.save_settings({"style": gui.STYLE_MODERN, "host": "10.0.0.5",
                              "port": 6000}, path) is True
    saved = gui.load_settings(path)
    assert saved["style"] == gui.STYLE_MODERN
    assert saved["host"] == "10.0.0.5"
    assert saved["port"] == 6000


def test_broken_settings_fall_back(root, tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not json", encoding="utf-8")
    saved = gui.load_settings(str(path))
    assert saved == {"style": gui.STYLE_CLASSIC, "host": gui.DEFAULT_HOST,
                     "port": gui.DEFAULT_PORT}


def test_hostile_settings_values_are_ignored(root, tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"style": "evil", "host": "", "port": 99999}',
                    encoding="utf-8")
    saved = gui.load_settings(str(path))
    assert saved["style"] == gui.STYLE_CLASSIC
    assert saved["host"] == gui.DEFAULT_HOST
    assert saved["port"] == gui.DEFAULT_PORT


def test_tk_opts_translates_padding():
    assert gui.Skin._tk_opts({}) == {}
    assert gui.Skin._tk_opts({"padding": 12}) == {"padx": 12, "pady": 12}
    assert gui.Skin._tk_opts({"padding": (4, 8)}) == {"padx": 4, "pady": 8}
    assert gui.Skin._tk_opts({"padding": (1, 2, 3, 4)}) == {"padx": 1, "pady": 2}


def test_every_theme_role_used_by_the_gui_exists():
    needed = ("bg", "panel", "sunken", "border", "fg", "muted", "accent",
              "accent_fg", "ok", "warn", "err", "active")
    for role in needed:
        assert gui.THEME_MODERN.color(role), role
    # The classic look must not force colours on the platform widgets.
    assert gui.THEME_CLASSIC.color("bg") is None
    assert gui.THEME_CLASSIC.native is True
