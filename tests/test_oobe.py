"""OOBE：触发判定、语言时区真实生效、向导脚本化跑通。"""
import io
import os
import sys

import oobe
import syslocale
import tui


def _ctx(tmp_path=None, persist_log=None):
    def persist(values):
        if persist_log is not None:
            persist_log.append(dict(values))
    return {"root_dir": str(tmp_path) if tmp_path else "/nonexistent",
            "username": "tester", "locked": True, "persist": persist}


def test_marker_triggers_oobe(tmp_path):
    assert oobe.should_run(str(tmp_path)) is True
    etc = tmp_path / "etc"
    etc.mkdir()
    (etc / ".oobe_done").write_text("x")
    assert oobe.should_run(str(tmp_path)) is False


def test_language_switch_is_real():
    assert syslocale.set_language("en") is True
    assert syslocale._("tui.cont") == "Continue"
    assert syslocale.set_language("zh_CN") is True
    assert syslocale._("tui.cont") == "继续"
    assert syslocale.set_language("xx") is False


def test_timezone_rejects_bogus_accepts_real():
    assert syslocale.set_timezone("Nope/Nowhere") is False
    assert syslocale.set_timezone("Asia/Shanghai") is True
    assert syslocale.get_timezone() == "Asia/Shanghai"
    assert syslocale.now_str("%Y-%m-%d")[:4].isdigit()


def test_tz_region_city_split():
    regions, zones = oobe._regions()
    assert "Asia" in regions
    cities = oobe._cities_of("Asia", zones)
    assert "Shanghai" in cities
    assert "UTC" in oobe._cities_of("Other", zones)


def _run_wizard(monkeypatch, answers):
    monkeypatch.setenv("PYSPOS_TUI", "line")
    inputs = iter(answers)
    monkeypatch.setattr("builtins.input", lambda _p="": next(inputs))
    syslocale.set_language("zh_CN")
    syslocale.set_timezone("Asia/Shanghai")
    log = []
    ok = oobe.run_wizard(_ctx(persist_log=log))
    return ok, log


def test_full_wizard_zh(monkeypatch, tmp_path):
    # 欢迎回车 → 语言选1中文 → 许可y → 地区回车(默认) → 城市回车 → 预览回车 →
    # 显示名回车 → root n → bl回车 → ota回车 → token回车 → 汇总y → 完成页回车
    ok, log = _run_wizard(monkeypatch, ["", "1", "y", "", "", "", "", "n",
                                       "", "", "", "y", ""])
    assert ok is True
    v = log[0]
    assert v["lang"] == "zh_CN" and v["root"] is False
    assert v["channel"] == "stable" and v["display_name"] == "tester"


def test_wizard_back_navigation(monkeypatch):
    # 欢迎页直接 < → 中止
    monkeypatch.setenv("PYSPOS_TUI", "line")
    monkeypatch.setattr("builtins.input", lambda _p="": "<")
    syslocale.set_language("zh_CN")
    assert oobe.run_wizard(_ctx()) is False


def test_wizard_abort_on_eof(monkeypatch):
    import pytest
    monkeypatch.setenv("PYSPOS_TUI", "line")

    def _eof(_p=""):
        raise EOFError
    monkeypatch.setattr("builtins.input", _eof)
    syslocale.set_language("zh_CN")
    with pytest.raises(tui.TUIAbort):
        oobe.run_wizard(_ctx())
    # maybe_run_oobe 负责兜底：中止不写标记、不崩启动
    assert oobe.maybe_run_oobe("/nonexistent-root-xyz") is False


def test_locale_command(tmp_path, monkeypatch):
    import main
    monkeypatch.chdir(tmp_path)
    # locale tz 会写真实 bootcfg.json：先备份，测完还原
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
