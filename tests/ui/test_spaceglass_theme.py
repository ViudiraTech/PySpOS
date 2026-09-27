'''
 *
 *      test_spaceglass_theme.py
 *      VortexGlass theme inventory, window geometry and strip painting.
 *
 *      The window frame is painted here rather than by Tk, because Tk 8.6 drops
 *      the alpha channel whenever an image is resized. These checks pin the two
 *      things that would silently break the look: the inventory of the 34 theme
 *      files, and the rule that a strip keeps native caps and fills its middle
 *      with one flat colour taken from the middle of the source.
 *
 *      2026/9/27 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import os
from pathlib import Path

import pytest

import pngcodec
import spaceglass_theme as theme

# The stock VortexGlass theme that ships with Uinxed, used when it is present.
STOCK_DIR = "/home/jitianyu/桌面/Uinxed-Kernel/user/assets/themes/vortexglass"

# Build a synthetic RGBA image from a pixel callback.
def make_image(width, height, pixel):
    data = bytearray()
    for y in range(height):
        for x in range(width):
            data += bytes(pixel(x, y))
    return pngcodec.RgbaImage(width, height, bytes(data))


def test_inventory_lists_every_stock_file_once():
    names = [asset.name for asset in theme.REQUIRED_ASSETS]
    assert len(names) == 34
    assert len(set(names)) == 34
    assert "top.png" in names and "reflection.png" in names
    assert set(theme.ORB_STATES) <= set(names)


def test_button_series_and_title_buttons_cover_existing_files():
    for kind, series in theme.BUTTON_SERIES.items():
        assert len(series) == 4, kind
        for name in series:
            assert name in [asset.name for asset in theme.REQUIRED_ASSETS]
    for kind, states in theme.TITLE_BUTTONS.items():
        for name in states.values():
            assert name in [asset.name for asset in theme.REQUIRED_ASSETS]


def test_candidate_dirs_put_the_override_before_the_fallbacks(monkeypatch):
    monkeypatch.setenv(theme.ENV_THEME_DIR, "/from/env")
    candidates = theme.candidate_theme_dirs()
    assert candidates[0] == "/from/env"
    # The system tree is searched next, so an installed theme wins over the
    # host-wide location, and the variable still wins over both.
    assert candidates[1] == os.path.join(str(theme.system_root()),
                                          theme.THEME_SUBDIR)
    assert list(theme.FALLBACK_THEME_DIRS) == candidates[2:]


def test_an_explicit_path_replaces_every_other_candidate(monkeypatch):
    monkeypatch.setenv(theme.ENV_THEME_DIR, "/from/env")
    assert theme.candidate_theme_dirs("/explicit") == ["/explicit"]


def test_system_root_is_the_parent_of_the_working_directory():
    # An app runs from apps/, so the tree that holds assets/ is one level up.
    assert theme.system_root() == Path(os.getcwd()).resolve().parent


def test_looks_like_theme_needs_every_file(tmp_path):
    assert theme.looks_like_theme(STOCK_DIR) is True
    empty = tmp_path / "vortexglass"
    empty.mkdir()
    assert theme.looks_like_theme(str(empty)) is False
    for asset in theme.REQUIRED_ASSETS:
        (empty / asset.name).write_bytes(b"")
    assert theme.looks_like_theme(str(empty)) is True
    (empty / "orb_0.png").unlink()
    assert theme.looks_like_theme(str(empty)) is False


def test_discovery_finds_a_theme_in_a_nested_tree(tmp_path, monkeypatch):
    root = tmp_path / "checkout"
    target = root / "user" / "assets" / "themes" / "vortexglass"
    target.mkdir(parents=True)
    for asset in theme.REQUIRED_ASSETS:
        (target / asset.name).write_bytes(b"")
    monkeypatch.setattr(theme, "search_roots", lambda: [str(root)])
    assert theme.discover_theme_dir() == os.path.abspath(str(target))


def test_discovery_skips_a_partial_theme_and_keeps_looking(tmp_path,
                                                            monkeypatch):
    root = tmp_path / "checkout"
    broken = root / "assets" / "themes" / "vortexglass"
    broken.mkdir(parents=True)
    (broken / "top.png").write_bytes(b"")
    good = root / "share" / "themes" / "vortexglass"
    good.mkdir(parents=True)
    for asset in theme.REQUIRED_ASSETS:
        (good / asset.name).write_bytes(b"")
    monkeypatch.setattr(theme, "search_roots", lambda: [str(root)])
    # A half-copied theme must not win over a complete one further down.
    assert theme.discover_theme_dir() == os.path.abspath(str(good))


def test_discovery_prunes_hidden_and_vendor_directories(tmp_path, monkeypatch):
    root = tmp_path / "checkout"
    for skip in sorted(theme.SKIP_DIR_NAMES):
        hidden = root / skip / "themes" / "vortexglass"
        hidden.mkdir(parents=True)
        for asset in theme.REQUIRED_ASSETS:
            (hidden / asset.name).write_bytes(b"")
    monkeypatch.setattr(theme, "search_roots", lambda: [str(root)])
    assert theme.discover_theme_dir() is None


def test_find_theme_dir_falls_back_to_the_search(tmp_path, monkeypatch):
    root = tmp_path / "checkout"
    target = root / "themes" / "vortexglass"
    target.mkdir(parents=True)
    for asset in theme.REQUIRED_ASSETS:
        (target / asset.name).write_bytes(b"")
    monkeypatch.delenv(theme.ENV_THEME_DIR, raising=False)
    monkeypatch.setattr(theme, "candidate_theme_dirs", lambda explicit=None: [])
    monkeypatch.setattr(theme, "search_roots", lambda: [str(root)])
    assert theme.find_theme_dir() == os.path.abspath(str(target))


def test_find_theme_dir_reports_the_roots_it_searched(tmp_path, monkeypatch):
    monkeypatch.delenv(theme.ENV_THEME_DIR, raising=False)
    monkeypatch.setattr(theme, "candidate_theme_dirs", lambda explicit=None: [])
    monkeypatch.setattr(theme, "search_roots", lambda: [str(tmp_path)])
    with pytest.raises(FileNotFoundError) as excinfo:
        theme.find_theme_dir()
    assert str(tmp_path) in str(excinfo.value)


def test_an_explicit_directory_is_never_replaced_by_a_search(tmp_path,
                                                             monkeypatch):
    # Naming a directory is a decision. If it has no theme, say so instead of
    # quietly loading the perfectly good copy the variable points at.
    good = tmp_path / "good"
    good.mkdir()
    for asset in theme.REQUIRED_ASSETS:
        (good / asset.name).write_bytes(b"")
    monkeypatch.setenv(theme.ENV_THEME_DIR, str(good))
    with pytest.raises(FileNotFoundError):
        theme.find_theme_dir(str(tmp_path / "empty"))
    # Without an explicit path the same variable is still honoured.
    assert theme.find_theme_dir() == os.path.abspath(str(good))


def test_load_theme_reports_missing_and_mismatched(tmp_path):
    (tmp_path / "top.png").write_bytes(b"")
    report = theme.load_theme(str(tmp_path))
    assert report["missing"], "a truncated theme must not look complete"
    assert "bottom.png" in report["missing"]
    assert theme.theme_complete(report) is False


@pytest.mark.skipif(not os.path.isdir(STOCK_DIR),
                    reason="stock VortexGlass theme is not installed")
def test_stock_theme_is_complete_and_matches_the_inventory():
    report = theme.load_theme(STOCK_DIR)
    assert report["mismatched"] == []
    assert report["missing"] == []
    assert len(report["images"]) == 34
    for asset in theme.REQUIRED_ASSETS:
        info = theme.read_png_info(report["images"][asset.name])
        assert (info.width, info.height, info.color) == (asset.width,
                                                         asset.height,
                                                         asset.color)


def test_title_buttons_sit_left_of_the_frame_edge():
    buttons = theme.title_geometry(100, 0, 400)["buttons"]
    frame_right = 100 + 400 + theme.SIDE_INSET
    assert buttons["close"][0] + buttons["close"][2] == frame_right - 4
    assert buttons["max"][0] + buttons["max"][2] == buttons["close"][0]
    assert buttons["min"][0] + buttons["min"][2] == buttons["max"][0]
    with pytest.raises(ValueError):
        theme.title_button_rect("nope", 0, 0, 100)


def test_title_text_reserves_room_for_the_caption_buttons():
    text = theme.title_geometry(100, 0, 400)["text"]
    buttons = theme.title_geometry(100, 0, 400)["buttons"]
    assert text[0] == 100 + theme.TITLE_LEFT
    assert text[0] + text[2] <= buttons["min"][0]


def test_frame_geometry_puts_the_title_above_the_client():
    layout = theme.WindowLayout(theme.SIDE_INSET, theme.TITLEBAR_HEIGHT, 640, 480)
    frame = layout.frame()
    client = frame["client"]
    strip = frame["title"]["strip"]
    assert strip[1] + strip[3] <= client[1]
    assert strip[0] == 0
    assert frame["left"][1] < client[1], "the side band overlaps the title"
    assert frame["bottom"][1] == client[1] + client[3]
    assert frame["bottom"][0] == 0


def test_hit_testing_finds_buttons_and_the_drag_strip():
    layout = theme.WindowLayout(theme.SIDE_INSET, theme.TITLEBAR_HEIGHT, 640, 480)
    frame = layout.frame()["title"]
    close = frame["buttons"]["close"]
    assert layout.hit_button(close[0] + 1, close[1] + 1) == "close"
    assert layout.hit_button(frame["strip"][0] + 4, 2) is None
    assert layout.hit_title(200, 4) is True
    assert layout.hit_title(200, theme.TITLEBAR_HEIGHT + 40) is False


def test_layout_rejects_a_degenerate_client():
    with pytest.raises(ValueError):
        theme.WindowLayout(0, 0, 0, 100)
    with pytest.raises(ValueError):
        theme.WindowLayout(0, 0, 100, -1)


def test_horizontal_strip_keeps_native_caps_and_flattens_the_middle():
    # Red on the caps, green in the middle column, transparent centre row.
    source = make_image(120, 4, lambda x, y: (255, 0, 0, 255) if x < 50 or x >= 70
                        else (0, 255, 0, 255))
    background = (0, 0, 0)
    strip = theme.build_horizontal_strip(source, 400, 4, background)
    assert (strip.width, strip.height) == (400, 4)
    corner = theme.FRAME_CORNER
    # The cap is the artwork, untouched, at the left edge.
    assert strip.pixel(0, 0) == bytes([255, 0, 0, 255])
    assert strip.pixel(corner - 1, 0) == bytes([255, 0, 0, 255])
    # The middle is one flat colour per row, sampled from the source centre.
    assert strip.pixel(corner, 0) == bytes([0, 255, 0, 255])
    assert strip.pixel(399 - corner, 0) == bytes([0, 255, 0, 255])
    assert strip.pixel(200, 3) == bytes([0, 255, 0, 255])


def test_horizontal_strip_leaves_a_fully_transparent_middle_alone():
    source = make_image(120, 2, lambda x, y: (255, 0, 0, 255) if x < 50 or x >= 70
                        else (0, 0, 0, 0))
    strip = theme.build_horizontal_strip(source, 300, 2, (9, 9, 9))
    corner = theme.FRAME_CORNER
    # A zero alpha pixel is skipped, so the backdrop shows through untouched.
    assert strip.pixel(corner + 5, 0) == bytes([9, 9, 9, 255])
    assert strip.pixel(0, 0) == bytes([255, 0, 0, 255])


def test_caps_are_composited_over_the_backdrop_not_copied_verbatim():
    # Tk 8.6 photo images cannot carry alpha, so a transparent cap pixel must
    # already be blended here. Copying the raw RGBA would hand Tk the stored
    # colour of a fully transparent pixel and paint a black square instead of
    # a rounded glass corner.
    source = make_image(120, 2, lambda x, y: (0, 0, 0, 0))
    strip = theme.build_horizontal_strip(source, 300, 2, (12, 34, 56))
    assert strip.pixel(0, 0) == bytes([12, 34, 56, 255])
    assert strip.pixel(299, 1) == bytes([12, 34, 56, 255])
    border = theme.build_vertical_border(source, 100, (12, 34, 56))
    assert border.pixel(0, 0) == bytes([12, 34, 56, 255])
    row = theme.build_title_extra_row(source, 300, (12, 34, 56))
    assert row.pixel(0, 0) == bytes([12, 34, 56, 255])
    # A half-transparent pixel lands halfway between art and backdrop.
    half = make_image(120, 1, lambda x, y: (132, 132, 132, 128))
    blended = theme.build_horizontal_strip(half, 300, 1, (0, 0, 0))
    assert 64 <= blended.pixel(200, 0)[0] <= 67


def test_horizontal_strip_splits_in_half_when_it_is_narrower_than_two_corners():
    source = make_image(120, 2, lambda x, y: (10, 20, 30, 255))
    strip = theme.build_horizontal_strip(source, 60, 2, (0, 0, 0))
    assert (strip.width, strip.height) == (60, 2)
    assert strip.pixel(0, 0) == bytes([10, 20, 30, 255])
    assert strip.pixel(59, 1) == bytes([10, 20, 30, 255])


def test_vertical_border_repeats_the_middle_row_between_two_caps():
    def pixel(x, y):
        if y < theme.SIDE_TOP_CAP or y >= theme.SIDE_ART_HEIGHT - theme.SIDE_TOP_CAP:
            return (200, 0, 0, 255)
        return (0, 0, 200, 255)

    source = make_image(12, theme.SIDE_ART_HEIGHT, pixel)
    border = theme.build_vertical_border(source, 300, (0, 0, 0))
    assert (border.width, border.height) == (12, 300)
    assert border.pixel(0, 0) == bytes([200, 0, 0, 255])
    cap = theme.SIDE_TOP_CAP
    assert border.pixel(0, cap - 1) == bytes([200, 0, 0, 255])
    assert border.pixel(0, cap) == bytes([0, 0, 200, 255])
    assert border.pixel(0, 300 - cap - 1) == bytes([0, 0, 200, 255])
    assert border.pixel(0, 300 - cap) == bytes([200, 0, 0, 255])


def test_vertical_border_splits_in_half_when_it_is_too_short():
    source = make_image(12, 600, lambda x, y: (7, 8, 9, 255) if y < 300
                        else (1, 2, 3, 255))
    border = theme.build_vertical_border(source, 40, (0, 0, 0))
    assert (border.width, border.height) == (12, 40)
    assert border.pixel(0, 0) == bytes([7, 8, 9, 255])
    assert border.pixel(0, 39) == bytes([1, 2, 3, 255])


def test_title_extra_row_continues_the_last_source_row():
    source = make_image(120, 3, lambda x, y: (40, 50, 60, 255) if y == 2
                        else (0, 0, 0, 255))
    row = theme.build_title_extra_row(source, 300, (0, 0, 0))
    assert (row.width, row.height) == (300, 1)
    assert row.pixel(0, 0) == bytes([40, 50, 60, 255])
    assert row.pixel(150, 0) == bytes([40, 50, 60, 255])


def test_peek_fades_from_the_top_and_stays_subtle():
    peek = theme.build_peek(20, 28, (0, 0, 0))
    assert (peek.width, peek.height) == (20, 28)
    top = peek.pixel(0, 0)
    bottom = peek.pixel(0, 27)
    assert top[0] > bottom[0], "the gradient must be strongest at the top"
    # The compositor peaks at alpha 12, so the light stays a whisper.
    assert top[0] <= theme.PEAK_COLOR[0] * 12 // 255 + 1


def test_sheen_wraps_horizontally_and_keeps_its_phase():
    def pixel(x, y):
        return (0, 0, 0, 0) if x != 3 else (255, 255, 255, 255)

    source = make_image(10, 2, pixel)
    background = (0, 0, 0)
    # The lit column sits at source x=3; with offset 0 it lands at dest x=3.
    assert theme.build_sheen(source, 20, 2, 0, background).pixel(3, 0) == bytes([255, 255, 255, 255])
    # Shifting the window by 7 slides the highlight left, it does not reset.
    assert theme.build_sheen(source, 20, 2, 7, background).pixel(6, 0) == bytes([255, 255, 255, 255])
    # A wide window wraps around instead of running out of artwork.
    assert theme.build_sheen(source, 20, 2, 0, background).pixel(13, 0) == bytes([255, 255, 255, 255])


def test_blend_pixel_matches_a_source_over_composite():
    assert theme.blend_pixel((10, 20, 30, 255), (0, 0, 0)) == (10, 20, 30, 255)
    assert theme.blend_pixel((0, 0, 0, 0), (5, 6, 7)) == (5, 6, 7, 255)
    red, green, blue, _alpha = theme.blend_pixel((255, 255, 255, 128), (0, 0, 0))
    assert 126 <= red <= 129
    assert (red, green, blue) == (128, 128, 128)


def test_builders_clamp_instead_of_raising_on_degenerate_sizes():
    # A window can be resized to nothing before the frame is rebuilt, and a
    # repaint must not explode halfway through drawing.
    source = make_image(4, 4, lambda x, y: (1, 2, 3, 255))
    assert theme.build_horizontal_strip(source, 0, 4, (0, 0, 0)).width == 1
    assert theme.build_vertical_border(source, 0, (0, 0, 0)).height == 1
    assert theme.build_sheen(source, 10, 0, 3, (0, 0, 0)).height == 1
    assert theme.build_peek(0, 10, (0, 0, 0)).width == 1
    assert theme.build_title_extra_row(source, 0, (0, 0, 0)).width == 1
