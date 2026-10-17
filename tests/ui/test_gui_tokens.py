'''
 *
 *      test_gui_tokens.py
 *      The VortexGlass design tokens must stay legible over any wallpaper.
 *
 *      2026/10/16 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */

'''

from tools.checks import check_gui_tokens_contrast


# The GUI surfaces are glass over the wallpaper, so the same check the website
# tokens get has to run against the QML tokens: it measures every text-on-surface
# pair over both a pure white and a pure black backdrop.
def test_gui_tokens_meet_wcag_aa():
    assert check_gui_tokens_contrast.main() == 0


# 颜色只从 Theme 来。这三个文件收拢前散着约 20 个裸色值，这条是防止回潮的守卫：
# 一个新色值应当进 Theme，而不是就地写进 QML。
def test_surfaces_have_no_literal_colours():
    import re
    from pathlib import Path

    qml = Path(__file__).resolve().parents[2] / "src/vortexglass/qml"
    for name in ("Desktop.qml", "GlassBand.qml", "Backdrop.qml"):
        source = (qml / name).read_text(encoding="utf-8")
        literals = re.findall(r'"#[0-9a-fA-F]{6,8}"', source)
        assert not literals, f"{name} 里还有裸色值: {literals}"
