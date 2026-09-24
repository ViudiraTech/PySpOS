"""OTA 临时禁用：零网络请求、降级字段完整、本地能力不受影响。"""
import sys
import time

sys.path.insert(0, "src")
import ota
import pyspos


def test_switch_is_off():
    assert pyspos.OTA_ENABLED is False


def test_cloud_check_returns_disabled_without_network():
    t0 = time.time()
    info = ota.check_cloud_update()
    dt = time.time() - t0
    assert dt < 5.0, "禁用状态下不应发起网络请求"
    assert info["has_update"] is False
    assert info.get("disabled") is True
    assert info.get("reason")


def test_cloud_download_refused():
    assert ota.download_and_install_update() is False
    assert ota.fetch_remote_version() is None
    assert ota.is_ota_enabled() is False


def test_local_status_still_works():
    st = ota.get_ota_status()
    assert st.get("ota_enabled") is False
    assert "current_version" in st
