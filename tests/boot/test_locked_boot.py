'''
 *
 *      test_locked_boot.py
 *      End-to-end locked boot over a throwaway root, throwaway keys and a hand-written manifest.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import base64
import sys

import pytest

import secure_boot
from secure_boot import BootVerificationError


# Generate a throwaway Ed25519 key pair plus the trusted-key map keyed by its key id.
def _make_keys():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519
    priv = ed25519.Ed25519PrivateKey.generate()
    pub_raw = priv.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    key_id = secure_boot.public_key_id(pub_raw)
    keys = {key_id: base64.b64encode(pub_raw).decode("ascii")}
    return priv, key_id, keys


# Manifest every file in the slot except the manifest and signature, then sign the canonical bytes.
def _sign_slot(slot_dir, priv, key_id, security_version=0):
    files = {}
    for rel, full in secure_boot._iter_tree_files(str(slot_dir)):
        if rel in (secure_boot.MANIFEST_NAME, secure_boot.SIGNATURE_NAME):
            continue
        files[rel] = secure_boot.sha256_file(full)
    manifest = {"format": 1, "algorithm": "ed25519", "product": "PySpOS",
                "version": "9.9.9-test", "security_version": security_version,
                "key_id": key_id, "files": files}
    raw = secure_boot.canonical_bytes(manifest)
    with open(slot_dir / secure_boot.MANIFEST_NAME, "wb") as f:
        f.write(raw)
    with open(slot_dir / secure_boot.SIGNATURE_NAME, "wb") as f:
        f.write(secure_boot.sign_bytes(priv, raw))


# Save a private key where write_policy can take it by path.
def _save_private(tmp_path, priv, name="oem.pem"):
    from cryptography.hazmat.primitives import serialization
    path = tmp_path / name
    path.write_bytes(priv.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    return str(path)


# Build a minimal two-file slot tree; the real slots are never touched.
def _fake_root(tmp_path):
    slot = tmp_path / "slot_a"
    (slot / "lib").mkdir(parents=True)
    (slot / "main.py").write_text("print('hi')\n", encoding="utf-8")
    (slot / "lib" / "core.py").write_text("X = 1\n", encoding="utf-8")
    return slot


# A correctly signed slot is accepted and selected on a locked device.
def test_locked_boot_accepts_signed_slot(tmp_path):
    priv, key_id, keys = _make_keys()
    slot = _fake_root(tmp_path)
    _sign_slot(slot, priv, key_id)
    sel = secure_boot.prepare_boot(
        str(tmp_path), True, keys=keys, legacy_slot="slot_a")
    assert sel is not None and sel["slot"] == "slot_a"


# A file changed after signing must fail verification closed rather than boot anyway.
def test_locked_boot_rejects_tampered_slot(tmp_path):
    priv, key_id, keys = _make_keys()
    slot = _fake_root(tmp_path)
    _sign_slot(slot, priv, key_id)
    (slot / "lib" / "core.py").write_text("X = 2\n", encoding="utf-8")
    with pytest.raises(BootVerificationError):
        secure_boot.prepare_boot(
            str(tmp_path), True, keys=keys, legacy_slot="slot_a")


# A signature made with a key outside the trust store must not verify.
def test_locked_boot_rejects_wrong_key(tmp_path):
    _, key_id, _ = _make_keys()
    _, _, other_keys = _make_keys()
    slot = _fake_root(tmp_path)
    priv, _, _ = _make_keys()
    _sign_slot(slot, priv, key_id)
    with pytest.raises(BootVerificationError):
        secure_boot.prepare_boot(
            str(tmp_path), True, keys=other_keys, legacy_slot="slot_a")


# A manifest below the policy rollback floor must not boot, even if signed.
def test_locked_boot_rejects_rollback(tmp_path):
    priv, key_id, keys = _make_keys()
    slot = _fake_root(tmp_path)
    _sign_slot(slot, priv, key_id, security_version=1)
    secure_boot.write_policy(str(tmp_path), True, 2, _save_private(tmp_path, priv),
                             trusted_keys=keys)
    with pytest.raises(BootVerificationError):
        secure_boot.prepare_boot(
            str(tmp_path), True, keys=keys, legacy_slot="slot_a")


# The same image boots once the floor matches its security version.
def test_locked_boot_accepts_matching_floor(tmp_path):
    priv, key_id, keys = _make_keys()
    slot = _fake_root(tmp_path)
    _sign_slot(slot, priv, key_id, security_version=2)
    secure_boot.write_policy(str(tmp_path), True, 2, _save_private(tmp_path, priv),
                             trusted_keys=keys)
    assert secure_boot.read_locked(str(tmp_path), keys) is True
    sel = secure_boot.prepare_boot(
        str(tmp_path), True, keys=keys, legacy_slot="slot_a")
    assert sel is not None and sel["slot"] == "slot_a"
    assert sel["manifest"]["security_version"] == 2


# Locked mode never falls back: an unsigned slot refuses instead of booting src.
def test_locked_boot_rejects_unsigned_slot(tmp_path):
    priv, _, keys = _make_keys()
    _fake_root(tmp_path)
    secure_boot.write_policy(str(tmp_path), True, 0, _save_private(tmp_path, priv),
                             trusted_keys=keys)
    with pytest.raises(BootVerificationError, match="没有通过签名"):
        secure_boot.prepare_boot(
            str(tmp_path), True, keys=keys, legacy_slot="slot_a")


# The sanctioned unlock -> lock round trip on a throwaway root: unlock wipes
# user data and writes an unlocked policy, lock refuses an unsigned slot,
# then succeeds once the slot is signed and the device boots locked.
def test_unlock_lock_cycle(tmp_path, monkeypatch):
    oem_priv, oem_id, oem_keys = _make_keys()
    monkeypatch.setattr(secure_boot, "TRUSTED_PUBLIC_KEYS", oem_keys)
    monkeypatch.setattr(secure_boot, "_RUNTIME_TRUSTED_KEYS", {})
    import fastboot
    import main
    import ota
    monkeypatch.setattr(main, "root_dir", str(tmp_path))
    monkeypatch.setattr(ota, "get_current_slot", lambda: "slot_a")
    slot = tmp_path / "slot_a"
    slot.mkdir(parents=True)
    (slot / "main.py").write_text("print('hi')\n", encoding="utf-8")
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc" / "bootcfg.json").write_text("{}", encoding="utf-8")

    # Unsigned active slot: locking must refuse (the brick guard).
    ok, message = fastboot.perform_lock()
    assert ok is False and "签名镜像" in message

    # Unlock wipes user data and leaves an unlocked, verifiable policy.
    ok, message = fastboot.perform_unlock()
    assert ok is True, message
    assert not (tmp_path / "etc" / "bootcfg.json").exists()
    assert secure_boot.read_locked(str(tmp_path)) is False

    # Sign the slot, lock, and boot locked.
    _sign_slot(slot, oem_priv, oem_id, security_version=1)
    ok, message = fastboot.perform_lock()
    assert ok is True, message
    assert secure_boot.read_locked(str(tmp_path)) is True
    sel = secure_boot.prepare_boot(str(tmp_path), True)
    assert sel is not None and sel["slot"] == "slot_a"


# Pending-slot attempts tick down per boot and clear on success, and success
# advances the rollback floor from the booted manifest.
def test_pending_attempts_and_success_floor(tmp_path):
    priv, key_id, keys = _make_keys()
    slot = _fake_root(tmp_path)
    _sign_slot(slot, priv, key_id, security_version=5)
    state = secure_boot.load_state(str(tmp_path))
    state.update(pending_slot="slot_a", attempts_remaining=3)
    secure_boot.save_state(str(tmp_path), state)
    sel = secure_boot.prepare_boot(
        str(tmp_path), True, keys=keys, legacy_slot="slot_a")
    assert sel["slot"] == "slot_a"
    assert secure_boot.load_state(str(tmp_path))["attempts_remaining"] == 2
    secure_boot.mark_boot_success(str(tmp_path), "slot_a", sel["manifest"])
    state = secure_boot.load_state(str(tmp_path))
    assert (state["active_slot"], state["pending_slot"],
            state["attempts_remaining"], state["rollback_index"]) == \
        ("slot_a", None, 0, 5)
