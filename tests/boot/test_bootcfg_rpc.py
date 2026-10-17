'''
 *
 *      test_bootcfg_rpc.py
 *      The set_bootcfg op: which keys a child may change, and what it validates.
 *
 *      2026/10/16 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */

'''

import pytest

import btcfg
import forkexec


# Capture preference writes so a test run never reaches etc/bootcfg.json.
@pytest.fixture()
def written(monkeypatch):
    records = []
    monkeypatch.setattr(btcfg, "set_bootcfg_value",
                        lambda key, value: records.append((key, value)))
    return records


# Capture audit records instead of appending to the repository's log.
@pytest.fixture()
def audited(monkeypatch):
    records = []
    monkeypatch.setattr(forkexec, "_audit",
                        lambda action, detail: records.append((action, detail)))
    return records


# Put the process-wide locale back: a successful change applies it live, and the
# rest of the suite should see the language and zone it started with.
@pytest.fixture()
def restore_locale():
    import syslocale
    before = (syslocale.get_language(), syslocale.get_timezone())
    yield
    syslocale.set_language(before[0])
    syslocale.set_timezone(before[1])


def test_set_bootcfg_persists_a_preference(written, audited, restore_locale):
    assert forkexec._sysctl_handler("set_bootcfg", ["lang", "en"], {}) is True
    assert written == [("lang", "en")]
    assert audited == [("set_bootcfg", "lang=en")]


# The trust state is not the settings screen's to change: it stays behind
# authorize_root and the signed policy, so the op refuses it outright rather
# than ignoring the write.
def test_set_bootcfg_refuses_privileged_keys(written):
    for key in ("locked", "rootstate", "checksum", "display_name "):
        with pytest.raises(PermissionError, match="不允许"):
            forkexec._sysctl_handler("set_bootcfg", [key, "true"], {})
    assert written == []


# Values are validated the same way the shell commands validate them, and a
# rejected value is never written.
def test_set_bootcfg_rejects_unknown_values(written, restore_locale):
    with pytest.raises(ValueError, match="不支持的语言"):
        forkexec._sysctl_handler("set_bootcfg", ["lang", "klingon"], {})
    with pytest.raises(ValueError, match="未知时区"):
        forkexec._sysctl_handler("set_bootcfg", ["timezone", "Mars/Olympus"], {})
    with pytest.raises(ValueError, match="未知更新通道"):
        forkexec._sysctl_handler("set_bootcfg", ["ota_channel", "nightly"], {})
    with pytest.raises(ValueError, match="显示名不能为空"):
        forkexec._sysctl_handler("set_bootcfg", ["display_name", "   "], {})
    assert written == []


# Every whitelisted key is accepted when the value is good, so the whitelist is
# not accidentally narrower than the settings screen needs.
def test_every_whitelisted_key_is_writable(written, audited, restore_locale):
    for key, value in (("lang", "zh_CN"), ("timezone", "UTC"),
                       ("display_name", "someone"), ("ota_channel", "beta")):
        assert forkexec._sysctl_handler("set_bootcfg", [key, value], {}) is True
        assert written[-1] == (key, value)
