import hashlib
import os
import zipfile

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import secure_boot


def _key_pair():
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    keys = {secure_boot.public_key_id(public): public}
    return private, keys


def _write_image(root, private, keys, security_version=1):
    slot = root / "slot_a"
    slot.mkdir(exist_ok=True)
    (slot / "main.py").write_text("print('signed')\n", encoding="utf-8")
    (slot / "kernel.py").write_text("LOOP = True\n", encoding="utf-8")
    files = {}
    for name in ("main.py", "kernel.py"):
        files[name] = hashlib.sha256((slot / name).read_bytes()).hexdigest()
    manifest = {
        "format": 1,
        "algorithm": "ed25519",
        "product": "PySpOS",
        "version": "1.0.0",
        "security_version": security_version,
        "key_id": next(iter(keys)),
        "files": files,
    }
    raw = secure_boot.canonical_bytes(manifest)
    (slot / secure_boot.MANIFEST_NAME).write_bytes(raw)
    (slot / secure_boot.SIGNATURE_NAME).write_bytes(private.sign(raw))
    return manifest


def test_locked_boot_requires_a_valid_signature(tmp_path):
    private, keys = _key_pair()
    _write_image(tmp_path, private, keys)
    selection = secure_boot.prepare_boot(str(tmp_path), True, keys=keys,
                                          legacy_slot="slot_a")
    assert selection["slot"] == "slot_a"
    assert selection["manifest"]["security_version"] == 1


def test_tampered_image_fails_closed(tmp_path):
    private, keys = _key_pair()
    _write_image(tmp_path, private, keys)
    (tmp_path / "slot_a" / "main.py").write_text("print('tampered')\n",
                                                   encoding="utf-8")
    with pytest.raises(secure_boot.BootVerificationError):
        secure_boot.prepare_boot(str(tmp_path), True, keys=keys,
                                 legacy_slot="slot_a")


def test_unsigned_image_is_rejected_only_when_locked(tmp_path):
    slot = tmp_path / "slot_a"
    slot.mkdir(exist_ok=True)
    (slot / "main.py").write_text("print('dev')\n", encoding="utf-8")
    assert secure_boot.prepare_boot(str(tmp_path), False, keys={},
                                    legacy_slot="slot_a")["manifest"] is None
    with pytest.raises(secure_boot.BootVerificationError):
        secure_boot.prepare_boot(str(tmp_path), True, keys={},
                                 legacy_slot="slot_a")


def test_wrong_key_and_rollback_are_rejected(tmp_path):
    private, keys = _key_pair()
    other_private, other_keys = _key_pair()
    _write_image(tmp_path, private, keys, security_version=2)
    wrong = dict(other_keys)
    with pytest.raises(secure_boot.BootVerificationError):
        secure_boot.verify_tree(str(tmp_path / "slot_a"),
                                secure_boot.parse_manifest(
                                    (tmp_path / "slot_a" / secure_boot.MANIFEST_NAME).read_bytes()),
                                keys=wrong)
    secure_boot.mark_boot_success(str(tmp_path), "slot_a",
                                  secure_boot.verify_slot(str(tmp_path), "slot_a",
                                                           keys=keys))
    _write_image(tmp_path, other_private, other_keys, security_version=1)
    with pytest.raises(secure_boot.BootVerificationError):
        secure_boot.prepare_boot(str(tmp_path), True, keys=other_keys,
                                 legacy_slot="slot_a")


def test_boot_state_members_are_skipped_not_rejected(tmp_path):
    """3.2.0 真实事故：包里混入构建机的 src/current_slot。

    启动期状态描述的是构建那台机器，不该落地；验签跳过它们，
    更新照常进行，而不是让整个包失败。
    """
    package = tmp_path / "update.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("src/main.py", "print('package')\n")
        archive.writestr("src/current_slot", "slot_a")
        archive.writestr("current_slot", "slot_a")
        archive.writestr(".hotreset", "x")
    # 未签名 + 未锁定：跳过状态文件后验证通过
    assert secure_boot.verify_package(str(package), locked=False) is None

    # 签名路径同样跳过：manifest 清单里不应出现状态文件
    private, keys = _key_pair()
    signed = tmp_path / "signed.zip"
    with zipfile.ZipFile(signed, "w") as archive:
        archive.writestr("src/main.py", "print('package')\n")
        archive.writestr("src/current_slot", "slot_a")
    secure_boot.sign_package(str(signed), "1.0.0", 4, private, trusted_keys=keys)
    manifest = secure_boot.verify_package(str(signed), keys=keys, locked=True)
    assert manifest["security_version"] == 4
    assert "current_slot" not in manifest["files"]
    assert "src/current_slot" not in manifest["files"]


