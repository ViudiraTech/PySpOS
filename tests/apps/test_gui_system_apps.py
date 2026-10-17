'''
 *
 *      test_gui_system_apps.py
 *      The package, update and trust windows: scenes, actions and refusals.
 *
 *      2026/10/16 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */

'''

import pytest

from vortexglass import model
from apps import guiota, guipackages, guitrust

PACKAGES = [
    {"id": "wordcount", "version": "1.0.0", "description": "统计行数与词数",
     "entrypoints": [{"name": "wc", "kind": "app"}]},
    {"id": "greeter", "version": "0.3.1", "description": "打个招呼",
     "entrypoints": [{"name": "greet", "kind": "app"}]},
]

OTA = {"ota_enabled": True, "ota_disable_reason": None, "boot_locked": False,
       "rollback_index": 1, "current_slot": "slot_a", "current_version": "3.2.0",
       "current_slot_verified": True, "other_slot": "slot_b",
       "other_version": "未知版本", "other_slot_verified": False,
       "has_update": False, "update_version": None}

BOOTCFG = {"locked": False, "rootstate": False, "lang": "zh_CN",
           "timezone": "Asia/Shanghai", "display_name": "jitianyu",
           "ota_channel": "stable"}


# Answer host calls from a table; fail_one names the op that should be refused.
def _stub(monkeypatch, module, replies, fail=None, reason="拒绝"):
    calls = []

    def fake(op, *args, **kwargs):
        calls.append((op, args))
        if op == fail:
            return (False, reason)
        return replies.get(op, (True, None))

    monkeypatch.setattr(module, "call", fake)
    return calls


def _texts(items):
    return [i["text"] for i in items if i.get("type") in ("text", "button")]


# ---------------------------------------------------------------- 包管理器

# 列表、详情和卸载按钮都在，且场景合协议。
def test_package_window_renders_and_follows_the_protocol(monkeypatch):
    _stub(monkeypatch, guipackages, {"pkg_list": (True, PACKAGES),
                                     "pkg_info": (True, PACKAGES[0])})
    view = guipackages.Packages()
    items = view.scene(760, 520)
    model.validate_scene(items)
    texts = _texts(items)
    assert "wordcount" in texts and "greeter" in texts
    assert any(t.startswith("详情 · ") for t in texts)
    assert "卸载" in texts
    assert view.selected == "wordcount"


# 选中另一个包会切走详情。
def test_package_selection_switches_the_detail(monkeypatch):
    _stub(monkeypatch, guipackages, {"pkg_list": (True, PACKAGES),
                                     "pkg_info": (True, PACKAGES[1])})
    view = guipackages.Packages()
    view.scene(760, 520)
    assert view.handle({"type": "click", "target": "pkg:greeter"}) is True
    assert view.selected == "greeter"
    assert "详情 · greeter" in _texts(view.scene(760, 520))


# 空列表要给下一步怎么做，而不是一片空白。
def test_empty_package_list_explains_what_to_do(monkeypatch):
    _stub(monkeypatch, guipackages, {"pkg_list": (True, [])})
    items = guipackages.Packages().scene(760, 520)
    model.validate_scene(items)
    joined = "\n".join(_texts(items))
    assert "尚未安装任何包" in joined and "pkg install" in joined


# 卸载失败的原因要留在界面上。
def test_package_removal_reports_a_refusal(monkeypatch):
    _stub(monkeypatch, guipackages,
          {"pkg_list": (True, PACKAGES), "pkg_info": (True, PACKAGES[0])},
          fail="pkg_remove", reason="包删除需要 ROOT")
    view = guipackages.Packages()
    view.scene(760, 520)
    assert view.handle({"type": "click", "target": "remove"}) is True
    assert "ROOT" in view.message
    assert any("ROOT" in t for t in _texts(view.scene(760, 520)))


# ---------------------------------------------------------------- 系统更新

def test_update_window_renders_both_slots(monkeypatch):
    _stub(monkeypatch, guiota, {"ota_status": (True, dict(OTA))})
    items = guiota.Update().scene(760, 500)
    model.validate_scene(items)
    texts = _texts(items)
    assert "slot_a（当前）" in texts and "slot_b（备用）" in texts
    assert "已验签" in texts and "未验签" in texts
    assert "3.2.0" in texts
    assert "防回滚索引" in texts


# 回滚被拒时说明原因，成功后说的是「重启后生效」而不是「已完成」——它换的是
# 启动槽位，不是当前这次运行。
def test_rollback_reports_refusal_and_effect(monkeypatch):
    _stub(monkeypatch, guiota, {"ota_status": (True, dict(OTA))},
          fail="ota_rollback", reason="OTA 回滚需要 ROOT")
    view = guiota.Update()
    view.scene(760, 500)
    assert view.handle({"type": "click", "target": "rollback"}) is True
    assert "ROOT" in view.message

    _stub(monkeypatch, guiota, {"ota_status": (True, dict(OTA)),
                                "ota_rollback": (True, True)})
    view = guiota.Update()
    view.scene(760, 500)
    view.handle({"type": "click", "target": "rollback"})
    assert "重启后生效" in view.message


# ---------------------------------------------------------------- 启动信任

def test_trust_window_renders_the_chain(monkeypatch):
    _stub(monkeypatch, guitrust, {"get_bootcfg": (True, dict(BOOTCFG)),
                                  "get_rootstate": (True, False),
                                  "ota_status": (True, dict(OTA))})
    items = guitrust.Trust().scene(720, 470)
    model.validate_scene(items)
    texts = _texts(items)
    assert "UNLOCKED" in texts and "LOCKED" not in texts
    assert "启动信任" in texts and "运行权限" in texts
    assert "已验签" in texts and "未验签" in texts
    assert "zh_CN / Asia/Shanghai" in texts


# 面板是只读的：不提供任何可点的东西，操作留在 shell 里。
def test_trust_window_offers_no_controls(monkeypatch):
    _stub(monkeypatch, guitrust, {"get_bootcfg": (True, dict(BOOTCFG)),
                                  "get_rootstate": (True, False),
                                  "ota_status": (True, dict(OTA))})
    items = guitrust.Trust().scene(720, 470)
    assert not [i for i in items if i.get("type") == "button"]


# ROOT 一态跟着宿主走。
def test_trust_window_follows_root_state(monkeypatch):
    _stub(monkeypatch, guitrust, {"get_bootcfg": (True, dict(BOOTCFG)),
                                  "get_rootstate": (True, True),
                                  "ota_status": (True, dict(OTA))})
    texts = _texts(guitrust.Trust().scene(720, 470))
    assert "是" in texts


# ---------------------------------------------------------------- 共同的降级

# 没有宿主通道时三个窗口都画原因，而不是抛异常。
@pytest.mark.parametrize("module,factory,first_op", [
    (guipackages, guipackages.Packages, "pkg_list"),
    (guiota, guiota.Update, "ota_status"),
    (guitrust, guitrust.Trust, "get_bootcfg"),
])
def test_windows_degrade_without_a_host_channel(module, factory, first_op, monkeypatch):
    _stub(monkeypatch, module, {}, fail=first_op, reason="不在宿主通道上")
    view = factory()
    items = view.scene(760, 520)
    model.validate_scene(items)
    assert "不在宿主通道上" in "\n".join(_texts(items))
