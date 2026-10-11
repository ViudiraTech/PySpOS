'''
 *
 *      test_boot_repair.py
 *      Bootloader repair prompt: locked mode refuses silently, unlocked mode
 *      asks once, repairs developer keys and retries verification a single time.
 *
 *      2026/10/11 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import argparse
import sys
import types

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest

import launcher
import secure_boot


# Locked verification failures refuse without ever prompting: asking would
# turn verified boot into a dialog box.
def test_locked_refusal_never_prompts(monkeypatch):
    monkeypatch.setattr(secure_boot, "read_locked", lambda root: True)
    monkeypatch.setattr(secure_boot, "configure_runtime_keys", lambda *a: {})
    def boom(*a, **k):
        raise secure_boot.BootVerificationError("policy 使用了不受信任的密钥")
    monkeypatch.setattr(secure_boot, "prepare_boot", boom)
    def no_input(*a):
        raise AssertionError("locked path must not prompt")
    monkeypatch.setattr("builtins.input", no_input)
    assert launcher.main([]) == 1


# Declining (or hanging up on) the prompt refuses after exactly one attempt.
@pytest.mark.parametrize("answer", ["n", EOFError()])
def test_unlocked_decline_refuses_without_retry(monkeypatch, answer):
    calls = []
    monkeypatch.setattr(secure_boot, "read_locked", lambda root: False)
    monkeypatch.setattr(secure_boot, "configure_runtime_keys", lambda *a: {})
    def boom(*a, **k):
        calls.append(1)
        raise secure_boot.BootVerificationError("policy 使用了不受信任的密钥")
    monkeypatch.setattr(secure_boot, "prepare_boot", boom)
    def reply(*a):
        if isinstance(answer, BaseException):
            raise answer
        return answer
    monkeypatch.setattr("builtins.input", reply)
    assert launcher.main([]) == 1
    assert len(calls) == 1


# Accepting repairs and retries; a clean retry continues the boot.
def test_unlocked_repair_retry_succeeds(monkeypatch):
    calls = []
    ensured = []
    monkeypatch.setattr(secure_boot, "read_locked", lambda root: False)
    monkeypatch.setattr(secure_boot, "configure_runtime_keys", lambda *a: {})
    def prepare(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise secure_boot.BootVerificationError("policy 使用了不受信任的密钥")
        return None
    monkeypatch.setattr(secure_boot, "prepare_boot", prepare)
    monkeypatch.setattr(secure_boot, "ensure_developer_key",
                        lambda root, locked=False: ensured.append(root) or {"key_id": "abc"})
    monkeypatch.setattr("builtins.input", lambda *a: "y")
    monkeypatch.setattr(launcher, "_prepare_runtime", lambda *a: None)
    fake = types.ModuleType("hotreset_env")
    fake.run = lambda **kwargs: 0
    monkeypatch.setitem(sys.modules, "hotreset_env", fake)
    assert launcher.main([]) == 0
    assert len(calls) == 2
    assert ensured


# A repair that cannot fix the trust (foreign-signed policy) still refuses,
# but names both key ids and the exact reissue command.
def test_unlocked_repair_still_fails_diagnoses(monkeypatch, capsys):
    monkeypatch.setattr(secure_boot, "read_locked", lambda root: False)
    monkeypatch.setattr(secure_boot, "configure_runtime_keys", lambda *a: {})
    def boom(*a, **k):
        raise secure_boot.BootVerificationError("policy 使用了不受信任的密钥")
    monkeypatch.setattr(secure_boot, "prepare_boot", boom)
    monkeypatch.setattr(secure_boot, "ensure_developer_key",
                        lambda root, locked=False: {"key_id": "abc"})
    monkeypatch.setattr("builtins.input", lambda *a: "y")
    assert launcher.main([]) == 1
    out = capsys.readouterr().out
    assert "policy 声明 key_id=" in out
    assert "flashing unlock" in out


# Against a real directory the repair heals an unreadable public key file.
def test_repair_heals_unreadable_public_key(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(secure_boot, "_RUNTIME_TRUSTED_KEYS", {})
    args = argparse.Namespace(slot=None, fastboot=False)
    monkeypatch.setattr("builtins.input", lambda *a: "y")
    repaired, selection = launcher._maybe_repair_and_retry(str(tmp_path), False, args)
    assert (repaired, selection) == (True, None)
    public = tmp_path / secure_boot.PROTECTED_DIR / secure_boot.DEVICE_PUBLIC_KEY_NAME
    assert public.is_file() and secure_boot.developer_key_id(str(tmp_path))


# A policy signed by a foreign key stays refused after repair, with the hint.
def test_repair_keeps_foreign_policy_refused(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(secure_boot, "_RUNTIME_TRUSTED_KEYS", {})
    foreign = Ed25519PrivateKey.generate()
    pem_path = tmp_path / "foreign.pem"
    pem_path.write_bytes(foreign.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    raw_foreign = foreign.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    secure_boot.write_policy(str(tmp_path), False, 0, str(pem_path),
                             trusted_keys={secure_boot.public_key_id(raw_foreign):
                                           raw_foreign})
    args = argparse.Namespace(slot=None, fastboot=False)
    monkeypatch.setattr("builtins.input", lambda *a: "y")
    assert launcher._maybe_repair_and_retry(str(tmp_path), False, args) == (False, None)
    out = capsys.readouterr().out
    assert "flashing unlock" in out
