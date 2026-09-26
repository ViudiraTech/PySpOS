'''
 *
 *      test_bootmode.py
 *      Tests for the boot mode request that carries a fastboot reboot across
 *      processes, the PySpOS counterpart of the AOSP BCB message.
 *
 *      2026/9/26 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import os

import pytest

import bootmode


@pytest.fixture
def root(tmp_path):
    return str(tmp_path)


def test_default_is_normal(root):
    assert bootmode.read_mode(root) == bootmode.MODE_NORMAL
    assert bootmode.wants_fastboot(root) is False


def test_request_fastboot(root):
    assert bootmode.request_mode(root, bootmode.MODE_FASTBOOT) is True
    assert bootmode.wants_fastboot(root) is True
    assert bootmode.read_mode(root) == bootmode.MODE_FASTBOOT


def test_only_one_shot_mode_exists(root):
    # A sticky variant was deliberately not added: every request is consumed
    # by the boot that honours it, and asking again just writes it again.
    assert bootmode.VALID_MODES == (bootmode.MODE_NORMAL, bootmode.MODE_FASTBOOT)
    assert not hasattr(bootmode, "MODE_FASTBOOT_ONCE")


def test_request_lives_in_protected_dir(root):
    import secure_boot
    path = bootmode.request_path(root)
    assert path == os.path.join(root, secure_boot.PROTECTED_DIR, "boot_mode")


def test_clear_removes_request(root):
    bootmode.request_mode(root, bootmode.MODE_FASTBOOT)
    bootmode.clear_mode(root)
    assert bootmode.wants_fastboot(root) is False
    assert not os.path.exists(bootmode.request_path(root))


def test_clear_is_idempotent(root):
    bootmode.clear_mode(root)
    bootmode.clear_mode(root)
    assert bootmode.read_mode(root) == bootmode.MODE_NORMAL


def test_rejects_unknown_mode(root):
    assert bootmode.request_mode(root, "recovery") is False
    assert bootmode.request_mode(root, "") is False
    assert bootmode.read_mode(root) == bootmode.MODE_NORMAL


def test_corrupt_request_falls_back_to_normal(root):
    path = bootmode.request_path(root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as stream:
        stream.write("nonsense-mode")
    assert bootmode.read_mode(root) == bootmode.MODE_NORMAL
    assert bootmode.wants_fastboot(root) is False


def test_empty_request_falls_back_to_normal(root):
    path = bootmode.request_path(root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as stream:
        stream.write("")
    assert bootmode.wants_fastboot(root) is False


def test_clear_ignores_symlink(root):
    path = bootmode.request_path(root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    target = os.path.join(root, "elsewhere")
    with open(target, "w", encoding="utf-8") as stream:
        stream.write(bootmode.MODE_FASTBOOT)
    os.symlink(target, path)
    bootmode.clear_mode(root)
    # The link must survive: following it would delete an unrelated file.
    assert os.path.islink(path)
    assert os.path.isfile(target)


def test_reboot_bootloader_sets_request(root, monkeypatch):
    import fastboot
    monkeypatch.setattr(fastboot.main, "root_dir", root)
    fastboot.reset_state()
    assert fastboot.handle_command("reboot-bootloader") == "OKAY"
    assert bootmode.wants_fastboot(root) is True


def test_plain_reboot_clears_request(root, monkeypatch):
    import fastboot
    monkeypatch.setattr(fastboot.main, "root_dir", root)
    bootmode.request_mode(root, bootmode.MODE_FASTBOOT)
    fastboot.reset_state()
    assert fastboot.handle_command("reboot") == "OKAY"
    assert bootmode.wants_fastboot(root) is False


def test_continue_clears_request(root, monkeypatch):
    import fastboot
    monkeypatch.setattr(fastboot.main, "root_dir", root)
    bootmode.request_mode(root, bootmode.MODE_FASTBOOT)
    fastboot.reset_state()
    assert fastboot.handle_command("continue").startswith("OKAY")
    assert bootmode.wants_fastboot(root) is False


def test_powerdown_clears_request(root, monkeypatch):
    import fastboot
    monkeypatch.setattr(fastboot.main, "root_dir", root)
    bootmode.request_mode(root, bootmode.MODE_FASTBOOT)
    fastboot.reset_state()
    assert fastboot.handle_command("powerdown") == "OKAY"
    assert bootmode.wants_fastboot(root) is False


def test_boot_clears_request_and_targets_system(root, monkeypatch):
    import fastboot
    monkeypatch.setattr(fastboot.main, "root_dir", root)
    bootmode.request_mode(root, bootmode.MODE_FASTBOOT)
    fastboot.reset_state()
    fastboot.stage_bytes(b"image")
    assert fastboot.handle_command("boot").startswith("OKAY")
    assert bootmode.wants_fastboot(root) is False
    assert fastboot.take_pending_boot() == "system"


def test_kernel_boot_path_consumes_the_request(monkeypatch, tmp_path):
    import kernel
    import main as main_mod
    root = str(tmp_path)
    bootmode.request_mode(root, bootmode.MODE_FASTBOOT)
    monkeypatch.setattr(main_mod, "root_dir", root)

    def fake_fastboot_boot():
        raise SystemExit(0)

    monkeypatch.setattr(kernel, "_fastboot_boot", fake_fastboot_boot)
    with pytest.raises(SystemExit):
        kernel.loop()
    # Honoured once and gone, so the next plain boot reaches the system.
    assert bootmode.wants_fastboot(root) is False


def test_kernel_boot_path_prefers_fastboot(monkeypatch):
    import kernel
    calls = []

    def fake_fastboot_boot():
        calls.append("fastboot")
        raise SystemExit(0)

    monkeypatch.setattr(bootmode, "wants_fastboot", lambda _root: True)
    monkeypatch.setattr(kernel, "_fastboot_boot", fake_fastboot_boot)
    monkeypatch.setattr("oobe.maybe_run_oobe",
                        lambda _root: pytest.fail("OOBE must not run"))
    with pytest.raises(SystemExit):
        kernel.loop()
    assert calls == ["fastboot"]


def test_kernel_boot_path_runs_oobe_when_not_requested(monkeypatch):
    import kernel
    calls = []

    class StopBoot(Exception):
        pass

    def fake_oobe(_root):
        calls.append("oobe")
        return False

    def fake_ota_init():
        raise StopBoot()

    monkeypatch.setattr(bootmode, "wants_fastboot", lambda _root: False)
    monkeypatch.setattr(kernel, "_fastboot_boot",
                        lambda: pytest.fail("fastboot must not run"))
    monkeypatch.setattr("oobe.maybe_run_oobe", fake_oobe)
    monkeypatch.setattr("ota.ota_init", fake_ota_init)
    monkeypatch.setattr(kernel, "screen_clear", lambda: None)
    with pytest.raises(StopBoot):
        kernel.loop()
    assert calls == ["oobe"]
