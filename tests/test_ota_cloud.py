'''
 *
 *      test_ota_cloud.py
 *      Cloud OTA, all stubbed: version list, URL normalization and per-slot install gating.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

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


# Cloud OTA has to stay enabled; this switch gates the whole feature.
def test_switch_is_on():
    assert pyspos.OTA_ENABLED is True


# The OTA host is the current domain and not the retired one.
def test_ota_server_host():
    assert ota.OTA_SERVER_URL == "https://goutoustdio.rainyland.top/ota/"
    assert "pyspos.us.ci" not in ota.OTA_SERVER_URL


# A bare filename resolves under the OTA base URL, and an absolute URL passes through untouched.
def test_resolve_download_url():
    assert ota.resolve_download_url("") \
        == "https://goutoustdio.rainyland.top/ota/PySpOS.zip"
    assert ota.resolve_download_url("PySpOS-3.2.0-20260924.zip") \
        == "https://goutoustdio.rainyland.top/ota/PySpOS-3.2.0-20260924.zip"
    abs_url = "https://cdn.example.invalid/x.zip"
    assert ota.resolve_download_url(abs_url) == abs_url


# The changelog becomes a newest-first list whose relative names are expanded to absolute URLs and keep their per-version notes.
def test_list_cloud_versions(monkeypatch):
    monkeypatch.setattr(ota, "fetch_remote_version", lambda: dict(FAKE_REMOTE))
    entries = ota.list_cloud_versions()
    assert [e["version"] for e in entries] == ["3.2.0", "3.1.0"]
    assert entries[0]["download_url"] == \
        "https://goutoustdio.rainyland.top/ota/PySpOS-3.2.0-20260924.zip"
    assert entries[1]["download_url"] == "https://cdn.example.invalid/PySpOS-3.1.0.zip"
    assert entries[0]["notes"] == ["a", "b"]


# With no changelog the current version alone becomes the only entry.
def test_list_cloud_versions_fallback_single(monkeypatch):
    data = dict(FAKE_REMOTE)
    data.pop("changelog")
    monkeypatch.setattr(ota, "fetch_remote_version", lambda: data)
    entries = ota.list_cloud_versions()
    assert len(entries) == 1 and entries[0]["version"] == "3.2.0"


# Disabling OTA yields an empty list and refuses to download, without touching the network.
def test_list_empty_when_disabled(monkeypatch):
    monkeypatch.setattr(pyspos, "OTA_ENABLED", False)
    assert ota.list_cloud_versions() == []
    assert ota.download_and_install_version({"download_url": "x"}, "slot_a") is False


# An unknown slot name is a caller bug and must raise rather than write anywhere.
def test_install_to_slot_rejects_bad_slot(tmp_path):
    with pytest.raises(ValueError):
        ota.install_package_to_slot(str(tmp_path / "u.zip"), "slot_c")


# A package that is not there fails softly with False instead of raising.
def test_install_to_slot_missing_package():
    assert ota.install_package_to_slot("/nonexistent/u.zip", "slot_a") is False


# Unpacking must not land the build machine's boot-time state files, while normal files still extract.
def test_safe_extract_skips_boot_state(tmp_path):
    import zipfile
    pkg = tmp_path / "u.zip"
    with zipfile.ZipFile(pkg, "w") as archive:
        archive.writestr("src/main.py", "x\n")
        archive.writestr("src/current_slot", "slot_a\n")
        archive.writestr(".hotreset", "x\n")
    target = tmp_path / "out"
    target.mkdir()
    assert ota._safe_extract_package(str(pkg), str(target)) is True
    assert (target / "main.py").is_file()
    assert not (target / "current_slot").exists()
    assert not (target / ".hotreset").exists()
    assert not (target / "src" / "current_slot").exists()


# On the build side the same state files must never be packed, or the build itself fails.
def test_builder_excludes_boot_state():
    import build_update
    for bad in ("src/current_slot", "src/.hotreset",
                "current_slot", ".hotreset"):
        assert build_update._should_include(bad) is False
        assert build_update._is_boot_state_member(bad) is True
    assert build_update._should_include("src/main.py") is True
