'''
 *
 *      test_guiservices.py
 *      The service-manager GUI: protocol-shaped scenes and host-channel handling.
 *
 *      2026/10/16 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */

'''

import pytest

from vortexglass import model
from apps import guiservices


# Two units with edges, shaped exactly like ServiceManager.status() returns.
UNITS = [
    {"name": "boot-commit.service", "description": "Verified boot commit",
     "type": "oneshot", "state": "active", "result": "success", "error": "",
     "elapsed": 0.001, "requires": ["default.target"], "wants": [],
     "after": ["default.target"], "before": []},
    {"name": "shell.service", "description": "Interactive shell",
     "type": "simple", "state": "failed", "result": "exit-code",
     "error": "exited", "elapsed": 0.5, "requires": [], "wants": [],
     "after": [], "before": []},
]


# Answer host calls from a table so the view can be driven without a compositor.
def _stub(monkeypatch, replies):
    calls = []

    def fake(op, *args, **kwargs):
        calls.append((op, args))
        return replies.get(op, (True, []))

    monkeypatch.setattr(guiservices, "call", fake)
    return calls


# A scene the app builds has to be one the compositor would actually accept.
def test_scene_matches_the_compositor_protocol(monkeypatch):
    _stub(monkeypatch, {"sm_status": (True, UNITS),
                        "sm_journal": (True, ["Oct 16 21:00:00 PySpOS init[1]: shell.service: Started"])})
    items = guiservices.Services().scene(680, 560)
    model.validate_scene(items)


# Selecting a row has to switch the detail panel to that unit's edges, not
# leave the first unit's edges on screen.
def test_selecting_a_unit_shows_its_own_edges(monkeypatch):
    _stub(monkeypatch, {"sm_status": (True, UNITS)})
    view = guiservices.Services()
    view.scene(680, 560)
    assert view.selected == "boot-commit.service"

    assert view.handle({"type": "click", "target": "unit:shell.service"}) is True
    assert view.selected == "shell.service"
    text = " ".join(item["text"] for item in view.scene(680, 560)
                    if item["type"] == "text")
    assert "shell.service" in text


# A refused lifecycle action has to surface its reason instead of vanishing.
def test_action_reports_its_outcome(monkeypatch):
    _stub(monkeypatch, {"sm_status": (True, UNITS),
                        "sm_start": (False, "Unit not found: shell.service")})
    view = guiservices.Services()
    view.scene(680, 560)
    view.handle({"type": "click", "target": "unit:shell.service"})
    view.handle({"type": "click", "target": "act:start"})
    assert "失败" in view.message and "Unit not found" in view.message
    text = " ".join(item["text"] for item in view.scene(680, 560)
                    if item["type"] == "text")
    assert "Unit not found" in text


# Without a host channel the view must still paint a reason rather than raise
# out of the paint loop.
def test_scene_degrades_without_a_host_channel(monkeypatch):
    _stub(monkeypatch, {"sm_status": (False, "不在宿主通道上（请从桌面或 shell 启动）")})
    items = guiservices.Services().scene(680, 560)
    model.validate_scene(items)
    text = " ".join(item["text"] for item in items if item["type"] == "text")
    assert "不在宿主通道上" in text


# Button ids have to be unique within one scene, and a rejected scene is a
# protocol error rather than a silent no-op.
def test_button_ids_are_unique(monkeypatch):
    _stub(monkeypatch, {"sm_status": (True, UNITS)})
    items = guiservices.Services().scene(680, 560)
    ids = [item["id"] for item in items if item["type"] == "button"]
    assert len(ids) == len(set(ids))

    with pytest.raises(model.ProtocolError):
        model.validate_scene([{"type": "button", "x": 0, "y": 0, "width": 10,
                               "height": 10, "text": "", "id": "dup"},
                              {"type": "button", "x": 0, "y": 0, "width": 10,
                               "height": 10, "text": "", "id": "dup"}])