def test_signed_package_and_path_traversal(tmp_path):
    private, keys = _key_pair()
    package = tmp_path / "update.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("src/main.py", "print('package')\n")
        archive.writestr("src/kernel.py", "LOOP = True\n")
    secure_boot.sign_package(str(package), "1.0.0", 4, private, trusted_keys=keys)
    manifest = secure_boot.verify_package(str(package), keys=keys, locked=True)
    assert manifest["security_version"] == 4

    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as archive:
        archive.writestr("src/../escape.py", "bad")
    with pytest.raises(secure_boot.BootVerificationError):
        secure_boot.verify_package(str(bad), keys=keys, locked=False)


def test_signed_package_keeps_verification_files_on_install(tmp_path):
    import ota
    private, keys = _key_pair()
    package = tmp_path / "update.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("src/main.py", "print('package')\n")
        archive.writestr("src/kernel.py", "LOOP = True\n")
    secure_boot.sign_package(str(package), "1.0.0", 4, private, trusted_keys=keys)
    staging = tmp_path / "staging"
    staging.mkdir()
    ota._safe_extract_package(str(package), str(staging))
    assert (staging / secure_boot.MANIFEST_NAME).is_file()
    assert (staging / secure_boot.SIGNATURE_NAME).is_file()


def test_boot_state_is_atomic_and_pending_state_is_tracked(tmp_path):
    state = secure_boot.load_state(str(tmp_path))
    assert state["rollback_index"] == 0
    secure_boot.stage_slot(str(tmp_path), "slot_b")
    state = secure_boot.load_state(str(tmp_path))
    assert state["pending_slot"] == "slot_b"
    assert state["attempts_remaining"] == 3
    secure_boot.mark_boot_success(str(tmp_path), "slot_b")
    state = secure_boot.load_state(str(tmp_path))
    assert state["active_slot"] == "slot_b"
    assert state["pending_slot"] is None


def test_policy_signature_controls_lock_state(tmp_path):
    private, keys = _key_pair()
    secure_boot.write_policy(str(tmp_path), True, 3, private, trusted_keys=keys)
    assert secure_boot.read_locked(str(tmp_path), keys) is True
    policy_path = tmp_path / secure_boot.PROTECTED_DIR / secure_boot.POLICY_NAME
    policy_path.write_bytes(policy_path.read_bytes().replace(b'"locked":true', b'"locked":false'))
    with pytest.raises(secure_boot.BootVerificationError):
        secure_boot.read_policy(str(tmp_path), keys)


def test_missing_policy_fails_closed(tmp_path):
    assert secure_boot.read_locked(str(tmp_path)) is True


def test_oobe_developer_key_only_trusts_unlocked_images(tmp_path, monkeypatch):
    monkeypatch.setattr(secure_boot, "_RUNTIME_TRUSTED_KEYS", {})
    info = secure_boot.ensure_developer_key(str(tmp_path), locked=False)
    assert os.path.isfile(info["private_key"])
    assert secure_boot.configure_runtime_keys(str(tmp_path), False)
    package = tmp_path / "dev.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("src/main.py", "print('dev')\n")
        archive.writestr("src/kernel.py", "LOOP = True\n")
    secure_boot.sign_package(str(package), "1.0.0", 1, info["private_key"])
    assert secure_boot.verify_package(str(package), locked=False)["key_id"] == info["key_id"]
    secure_boot.configure_runtime_keys(str(tmp_path), True)
    with pytest.raises(secure_boot.BootVerificationError):
        secure_boot.verify_package(str(package), locked=True)
    with pytest.raises(secure_boot.BootVerificationError):
        secure_boot.write_policy(str(tmp_path), True, 1, info["private_key"])


def test_legacy_token_cannot_change_policy():
    import api
    assert not hasattr(api, "return_token")
    assert api._local_set_lockstate(False) is False


def test_reset_slot_preserves_policy_and_is_locked_safe(tmp_path, monkeypatch):
    import reset_slot
    private, keys = _key_pair()
    monkeypatch.setattr(secure_boot, "TRUSTED_PUBLIC_KEYS", keys)
    secure_boot.write_policy(str(tmp_path), False, 0, private, trusted_keys=keys)
    slot = tmp_path / "slot_a"
    slot.mkdir()
    (slot / "stale.py").write_text("old", encoding="utf-8")
    assert reset_slot.wipe_slots(str(tmp_path), ["slot_a"], assume_yes=True)
    assert not slot.exists()
    assert secure_boot.read_policy(str(tmp_path), keys)["locked"] is False
    secure_boot.write_policy(str(tmp_path), True, 1, private, trusted_keys=keys)
    with pytest.raises(RuntimeError):
        reset_slot.wipe_slots(str(tmp_path), ["slot_a"], assume_yes=True)
