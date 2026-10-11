'''
 *
 *      test_tool_prompts.py
 *      Hardened y/n prompts in the root maintenance tools.
 *
 *      2026/10/11 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import builtins
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import secure_boot


# No policy file means "locked by default", so every prompt test writes a real
# unlocked policy first, the way a developer machine actually looks.
def _unlock(tmp_path, monkeypatch):
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    keys = {secure_boot.public_key_id(public): public}
    monkeypatch.setattr(secure_boot, "TRUSTED_PUBLIC_KEYS", keys)
    monkeypatch.setattr(secure_boot, "_RUNTIME_TRUSTED_KEYS", {})
    secure_boot.write_policy(str(tmp_path), False, 0, private, trusted_keys=keys)


# Wire the terminal prompt to a fixed answer, with stty healing stubbed out
# so the suite never touches the real terminal.
def _answer(monkeypatch, answer):
    import ttyutil
    monkeypatch.setattr(ttyutil, "ensure_sane_tty", lambda: False)
    monkeypatch.setattr(builtins, "input", lambda _prompt: answer)


# A bare CR from a half-broken terminal still counts as yes.
def test_reset_slot_prompt_accepts_cr_yes(tmp_path, monkeypatch):
    import reset_slot
    _unlock(tmp_path, monkeypatch)
    slot = tmp_path / "slot_a"
    slot.mkdir()
    (slot / "stale.py").write_text("old", encoding="utf-8")
    _answer(monkeypatch, "y\r")
    assert reset_slot.wipe_slots(str(tmp_path), ["slot_a"], assume_yes=False) is True
    assert not slot.exists()


# An empty answer takes the default: cancel, nothing deleted.
def test_reset_slot_prompt_defaults_to_cancel(tmp_path, monkeypatch):
    import reset_slot
    _unlock(tmp_path, monkeypatch)
    slot = tmp_path / "slot_a"
    slot.mkdir()
    _answer(monkeypatch, "")
    assert reset_slot.wipe_slots(str(tmp_path), ["slot_a"], assume_yes=False) is False
    assert slot.exists()


# force_sync cancels on an explicit no, even with a stray CR attached.
def test_force_sync_prompt_cancels_on_no(tmp_path, monkeypatch):
    import force_sync
    _unlock(tmp_path, monkeypatch)
    (tmp_path / "src").mkdir()
    (tmp_path / "slot_a").mkdir()
    _answer(monkeypatch, "n\r")
    assert force_sync.sync_slot(str(tmp_path), "slot_a", assume_yes=False) is False
    assert (tmp_path / "slot_a").exists()


# The build tool's question strips a bare CR instead of reading "y\r".
def test_build_update_ask_strips_carriage_return(monkeypatch):
    import ttyutil
    import build_update
    monkeypatch.setattr(ttyutil, "ensure_sane_tty", lambda: False)
    monkeypatch.setattr(builtins, "input", lambda _prompt: "y\r")

    class _Interactive:
        def isatty(self):
            return True

    monkeypatch.setattr(sys, "stdin", _Interactive())
    assert build_update._ask("继续？ ") == "y"


# Non-interactive stdin keeps the documented default without reading at all.
def test_build_update_ask_uses_default_when_not_a_tty(monkeypatch):
    import build_update

    def _no_read(_prompt):
        raise AssertionError("不应读取输入")

    monkeypatch.setattr(builtins, "input", _no_read)
    assert build_update._ask("继续？ ", default="rc") == "rc"
