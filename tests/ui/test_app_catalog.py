'''
 *
 *      test_app_catalog.py
 *      The start menu catalog: unique ids, resolvable modules and real icons.
 *
 *      2026/10/16 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */

'''

import re
from pathlib import Path

import pytest

pytest.importorskip("PyQt6", reason="install requirements-gui.txt for compositor GUI tests")

from vortexglass import quick_backend

VORTEXGLASS = Path(quick_backend.__file__).resolve().parent
ICONS = VORTEXGLASS / "assets" / "icons"


# Ids are unique: the launcher looks entries up by id, so a duplicate would make
# one of them unreachable from the menu.
def test_ids_are_unique():
    ids = [entry["id"] for entry in quick_backend.APP_CATALOG]
    assert len(ids) == len(set(ids))


# Every entry names an icon that is really on disk; the menu renders an empty
# slot otherwise, and nothing else would catch a rename.
def test_every_entry_has_its_icon():
    for entry in quick_backend.APP_CATALOG:
        assert entry["icon"], entry["id"]
        assert (ICONS / f"{entry['icon']}.svg").is_file(), entry["id"]


# Each entry either names an apps/ module or is handled some other way, which is
# only true of the terminal: it owns a PTY rather than a window the app manages.
def test_modules_resolve_to_real_app_modules():
    apps = VORTEXGLASS.parent / "apps"
    for entry in quick_backend.APP_CATALOG:
        module = entry["module"]
        if module is None:
            assert entry["id"] == "terminal", entry["id"]
            continue
        assert (apps / f"{module}.py").is_file(), entry["id"]


# The icon colour is baked into each SVG because Qt cannot recolour an Image,
# while the contrast check reads the Theme token. This is what keeps the two from
# drifting apart silently: a hand-edit that bakes another colour fails here.
def test_icons_bake_the_theme_accent_colour():
    theme = (VORTEXGLASS / "qml" / "Theme.qml").read_text(encoding="utf-8")
    accent = re.search(r'readonly property color iconAccent:\s*"([^"]+)"',
                       theme).group(1)
    for entry in quick_backend.APP_CATALOG:
        svg = (ICONS / f"{entry['icon']}.svg").read_text(encoding="utf-8")
        assert accent in svg, f"{entry['icon']}.svg 未使用 Theme.iconAccent ({accent})"


# The catalog is what the QML delegate iterates, so every field the delegate
# reads has to be present or the menu renders a blank row.
def test_entries_carry_the_fields_the_delegate_reads():
    for entry in quick_backend.APP_CATALOG:
        assert set(entry) == {"id", "title", "description", "icon", "module"}
        assert entry["title"] and entry["description"]
