'''
 *
 *      test_tray.py
 *      Taskbar tray: the boot-fixed chips, the ROOT marker and the clock source.
 *
 *      2026/10/16 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */

'''

import pytest

pytest.importorskip("PyQt6", reason="install requirements-gui.txt for compositor GUI tests")

from vortexglass import quick_backend


# Every chip carries the two fields the QML delegate switches on, and its tone is
# one the delegate knows how to colour.
def test_tray_chips_have_the_shape_the_delegate_expects():
    chips = quick_backend.boot_chips() + quick_backend.root_chips()
    assert chips, "至少应该有一个标记"
    for chip in chips:
        assert set(chip) == {"text", "tone"}
        assert chip["text"]
        assert chip["tone"] in {"slot", "locked", "unlocked", "root"}


# The slot chip names the active slot and the trust chip matches the boot lock
# state, so the tray cannot drift from what the OS actually booted.
def test_tray_chips_report_real_boot_state():
    import main
    import ota

    tones = {chip["tone"]: chip["text"] for chip in quick_backend.boot_chips()}
    assert tones["slot"] == ota.get_current_slot().replace("slot_", "").upper()
    assert tones["locked" if main.boot_locked else "unlocked"] in ("LOCKED", "UNLOCKED")


# The ROOT marker follows main's state; the shell already shows the same signal
# as a `#` prompt, so the check pins the shared convention too.
def test_root_marker_follows_main(monkeypatch):
    import main

    monkeypatch.setattr(main, "is_root", lambda: False)
    assert quick_backend.root_chips() == []
    monkeypatch.setattr(main, "is_root", lambda: True)
    assert quick_backend.root_chips() == [{"text": "#", "tone": "root"}]


# The clock must read the OS's configured timezone rather than the host's. It
# delegates to syslocale, which is the only module that applies `locale tz`; a
# plain datetime.now() would silently show host time instead.
def test_tray_clock_delegates_to_the_system_locale(monkeypatch):
    import syslocale

    monkeypatch.setattr(syslocale, "now_str",
                        lambda fmt="%H:%M:%S": f"<{fmt}>")
    assert quick_backend.clock_text() == ("<%H:%M>", "<%Y/%m/%d>")
