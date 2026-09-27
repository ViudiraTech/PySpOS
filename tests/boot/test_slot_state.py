'''
 *
 *      test_slot_state.py
 *      The active slot has exactly one source of truth: the verified boot state.
 *
 *      This file exists because the active slot used to live in two places at
 *      once. set_current_slot wrote a legacy current_slot file while
 *      get_current_slot preferred boot_state.active_slot, so switching the boot
 *      slot was silently dropped and the device kept booting the old image.
 *
 *      2026/9/26 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import os
import sys

import pytest

import ota
import secure_boot


# Point the modules at a scratch root so nothing real is touched.
@pytest.fixture
def root(tmp_path, monkeypatch):
    # ota keeps its root in a module global; secure_boot takes it per call.
    target = str(tmp_path)
    monkeypatch.setattr(ota, "root_dir", target)
    return target


def write_legacy_slot(root, slot):
    with open(os.path.join(root, "current_slot"), "w", encoding="utf-8") as stream:
        stream.write(slot)


def read_boot_state(root):
    return secure_boot.load_state(root)


def test_set_active_slot_writes_the_boot_state(root):
    secure_boot.set_active_slot(root, ota.SLOT_B)
    assert read_boot_state(root)["active_slot"] == ota.SLOT_B


def test_set_active_slot_clears_a_pending_switch(root):
    secure_boot.set_active_slot(root, ota.SLOT_A)
    secure_boot.stage_slot(root, ota.SLOT_B)
    assert read_boot_state(root)["pending_slot"] == ota.SLOT_B
    secure_boot.set_active_slot(root, ota.SLOT_B)
    state = read_boot_state(root)
    assert state["active_slot"] == ota.SLOT_B
    assert state["pending_slot"] is None
    assert state["attempts_remaining"] == 0


def test_set_active_slot_rejects_an_unknown_slot(root):
    with pytest.raises(secure_boot.BootVerificationError):
        secure_boot.set_active_slot(root, "slot_c")


def test_get_current_slot_reads_the_boot_state(root):
    secure_boot.set_active_slot(root, ota.SLOT_B)
    assert ota.get_current_slot() == ota.SLOT_B


def test_set_current_slot_is_visible_to_get_current_slot(root):
    # The regression this guards: the switch used to be written somewhere
    # get_current_slot never looked, so it appeared to do nothing.
    ota.set_current_slot(ota.SLOT_B)
    assert ota.get_current_slot() == ota.SLOT_B
    assert read_boot_state(root)["active_slot"] == ota.SLOT_B


def test_legacy_file_is_migrated_once(root):
    # A device that only has the legacy marker still boots the right slot, and
    # the migration promotes it into the boot state.
    write_legacy_slot(root, ota.SLOT_B)
    assert ota.get_current_slot() == ota.SLOT_B
    assert read_boot_state(root)["active_slot"] == ota.SLOT_B


def test_boot_state_wins_over_a_stale_legacy_file(root):
    # Once the boot state knows the active slot, the legacy file is ignored.
    secure_boot.set_active_slot(root, ota.SLOT_A)
    write_legacy_slot(root, ota.SLOT_B)
    assert ota.get_current_slot() == ota.SLOT_A


def test_missing_state_defaults_to_slot_a(root):
    assert ota.get_current_slot() == ota.SLOT_A
    assert read_boot_state(root)["active_slot"] == ota.SLOT_A


def test_get_other_slot_follows_the_boot_state(root):
    secure_boot.set_active_slot(root, ota.SLOT_B)
    assert ota.get_other_slot() == ota.SLOT_A


def test_install_marks_the_slot_pending_not_active(root, monkeypatch):
    # Installing must not switch the active slot: the bootloader tries the
    # pending slot first and rolls back if it fails. Switching active here
    # would skip that protection.
    monkeypatch.setattr(ota, "_boot_is_locked", lambda: False)
    monkeypatch.setattr(ota, "_rollback_floor", lambda: 0)
    monkeypatch.setattr(ota, "get_current_version", lambda: "3.2.0")
    monkeypatch.setattr(ota, "get_update_version", lambda _p: "3.2.1")
    monkeypatch.setattr(ota, "_safe_extract_package",
                        lambda _p, _d: None)
    monkeypatch.setattr(ota, "_slot_is_ready", lambda _p: True)
    monkeypatch.setattr(secure_boot, "verify_package", lambda *_a, **_k: None)
    monkeypatch.setattr(ota, "verify_update_compatibility", lambda _p: True)
    package = os.path.join(root, "update.zip")
    with open(package, "wb") as stream:
        stream.write(b"PK\x05\x06" + b"\x00" * 18)
    assert ota.install_package_to_slot(package, ota.SLOT_B) is True
    state = read_boot_state(root)
    assert state["pending_slot"] == ota.SLOT_B
    assert state["active_slot"] != ota.SLOT_B


def test_prepare_boot_prefers_the_pending_slot(root):
    secure_boot.set_active_slot(root, ota.SLOT_A)
    secure_boot.stage_slot(root, ota.SLOT_B)
    for slot in (ota.SLOT_A, ota.SLOT_B):
        os.makedirs(os.path.join(root, slot), exist_ok=True)
        with open(os.path.join(root, slot, "main.py"), "w",
                  encoding="utf-8") as stream:
            stream.write("# slot\n")
    selection = secure_boot.prepare_boot(root, False)
    assert selection["slot"] == ota.SLOT_B
