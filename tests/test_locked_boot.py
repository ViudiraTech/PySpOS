"""LOCKED 签名启动端到端：tmp 伪根 + 现场密钥对 + 手工槽 manifest。

不碰真实槽位与 LOCKED 文件，只调 prepare_boot(locked=True)。
"""
import base64
import sys

import pytest

sys.path.insert(0, ".")
sys.path.insert(0, "src")
import secure_boot
from secure_boot import BootVerificationError


def _make_keys():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519
    priv = ed25519.Ed25519PrivateKey.generate()
    pub_raw = priv.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    key_id = secure_boot.public_key_id(pub_raw)
    keys = {key_id: base64.b64encode(pub_raw).decode("ascii")}
    return priv, key_id, keys


def _sign_slot(slot_dir, priv, key_id):
    files = {}
    for rel, full in secure_boot._iter_tree_files(str(slot_dir)):
        if rel in (secure_boot.MANIFEST_NAME, secure_boot.SIGNATURE_NAME):
            continue
        files[rel] = secure_boot.sha256_file(full)
    manifest = {"format": 1, "algorithm": "ed25519", "product": "PySpOS",
                "version": "9.9.9-test", "security_version": 0,
                "key_id": key_id, "files": files}
    raw = secure_boot.canonical_bytes(manifest)
    with open(slot_dir / secure_boot.MANIFEST_NAME, "wb") as f:
        f.write(raw)
    with open(slot_dir / secure_boot.SIGNATURE_NAME, "wb") as f:
        f.write(secure_boot.sign_bytes(priv, raw))


def _fake_root(tmp_path):
    slot = tmp_path / "slot_a"
    (slot / "lib").mkdir(parents=True)
    (slot / "main.py").write_text("print('hi')\n", encoding="utf-8")
    (slot / "lib" / "core.py").write_text("X = 1\n", encoding="utf-8")
    return slot


def test_locked_boot_accepts_signed_slot(tmp_path):
    priv, key_id, keys = _make_keys()
    slot = _fake_root(tmp_path)
    _sign_slot(slot, priv, key_id)
    sel = secure_boot.prepare_boot(
        str(tmp_path), True, keys=keys, legacy_slot="slot_a")
    assert sel is not None and sel["slot"] == "slot_a"


def test_locked_boot_rejects_tampered_slot(tmp_path):
    priv, key_id, keys = _make_keys()
    slot = _fake_root(tmp_path)
    _sign_slot(slot, priv, key_id)
    (slot / "lib" / "core.py").write_text("X = 2\n", encoding="utf-8")
    with pytest.raises(BootVerificationError):
        secure_boot.prepare_boot(
            str(tmp_path), True, keys=keys, legacy_slot="slot_a")


def test_locked_boot_rejects_wrong_key(tmp_path):
    _, key_id, _ = _make_keys()
    _, _, other_keys = _make_keys()
    slot = _fake_root(tmp_path)
    priv, _, _ = _make_keys()
    _sign_slot(slot, priv, key_id)
    with pytest.raises(BootVerificationError):
        secure_boot.prepare_boot(
            str(tmp_path), True, keys=other_keys, legacy_slot="slot_a")
