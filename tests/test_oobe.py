'''
 *
 *      test_oobe.py
 *      OOBE: the trigger marker, real language and timezone effects, scripted wizard runs.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import io
import os
import sys

import oobe
import syslocale
import tui


# Build a wizard context whose persist() calls land in a list instead of on disk.
def _ctx(tmp_path=None, persist_log=None):
# Record the wizard's final settings rather than writing them anywhere.
    def persist(values):
        if persist_log is not None:
            persist_log.append(dict(values))
    return {"root_dir": str(tmp_path) if tmp_path else "/nonexistent",
            "username": "tester", "locked": True, "persist": persist}


# OOBE runs until the .oobe_done marker exists, and never runs again afterwards.
def test_marker_triggers_oobe(tmp_path):
    assert oobe.should_run(str(tmp_path)) is True
    etc = tmp_path / "etc"
    etc.mkdir()
    (etc / ".oobe_done").write_text("x")
    assert oobe.should_run(str(tmp_path)) is False


# Switching the language really changes translated strings, while an unknown code is refused.
def test_language_switch_is_real():
    assert syslocale.set_language("en") is True
    assert syslocale._("tui.cont") == "Continue"
    assert syslocale.set_language("zh_CN") is True
    assert syslocale._("tui.cont") == "继续"
    assert syslocale.set_language("xx") is False


# A bogus zone is rejected, a real one sticks, and the clock formats in it.
def test_timezone_rejects_bogus_accepts_real():
    assert syslocale.set_timezone("Nope/Nowhere") is False
    assert syslocale.set_timezone("Asia/Shanghai") is True
    assert syslocale.get_timezone() == "Asia/Shanghai"
    assert syslocale.now_str("%Y-%m-%d")[:4].isdigit()


# The zone database splits into regions and per-region cities, with a fallback for an unknown region.
def test_tz_region_city_split():
    regions, zones = oobe._regions()
    assert "Asia" in regions
    cities = oobe._cities_of("Asia", zones)
    assert "Shanghai" in cities
    assert "UTC" in oobe._cities_of("Other", zones)


# Drive the whole wizard through the line backend with a scripted answer sequence, forcing Chinese and a known timezone first.
def _run_wizard(monkeypatch, answers):
    monkeypatch.setenv("PYSPOS_TUI", "line")
    inputs = iter(answers)
    monkeypatch.setattr("builtins.input", lambda _p="": next(inputs))
    syslocale.set_language("zh_CN")
    syslocale.set_timezone("Asia/Shanghai")
    log = []
    ok = oobe.run_wizard(_ctx(persist_log=log))
    return ok, log


# A full Chinese run persists the chosen language, no ROOT, the stable channel and the default display name.
def test_full_wizard_zh(monkeypatch, tmp_path):
    # welcome Enter -> language 1 for Chinese -> licence y -> region Enter (default) -> city Enter -> preview Enter ->
    # display name Enter -> root n -> bl Enter -> ota Enter -> token Enter -> summary y -> done page Enter
    ok, log = _run_wizard(monkeypatch, ["", "1", "y", "", "", "", "", "n",
                                       "", "", "", "y", ""])
    assert ok is True
    v = log[0]
    assert v["lang"] == "zh_CN" and v["root"] is False
    assert v["channel"] == "stable" and v["display_name"] == "tester"


# Pressing back on the first page aborts the wizard instead of leaving a half-configured device.
def test_wizard_back_navigation(monkeypatch):
    # Pressing back on the welcome page aborts
    monkeypatch.setenv("PYSPOS_TUI", "line")
    monkeypatch.setattr("builtins.input", lambda _p="": "<")
    syslocale.set_language("zh_CN")
    assert oobe.run_wizard(_ctx()) is False


# EOF aborts through TUIAbort and maybe_run_oobe absorbs it, so a non-interactive boot still starts.
def test_wizard_abort_on_eof(monkeypatch):
    import pytest
    monkeypatch.setenv("PYSPOS_TUI", "line")

# input() stand-in reporting a closed stdin.
    def _eof(_p=""):
        raise EOFError
    monkeypatch.setattr("builtins.input", _eof)
    syslocale.set_language("zh_CN")
    with pytest.raises(tui.TUIAbort):
        oobe.run_wizard(_ctx())
    # maybe_run_oobe is the backstop: an abort writes no marker and does not break boot
    assert oobe.maybe_run_oobe("/nonexistent-root-xyz") is False


# locale tz persists a real zone and locale shows it back; the real bootcfg is restored afterwards.
def test_locale_command(tmp_path, monkeypatch):
    import main
    monkeypatch.chdir(tmp_path)
    # locale tz writes the real bootcfg.json: back it up first and restore it afterwards
    import btcfg
    cfg_path = btcfg.boot_config
    backup = None
    if os.path.isfile(cfg_path):
        with open(cfg_path, "rb") as f:
            backup = f.read()
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        main.handle_command("locale tz Asia/Tokyo")
        out1 = buf.getvalue()
        buf.truncate(0)
        buf.seek(0)
        main.handle_command("locale")
        out2 = buf.getvalue()
    finally:
        sys.stdout = old
        if backup is not None:
            with open(cfg_path, "wb") as f:
                f.write(backup)
    assert "Asia/Tokyo" in out1 + out2
    syslocale.set_timezone("Asia/Shanghai")
    syslocale.set_language("zh_CN")
