'''
 *
 *      test_glass.py
 *      Blur tiers stay inside their artifact bounds, and the dither is a dither.
 *
 *      2026/10/16 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */

'''

import re
from pathlib import Path

import pngcodec

QML = Path(__file__).resolve().parents[2] / "src/vortexglass/qml"
ASSETS = Path(__file__).resolve().parents[2] / "src/vortexglass/assets"


# 从单例里读档位表。Theme.qml 是 QML 不是 Python，只能这样读——同一招对比度
# 检查器也在用。
def _tiers():
    source = (QML / "Theme.qml").read_text(encoding="utf-8")
    block = re.search(r"readonly property var blurTiers:\s*\[(.*?)\]", source, re.S)
    assert block, "Theme.qml 里没有 blurTiers"
    tiers = []
    for item in re.finditer(r"\{(.*?)\}", block.group(1), re.S):
        fields = dict(re.findall(r"(\w+):\s*([\d.]+)", item.group(1)))
        tiers.append({k: float(v) for k, v in fields.items()})
    return tiers


# 每档的采样外扩必须盖得住纹理半径，否则双线性插值会取到玻璃带以外的像素，
# 边缘出现一圈被拉进来的画面——这正是 KWin 用 expandSize 守的那条边界。
def test_every_tier_expands_at_least_its_texture_radius():
    tiers = _tiers()
    assert tiers, "至少要有一档"
    for tier in tiers:
        texture_radius = tier["screenRadius"] * tier["scale"]
        assert tier["expand"] >= texture_radius, tier


# 降采样省像素，半径按比例补回，屏幕上的模糊强度才不变——这是这套档位存在的
# 理由，所以所有档的屏幕半径应当一致。
def test_tiers_agree_on_the_on_screen_radius():
    radii = {tier["screenRadius"] for tier in _tiers()}
    assert len(radii) == 1, radii


# 档位比例只能是 (0, 1]：大于 1 是放大采样，没有意义。
def test_tier_scales_are_ratios():
    for tier in _tiers():
        assert 0 < tier["scale"] <= 1.0, tier


# 半分辨率档真的省一半采样。
def test_one_tier_halves_the_sampling():
    scales = sorted(tier["scale"] for tier in _tiers())
    assert scales[0] == 0.5, scales


# 调用方按面积选档，而不是散落的魔数比较。
def test_desktop_selects_a_tier_instead_of_comparing_pixels():
    source = (QML / "Desktop.qml").read_text(encoding="utf-8")
    assert "blurTierFor(" in source
    assert "> 500000" not in source, "像素阈值应该留在 Theme.blurDownsampleArea 一处"


# 噪声图的幅度：它要小到看不出来，又大到足以打散 8 位量化台阶。把这条换算写
# 成断言，改图的人就会知道自己在动什么。
def test_noise_tile_is_a_dither_not_a_texture():
    image = pngcodec.read_png(str(ASSETS / "noise.png"))
    assert image.width == image.height == 64, "平铺图不必大，随机数本身无结构"
    alphas = set(image.pixels[3::4])
    assert len(alphas) == 1, f"alpha 应当处处相同，否则噪声有明暗结构: {alphas}"
    alpha = alphas.pop()
    greys = sorted({image.pixels[i] for i in range(0, len(image.pixels), 4)})
    assert len(greys) > 32, "灰度要够散才有抖动效果"
    # 合成后每通道被推开的幅度 = 偏离中灰多少 × alpha。
    shift = max(abs(greys[0] - 128), abs(greys[-1] - 128)) * alpha / 255
    assert 1.0 <= shift <= 6.0, f"幅度 {shift:.1f}/255 不在肉眼该看不见的区间"


# 噪声叠在折射之上，两者各有自己的 objectName，复核工具靠它们取源。
def test_glass_band_layers_refraction_and_noise():
    source = (QML / "GlassBand.qml").read_text(encoding="utf-8")
    assert '"glass-refraction"' in source and '"glass-noise"' in source
    assert "noise.png" in source
