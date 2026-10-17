'''
 *
 *      test_guisettings.py
 *      Settings view: choice chips, the name field, and the read-only trust panel.
 *
 *      2026/10/16 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */

'''

import pytest

from vortexglass import model, style
from apps import guisettings

CONFIG = {"locked": False, "rootstate": False, "lang": "zh_CN",
          "timezone": "Asia/Shanghai", "display_name": "jitianyu",
          "ota_channel": "stable"}

SNAPSHOT = {"ok": True, "identity": {"version": "3.2.0", "slot": "slot_a",
                                     "slot_version": "3.0.0", "ota": "启用"}}


# Answer host calls from a table and record what the view asked for. get_ok and
# set_ok are separate so a test can fail one path without failing the other.
def _stub(monkeypatch, config=None, get_ok=True, set_ok=True, reason="拒绝"):
    calls = []

    def fake(op, *args, **kwargs):
        calls.append((op, args))
        if op == "get_bootcfg":
            return (True, dict(config or CONFIG)) if get_ok else (False, reason)
        if op == "set_bootcfg":
            return (True, True) if set_ok else (False, reason)
        if op == "sm_snapshot":
            return (True, SNAPSHOT)
        return (True, None)

    monkeypatch.setattr(guisettings, "call", fake)
    return calls


# Every string the scene puts on screen, including the choice chips, whose label
# rides on the button item rather than a separate text item.
def _texts(items):
    return [i["text"] for i in items if i.get("type") in ("text", "button")]


# A scene the view builds is one the compositor would accept.
def test_scene_matches_the_compositor_protocol(monkeypatch):
    _stub(monkeypatch)
    model.validate_scene(guisettings.Settings().scene(760, 546))


# The current values are on screen and the active chip is the accented one.
def test_scene_shows_current_values(monkeypatch):
    _stub(monkeypatch)
    items = guisettings.Settings().scene(760, 546)
    joined = "\n".join(_texts(items))
    assert "简体中文" in joined and "稳定版" in joined
    assert "上海" in joined and "jitianyu" in joined
    # 标签是简称，真正写进配置的是完整 zone id，所以断言 id 而不是标签。
    assert "timezone:Asia/Shanghai" in {i.get("id") for i in items}
    active = {i["id"] for i in items
              if i.get("type") == "button" and i["color"] == style.CONTROL_ACTIVE}
    assert active == {"lang:zh_CN", "timezone:Asia/Shanghai",
                      "ota_channel:stable"}


# Clicking a chip sends exactly that key and value to the host.
def test_choice_click_sends_the_pair(monkeypatch):
    calls = _stub(monkeypatch)
    view = guisettings.Settings()
    view.scene(760, 546)
    assert view.handle({"type": "click", "target": "timezone:UTC"}) is True
    assert calls[-1] == ("set_bootcfg", ("timezone", "UTC"))


# A refusal from the host is reported on screen instead of vanishing.
def test_refused_change_is_reported(monkeypatch):
    _stub(monkeypatch, set_ok=False, reason="未知时区: Mars/Olympus")
    view = guisettings.Settings()
    view.scene(760, 546)
    view.handle({"type": "click", "target": "timezone:Mars/Olympus"})
    assert "失败" in view.message and "Mars/Olympus" in view.message
    assert any("Mars/Olympus" in t for t in _texts(view.scene(760, 546)))


# A display name is one line: newlines are folded and the field is rewritten to
# what was actually submitted, so the screen cannot drift from the config.
def test_display_name_is_folded_to_one_line(monkeypatch):
    calls = _stub(monkeypatch)
    view = guisettings.Settings()
    view.scene(760, 546)
    view.editor = guisettings.TextEditor("  two\nlines  ")
    assert view.handle({"type": "click", "target": "apply_name"}) is True
    assert calls[-1] == ("set_bootcfg", ("display_name", "two lines"))
    assert view.editor.content == "two lines"


# The trust state is read-only: it appears on screen with its own tone, and the
# view offers no way to click it.
def test_trust_state_is_shown_but_not_editable(monkeypatch):
    _stub(monkeypatch, config={**CONFIG, "locked": True, "rootstate": True})
    items = guisettings.Settings().scene(760, 546)
    texts = _texts(items)
    assert "LOCKED" in texts and "是" in texts
    locked = next(i for i in items if i.get("text") == "LOCKED")
    assert locked["color"] == style.WARN
    ids = {i["id"] for i in items if i.get("type") == "button"}
    assert not any("locked" in i or "rootstate" in i for i in ids)


# Without a host channel the view paints the reason rather than raising.
def test_scene_degrades_without_a_host_channel(monkeypatch):
    _stub(monkeypatch, get_ok=False, reason="不在宿主通道上")
    view = guisettings.Settings()
    items = view.scene(760, 546)
    model.validate_scene(items)
    assert "不在宿主通道上" in "\n".join(_texts(items))


# A refresh must not clobber a half-typed name, but it should follow a change
# made elsewhere once the field is back in sync with the loaded value.
def test_refresh_does_not_clobber_a_pending_edit(monkeypatch):
    _stub(monkeypatch)
    view = guisettings.Settings()
    view.scene(760, 546)
    assert view.editor.content == "jitianyu"

    view.editor = guisettings.TextEditor("typing")
    view.scene(760, 546)
    assert view.editor.content == "typing"

    view.editor = guisettings.TextEditor("jitianyu")
    _stub(monkeypatch, config={**CONFIG, "display_name": "renamed"})
    view.scene(760, 546)
    assert view.editor.content == "renamed"
