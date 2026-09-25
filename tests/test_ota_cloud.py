"""云端 OTA（已恢复）：版本列表、地址归一化、指定槽位安装门控。

全部用桩，不发任何网络请求。服务器地址断言在
test_ota_server_host 里，防止切回旧域名。
"""
import sys

import pytest

sys.path.insert(0, "src")
import ota
import pyspos


FAKE_REMOTE = {
    "version": "3.2.0",
    "release_date": "2026-09-24",
    "develop_stage": "rc",
    "download_url": "PySpOS-3.2.0-20260924.zip",
    "sha256": "x" * 64,
    "file_size": 251027,
    "release_notes": "notes",
    "changelog": [
        {"version": "3.2.0", "date": "2026-09-24", "type": "rc",
         "download_url": "PySpOS-3.2.0-20260924.zip",
         "sha256": "x" * 64, "file_size": 251027,
         "changes": ["a", "b"]},
        {"version": "3.1.0", "date": "2026-03-15", "type": "release",
         "download_url": "https://cdn.example.invalid/PySpOS-3.1.0.zip",
         "sha256": None, "file_size": 167000,
         "changes": ["c"]},
    ],
}


def test_switch_is_on():
    assert pyspos.OTA_ENABLED is True


def test_ota_server_host():
    assert ota.OTA_SERVER_URL == "https://goutoustdio.rainyland.top/ota/"
    assert "pyspos.us.ci" not in ota.OTA_SERVER_URL


def test_resolve_download_url():
    assert ota.resolve_download_url("") \
        == "https://goutoustdio.rainyland.top/ota/PySpOS.zip"
    assert ota.resolve_download_url("PySpOS-3.2.0-20260924.zip") \
        == "https://goutoustdio.rainyland.top/ota/PySpOS-3.2.0-20260924.zip"
    abs_url = "https://cdn.example.invalid/x.zip"
    assert ota.resolve_download_url(abs_url) == abs_url


def test_list_cloud_versions(monkeypatch):
    monkeypatch.setattr(ota, "fetch_remote_version", lambda: dict(FAKE_REMOTE))
    entries = ota.list_cloud_versions()
    assert [e["version"] for e in entries] == ["3.2.0", "3.1.0"]
    assert entries[0]["download_url"] == \
        "https://goutoustdio.rainyland.top/ota/PySpOS-3.2.0-20260924.zip"
    assert entries[1]["download_url"] == "https://cdn.example.invalid/PySpOS-3.1.0.zip"
    assert entries[0]["notes"] == ["a", "b"]


def test_list_cloud_versions_fallback_single(monkeypatch):
    data = dict(FAKE_REMOTE)
    data.pop("changelog")
    monkeypatch.setattr(ota, "fetch_remote_version", lambda: data)
    entries = ota.list_cloud_versions()
    assert len(entries) == 1 and entries[0]["version"] == "3.2.0"


def test_list_empty_when_disabled(monkeypatch):
    monkeypatch.setattr(pyspos, "OTA_ENABLED", False)
    assert ota.list_cloud_versions() == []
    assert ota.download_and_install_version({"download_url": "x"}, "slot_a") is False


def test_install_to_slot_rejects_bad_slot(tmp_path):
    with pytest.raises(ValueError):
        ota.install_package_to_slot(str(tmp_path / "u.zip"), "slot_c")


def test_install_to_slot_missing_package():
    assert ota.install_package_to_slot("/nonexistent/u.zip", "slot_a") is False
