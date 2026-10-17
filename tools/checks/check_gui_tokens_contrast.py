'''
 *
 *      check_gui_tokens_contrast.py
 *      WCAG 2.2 AA contrast check for the VortexGlass QML design tokens.
 *
 *      2026/10/16 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# The colour maths is shared with the docs checker so the two cannot drift.
from check_tokens_contrast import composite, ratio  # noqa: E402

THEME = Path(__file__).resolve().parents[2] / 'src/vortexglass/qml/Theme.qml'

# QML writes an 8-digit colour as #AARRGGBB, the reverse of CSS, so the docs
# parser cannot be reused here.
def qml_color(value):
    h = value.lstrip('#')
    if len(h) == 6:
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
        return (r, g, b, 1.0)
    if len(h) == 8:
        a, r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4, 6))
        return (r, g, b, a / 255)
    raise ValueError(f'不是可识别的 QML 颜色: {value}')


# Read the colour tokens out of the QML singleton.
def load_colors(path):
    source = path.read_text(encoding='utf-8')
    found = {}
    for name, value in re.findall(
            r'readonly property color (\w+):\s*"([^"]+)"', source):
        found[name] = qml_color(value)
    return found


# Every GUI surface is glass over the wallpaper, and the wallpaper is arbitrary,
# so each translucent surface is measured twice: over pure white and over pure
# black. Only the worse of the two counts.
EXTREMES = {'白壁纸': (255, 255, 255, 1.0), '黑壁纸': (0, 0, 0, 1.0)}


# Flatten one layer onto what is already there; an opaque layer ignores it.
def over(color, backdrop):
    return color if color[3] >= 1.0 else composite(color, backdrop)


# How a surface looks from the outside. A bare token name is one layer over the
# backdrop; a tuple stacks outermost-first, which is what the tray chips need
# (chip over taskbar over wallpaper) — measuring a chip straight against the
# wallpaper would punish it twice for translucency it does not have.
def surface(spec, backdrop, colors):
    if isinstance(spec, tuple):
        result = backdrop
        for token in reversed(spec):
            result = over(colors[token], result)
        return result
    return over(colors[spec], backdrop)


# Measure every text-on-surface pair that has a contrast floor.
def main():
    colors = load_colors(THEME)

    def c(name):
        if name not in colors:
            raise KeyError(f'Theme.qml 缺少颜色 token: {name}')
        return colors[name]

    # label, foreground token, surface token, WCAG floor
    rows = [
        ('任务栏文字 / 任务栏底', 'textOnChrome', 'taskbarBackground', 4.5),
        ('窗口按钮 / 未聚焦底', 'textOnChrome', 'windowButton', 4.5),
        ('窗口按钮 / 聚焦底', 'textOnChrome', 'windowButtonFocused', 4.5),
        ('开始按钮 / 常态底', 'textOnChrome', 'controlBackground', 4.5),
        ('开始按钮 / 展开底', 'textOnChrome', 'controlBackgroundActive', 4.5),
        ('退出按钮 / 危险底', 'textOnChrome', 'dangerBackground', 4.5),
        ('菜单标题 / 菜单底', 'textPrimary', 'menuBackground', 4.5),
        ('菜单次要文字 / 菜单底', 'textSecondary', 'menuBackground', 4.5),
        ('占位符 / 输入框底', 'textPlaceholder', 'fieldBackground', 4.5),
        ('应用项文字 / 悬停底', 'textPrimary', 'rowHover', 4.5),
        ('署名文字 / 署名底衬', 'textOnChrome', 'taskbarBackground', 4.5),
        ('时钟日期 / 任务栏底', 'trayText', 'taskbarBackground', 4.5),
        ('托盘槽位标记 / 标记底', 'traySlot', ('trayChipBackground', 'taskbarBackground'), 4.5),
        ('托盘锁定标记 / 标记底', 'trayLocked', ('trayChipBackground', 'taskbarBackground'), 4.5),
        ('托盘解锁标记 / 标记底', 'trayUnlocked', ('trayChipBackground', 'taskbarBackground'), 4.5),
        ('托盘 ROOT 标记 / 标记底', 'trayRoot', ('trayChipBackground', 'taskbarBackground'), 4.5),
        # Icon glyphs are graphics, not text: WCAG 1.4.11 asks for 3:1.
        ('应用图标 / 菜单底', 'iconAccent', 'menuBackground', 3.0),
    ]

    print(f"{'检查项':30} {'白壁纸':>9} {'黑壁纸':>9}  判定")
    print('-' * 62)
    bad = []
    for label, fg_tok, surf_spec, need in rows:
        values = {}
        for extreme, backdrop in EXTREMES.items():
            bg = surface(surf_spec, backdrop, colors)
            values[extreme] = ratio(over(c(fg_tok), bg), bg)
        ok = all(v >= need for v in values.values())
        cells = '  '.join(f'{values[e]:5.2f}:1' for e in EXTREMES)
        print(f"{label:30} {cells}  {'OK' if ok else 'FAIL'} (需 {need})")
        if not ok:
            bad.append(label)

    # The desktop watermark is a brand mark, which WCAG 1.4.3 exempts from any
    # contrast floor. It is reported so the number stays visible, not enforced.
    wm = c('wallpaperTitle')
    worst = min(ratio(wm, b) for b in EXTREMES.values())
    print(f"\n（参考，不作判定）桌面水印 / 壁纸: 最差 {worst:.2f}:1"
          " —— 品牌标记，WCAG 1.4.3 豁免")

    print('\n结论:', '全部达标（WCAG AA）' if not bad else f'{len(bad)} 项不达标: {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
