'''
 *
 *      test_spaceglass_app.py
 *      The spaceglass app builds a real VortexGlass window against a Tk root.
 *
 *      Skipped without a display, because the checks that matter here are the
 *      ones that only fail once Tk is involved: a bad widget option, a repaint
 *      that drops the alpha channel, or a caption button that stops matching
 *      the frame it was drawn into.
 *
 *      2026/9/27 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

from tests.support import REPO as REPO_ROOT

import contextlib
import io
import os
import tkinter as tk
import types

import pytest

import pngcodec
import spaceglass_theme as theme

# Only the interactive tests need a real Tk root, and they must be asked for
# explicitly. Gating on DISPLAY alone is not enough: a developer running pytest
# on a desktop has DISPLAY set, and every window would then open on the real
# screen instead of a throwaway one. Run them under a virtual display with
#   SPACEGLASS_TK_TESTS=1 xvfb-run -a python3 -m pytest tests/ui/test_spaceglass_app.py
requires_display = pytest.mark.skipif(
    not (os.environ.get("DISPLAY") and os.environ.get("SPACEGLASS_TK_TESTS")),
    reason="需要显示环境与 SPACEGLASS_TK_TESTS=1（建议在 xvfb-run 下运行，"
           "否则窗口会开在真实屏幕上）")

# The app file, loaded the way PySpOS launches an app.
REPO = REPO_ROOT
APP_PATH = os.path.join(REPO, "src", "apps", "spaceglass.py")


# Build a stand-in for a Tk mouse event, with absolute coordinates defaulted.
def event(x, y, x_root=None, y_root=None):
    return types.SimpleNamespace(x=x, y=y,
                                 x_root=x if x_root is None else x_root,
                                 y_root=y if y_root is None else y_root)


# Import the app without running main(), mirroring how a test sees a module.
@pytest.fixture(scope="module")
def app():
    module = types.ModuleType("spaceglass_under_test")
    module.__file__ = APP_PATH
    module.__name__ = "spaceglass_under_test"
    with open(APP_PATH, "r", encoding="utf-8") as stream:
        source = stream.read()
    # The module prints a banner unless it is the __exec__ entry point, and the
    # name above is deliberately not __exec__, so silence that one line.
    with contextlib.redirect_stdout(io.StringIO()):
        exec(compile(source, APP_PATH, "exec"), module.__dict__)
    return module


@pytest.fixture
def report(theme_dir):
    return theme.load_theme(theme_dir)


@pytest.fixture
def window(app, report):
    try:
        built = app.SpaceGlassWindow(report, "SpaceGlass Test", 640, 400)
    except Exception as exc:  # pragma: no cover - depends on the environment
        pytest.skip(f"无法创建 Tk 窗口: {exc}")
    built.root.update()
    yield built
    try:
        built.root.destroy()
    except Exception:
        pass


@requires_display
def test_window_size_is_the_client_plus_the_glass_frame(window):
    assert window.root.winfo_width() == window.client_width + theme.SIDE_INSET * 2
    assert window.root.winfo_height() == (window.client_height
                                          + theme.TITLEBAR_HEIGHT
                                          + theme.BOTTOM_HEIGHT)


@requires_display
def test_client_area_sits_inside_the_frame(window):
    frame = window.layout().frame()
    assert window.client.winfo_x() == frame["client"][0]
    assert window.client.winfo_y() == frame["client"][1]
    assert window.client.winfo_width() == window.client_width
    assert window.client.winfo_height() == window.client_height


@requires_display
def test_frame_is_drawn_edge_to_edge(window):
    frame = window.layout().frame()
    assert frame["title"]["strip"][0] == 0
    assert frame["left"][0] == 0
    assert frame["right"][0] + frame["right"][2] == window.root.winfo_width()
    assert frame["bottom"][1] + frame["bottom"][3] == window.root.winfo_height()
    kinds = [window.canvas.type(item) for item in window.canvas.find_all()]
    assert kinds.count("image") >= 7, "the seven painted frame strips are missing"
    assert kinds.count("text") == 1, "the title text must be drawn once"


@requires_display
def test_hover_swaps_the_caption_button_and_keeps_the_frame(window):
    close = window.layout().frame()["title"]["buttons"]["close"]
    assert window.hover_button is None
    window._on_motion(event(close[0] + 2, close[1] + 2))
    assert window.hover_button == "close"
    assert window.canvas.cget("cursor") == "hand2"
    window._on_motion(event(close[0] + 200, close[1] + 2))
    assert window.hover_button is None
    assert window.canvas.cget("cursor") == ""


@requires_display
def test_dragging_the_title_moves_the_window(window):
    start = window.root.geometry()
    origin = (window.origin_x, window.origin_y)
    window._on_press(event(200, 10, x_root=origin[0] + 200,
                            y_root=origin[1] + 10))
    assert window.drag_origin == (200, 10)
    window._on_drag(event(200, 10, x_root=origin[0] + 260,
                          y_root=origin[1] + 70))
    assert window.root.geometry() != start
    assert (window.origin_x, window.origin_y) == (origin[0] + 60, origin[1] + 60)


@requires_display
def test_pressing_the_content_area_starts_no_drag(window):
    window._on_press(event(300, 300, x_root=500, y_root=500))
    assert window.drag_origin is None
    assert window.pressed_button is None


@requires_display
def test_pressing_a_caption_button_selects_it(window):
    close = window.layout().frame()["title"]["buttons"]["close"]
    window._on_press(event(close[0] + 2, close[1] + 2))
    assert window.pressed_button == "close"
    assert window.drag_origin is None


@requires_display
def test_maximize_round_trips_to_the_previous_size(window):
    before = (window.client_width, window.client_height)
    window.toggle_maximize()
    window.root.update()
    assert window.maximized is True
    assert window.client_width >= before[0]
    window.toggle_maximize()
    window.root.update()
    assert window.maximized is False
    assert (window.client_width, window.client_height) == before


@requires_display
def test_resize_rebuilds_the_painted_strips(window):
    before = window.frame_size
    window.client_width = 520
    window.apply_geometry()
    window.redraw()
    window.root.update()
    assert window.frame_size != before
    assert window.frame_size[0] == 520
    # Repainting at a new size must drop the previous strip images instead of
    # letting the cache grow once per resize.
    painted = [key for key in window.cache.images
               if isinstance(key, tuple) and key[0] == "paint"]
    assert painted
    old_width = 640 + theme.SIDE_INSET * 2
    new_width = 520 + theme.SIDE_INSET * 2
    assert all(old_width not in key[2:4] for key in painted)
    assert any(new_width in key[2:4] for key in painted)


@requires_display
def test_orb_animation_visits_every_state(window):
    seen = set()
    for _ in range(len(theme.ORB_STATES)):
        window.tick_orb()
        seen.add(window.orb_index)
    assert seen == set(range(len(theme.ORB_STATES)))
    assert window.orb_label.cget("image")


@requires_display
def test_escape_closes_the_window(window):
    window.root.event_generate("<Escape>")
    window.root.update()
    # A destroyed Tk root refuses every command, which is the observable proof.
    with pytest.raises(tk.TclError):
        window.root.winfo_exists()


@requires_display
def test_tk_receives_an_opaque_painted_strip(window, tmp_path):
    # Tk 8.6 photo images have no alpha channel, so the strips must already be
    # composited over the backdrop here. Write one back out of the interpreter
    # and confirm it arrives opaque, which is what keeps the rounded corners of
    # the glass artwork from turning into black squares.
    painted = {key: value for key, value in window.cache.images.items()
               if isinstance(key, tuple) and key[0] == "paint"}
    assert painted, "the frame strips must reach Tk as painted images"
    path = str(tmp_path / "strip.png")
    for key, name in painted.items():
        window.root.tk.call(name, "write", path, "-format", "png")
        image = pngcodec.read_png(path)
        assert (image.width, image.height) == (key[2], key[3])
        assert set(image.pixels[3::4]) == {255}, f"{key} must be opaque"


def test_parse_args_accepts_the_documented_options(app):
    options = app.parse_args(["--theme-dir=/tmp/t", "--title=Demo",
                              "--size=640x480"])
    assert options == {"theme_dir": "/tmp/t", "title": "Demo",
                       "width": 640, "height": 480,
                       "render": None, "window": None}
    assert app.parse_args([])["theme_dir"] is None


def test_render_flag_takes_an_optional_path(app, tmp_path):
    assert app.parse_args(["--render"])["render"] == app.DEFAULT_RENDER
    target = str(tmp_path / "out.png")
    assert app.parse_args([f"--render={target}"])["render"] == target
    assert app.parse_args(["--window"])["window"] is True


def test_offline_render_writes_a_complete_window(app, report, tmp_path):
    # A PySpOS guest has no display server, so the app must still produce the
    # window as a file. This path never touches Tk, so it runs everywhere.
    pixels = app.ThemePixels(report)
    image = app.compose_window(pixels, 640, 400, app.parse_colour(app.BACKDROP))
    assert (image.width, image.height) == (640 + theme.SIDE_INSET * 2,
                                           400 + theme.TITLEBAR_HEIGHT
                                           + theme.BOTTOM_HEIGHT)
    assert set(image.pixels[3::4]) == {255}
    path = str(tmp_path / "window.png")
    app.render_to_file(pixels, app.parse_args([f"--render={path}",
                                               "--size=640x400"]))
    written = pngcodec.read_png(path)
    assert (written.width, written.height) == (image.width, image.height)
    assert written.pixels == image.pixels


def test_offline_render_places_the_orb_and_the_caption_buttons(app, report):
    pixels = app.ThemePixels(report)
    image = app.compose_window(pixels, 640, 400, app.parse_colour(app.BACKDROP))
    layout = theme.WindowLayout(theme.SIDE_INSET, theme.TITLEBAR_HEIGHT, 640,
                               400)
    close = layout.frame()["title"]["buttons"]["close"]
    # The button artwork is opaque artwork, so it survives the composite intact.
    source = pixels.button(theme.TITLE_BUTTONS["close"]["normal"])
    centre = ((close[1] + source.height // 2) * image.width
              + close[0] + source.width // 2) * 4
    assert image.pixels[centre:centre + 3] == source.pixels[
        (source.height // 2 * source.width + source.width // 2) * 4:
        (source.height // 2 * source.width + source.width // 2) * 4 + 3]


def test_main_renders_a_file_when_no_display_is_available(app, report,
                                                         tmp_path,
                                                         monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    target = str(tmp_path / "guest.png")
    monkeypatch.setenv("PYSPOS_APP_ARGS", f"--render={target}")
    monkeypatch.setenv(theme.ENV_THEME_DIR, report["directory"])
    app.main()
    assert os.path.isfile(target)


@pytest.mark.parametrize("argv", [["--nope"], ["--size=wide"]])
def test_parse_args_rejects_bad_options(app, argv):
    with pytest.raises(SystemExit) as excinfo:
        app.parse_args(argv)
    assert excinfo.value.code == 2


def test_an_incomplete_theme_is_refused_before_any_window(app, tmp_path,
                                                          monkeypatch):
    (tmp_path / "top.png").write_bytes(b"")
    monkeypatch.setenv("PYSPOS_APP_ARGS", f"--theme-dir={tmp_path}")
    with pytest.raises(SystemExit) as excinfo:
        app.main()
    assert excinfo.value.code == 1


def test_a_missing_theme_reports_where_it_looked(app, tmp_path, monkeypatch,
                                                 capsys):
    monkeypatch.setenv("PYSPOS_APP_ARGS", f"--theme-dir={tmp_path}")
    with pytest.raises(SystemExit) as excinfo:
        app.main()
    assert excinfo.value.code == 1
    assert str(tmp_path) in capsys.readouterr().out


def test_arguments_come_from_the_shell_not_from_sys_argv(app, monkeypatch):
    # The launcher imports the app as a module, so sys.argv still holds the
    # launcher switches, including --kernel. Reading them would make every
    # `open spaceglass` fail before it ever loaded the theme.
    monkeypatch.setenv("PYSPOS_APP_ARGS", "--title=Demo --size=800x600")
    monkeypatch.setattr("sys.argv", ["launcher.py", "--kernel"])
    options = app.parse_args(app.app_args())
    assert options["title"] == "Demo"
    assert (options["width"], options["height"]) == (800, 600)


def test_app_args_fall_back_when_the_shell_quoted_something_bad(app,
                                                                monkeypatch):
    monkeypatch.setenv("PYSPOS_APP_ARGS", '--title="unclosed')
    # shlex refuses the dangling quote, so the raw split is used instead of
    # losing the argument entirely.
    assert app.app_args() == ['--title="unclosed']
