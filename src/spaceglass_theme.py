'''
 *
 *      spaceglass_theme.py
 *      VortexGlass theme loader, inventory, and nine-slice geometry.
 *
 *      2026/9/27 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import os
import struct
from dataclasses import dataclass
from pathlib import Path

import pngcodec

# Environment override for the theme directory.
ENV_THEME_DIR = "VORTEXGLASS_THEME_DIR"
# Where a theme lives once it is installed into the PySpOS tree.
THEME_SUBDIR = os.path.join("assets", "themes", "vortexglass")
# Fixed locations tried when nothing is passed and the variable is unset.
FALLBACK_THEME_DIRS = (
    os.path.join("/usr/share/themes", "vortexglass"),
    THEME_SUBDIR,
)

# Title and frame metrics taken from the compositor implementation.
TITLEBAR_HEIGHT = 28
TITLE_ART_HEIGHT = 27
SIDE_INSET = 12
SIDE_OVERLAP_TOP = 2
SIDE_OVERLAP_BOTTOM = 2
BOTTOM_HEIGHT = 20
BUTTON_HEIGHT = 18
BUTTON_GAP = 5
TITLE_LEFT = 20
TITLE_TOP = 5
TITLE_RIGHT_RESERVE = 125
FRAME_CORNER = 50
# Authored height of the side strips; the compositor never uses all of it.
SIDE_ART_HEIGHT = 600
SIDE_TOP_CAP = 40
SIDE_BOTTOM_CAP = 40
SIDE_GLASS_Y = 200


# One canonical theme file and its role in the compositor.
@dataclass(frozen=True)
class ThemeAsset:
    name: str
    role: str
    width: int
    height: int
    color: int


# Expected dimensions and PNG colour types for the 34-image VortexGlass set.
# Colour types are PNG values: 3 is palette, 4 is gray plus alpha and 6 is RGBA.
REQUIRED_ASSETS = (
    ThemeAsset("top.png", "title-strip", 336, 27, 6),
    ThemeAsset("bottom.png", "bottom-strip", 181, 20, 6),
    ThemeAsset("left.png", "left-strip", 12, 600, 6),
    ThemeAsset("right.png", "right-strip", 12, 600, 6),
    ThemeAsset("frame_top_left.png", "top-left-corner", 8, 25, 4),
    ThemeAsset("frame_top_right.png", "top-right-corner", 8, 25, 4),
    ThemeAsset("frame_bottom_left.png", "bottom-left-corner", 8, 8, 4),
    ThemeAsset("frame_bottom_right.png", "bottom-right-corner", 8, 8, 4),
    ThemeAsset("close.png", "close-normal", 41, 18, 6),
    ThemeAsset("close_light.png", "close-hover", 41, 18, 6),
    ThemeAsset("min.png", "minimize-normal", 26, 18, 6),
    ThemeAsset("min_light.png", "minimize-hover", 26, 18, 6),
    ThemeAsset("max.png", "maximize-normal", 26, 18, 6),
    ThemeAsset("max_light.png", "maximize-hover", 26, 18, 6),
    ThemeAsset("btn_close_0.png", "close-frame-0", 51, 22, 6),
    ThemeAsset("btn_close_1.png", "close-frame-1", 51, 22, 6),
    ThemeAsset("btn_close_2.png", "close-frame-2", 51, 22, 6),
    ThemeAsset("btn_close_3.png", "close-frame-3", 51, 22, 6),
    ThemeAsset("btn_max_0.png", "maximize-frame-0", 31, 22, 4),
    ThemeAsset("btn_max_1.png", "maximize-frame-1", 31, 22, 6),
    ThemeAsset("btn_max_2.png", "maximize-frame-2", 31, 22, 6),
    ThemeAsset("btn_max_3.png", "maximize-frame-3", 31, 22, 4),
    ThemeAsset("btn_min_0.png", "minimize-frame-0", 31, 22, 3),
    ThemeAsset("btn_min_1.png", "minimize-frame-1", 31, 22, 6),
    ThemeAsset("btn_min_2.png", "minimize-frame-2", 31, 22, 6),
    ThemeAsset("btn_min_3.png", "minimize-frame-3", 31, 22, 3),
    ThemeAsset("btn_rst_0.png", "restore-frame-0", 31, 22, 4),
    ThemeAsset("btn_rst_1.png", "restore-frame-1", 31, 22, 6),
    ThemeAsset("btn_rst_2.png", "restore-frame-2", 31, 22, 6),
    ThemeAsset("btn_rst_3.png", "restore-frame-3", 31, 22, 4),
    ThemeAsset("orb_0.png", "orb-normal", 36, 36, 6),
    ThemeAsset("orb_1.png", "orb-hover", 36, 36, 6),
    ThemeAsset("orb_2.png", "orb-pressed", 36, 36, 6),
    ThemeAsset("reflection.png", "glass-sheen", 802, 604, 6),
)

# Generic title buttons and their two production states.
TITLE_BUTTONS = {
    "close": {"normal": "close.png", "hover": "close_light.png"},
    "min": {"normal": "min.png", "hover": "min_light.png"},
    "max": {"normal": "max.png", "hover": "max_light.png"},
}

# Four indexed animation frames for each caption control.
BUTTON_SERIES = {
    "close": ("btn_close_0.png", "btn_close_1.png",
              "btn_close_2.png", "btn_close_3.png"),
    "max": ("btn_max_0.png", "btn_max_1.png",
            "btn_max_2.png", "btn_max_3.png"),
    "min": ("btn_min_0.png", "btn_min_1.png",
            "btn_min_2.png", "btn_min_3.png"),
    "restore": ("btn_rst_0.png", "btn_rst_1.png",
                "btn_rst_2.png", "btn_rst_3.png"),
}

# Orb animation states in the compositor.
ORB_STATES = ("orb_0.png", "orb_1.png", "orb_2.png")


# PNG image dimensions and colour type read directly from IHDR, without Pillow.
@dataclass(frozen=True)
class PngInfo:
    width: int
    height: int
    color: int


# Return the PySpOS system root, which is the parent of the running directory.
# An app is executed from the apps/ directory, so its parent is the tree that
# holds etc/, assets/ and the rest of the system, exactly as api.py assumes.
def system_root():
    return Path(os.getcwd()).resolve().parent


# Where the fallback search looks for a directory named vortexglass. The theme
# is not vendored, so a checkout of the project that drew the artwork, a
# desktop copy of it, or a system-wide install are all fair game.
def search_roots():
    home = os.path.expanduser("~")
    roots = [str(system_root().parent), "/usr/share/themes",
             "/usr/local/share/themes", os.path.join(home, "桌面"),
             os.path.join(home, "Desktop"), os.path.join(home, "Music"),
             os.path.join(home, ".local", "share"), home]
    seen = set()
    ordered = []
    for root in roots:
        if not root or root in seen or not os.path.isdir(root):
            continue
        seen.add(root)
        ordered.append(root)
    return ordered


# Directories that never hold a theme and are expensive to walk.
SKIP_DIR_NAMES = frozenset({
    ".git", ".svn", ".hg", "node_modules", "__pycache__", ".cache", ".npm",
    ".venv", "venv", "dist", "build", ".gradle", ".m2", "site-packages",
    ".local", "snap", "flatpak",
})
# The directory name the search looks for.
THEME_DIR_NAME = "vortexglass"
# Bounds, so a huge home directory cannot stall the shell on `open spaceglass`.
SEARCH_MAX_DEPTH = 6
SEARCH_MAX_DIRS = 20000


# Report whether a directory holds the files a theme needs to draw a window.
def looks_like_theme(path):
    return all(os.path.isfile(os.path.join(path, asset.name))
               for asset in REQUIRED_ASSETS)


# Walk the search roots for the first complete theme directory.
# A partial match is skipped rather than accepted, because a half-copied theme
# would otherwise be picked and then fail one image at a time while drawing.
def discover_theme_dir():
    for root in search_roots():
        root_depth = root.rstrip(os.sep).count(os.sep)
        examined = 0
        for current, dirnames, _files in os.walk(root):
            if examined >= SEARCH_MAX_DIRS:
                break
            examined += 1
            if current.count(os.sep) - root_depth >= SEARCH_MAX_DEPTH:
                dirnames[:] = []
                continue
            dirnames[:] = sorted(name for name in dirnames
                                 if name not in SKIP_DIR_NAMES
                                 and not name.startswith("."))
            if os.path.basename(current) != THEME_DIR_NAME:
                continue
            if looks_like_theme(current):
                return os.path.abspath(current)
            # Do not descend into a theme that failed the check: its own
            # subdirectories cannot hold another theme.
            dirnames[:] = []
    return None


# Candidate theme directories, with the explicit path and the variable first.
# An explicit path stands alone: consulting the variable or the disk after it
# would let `open spaceglass --theme-dir=...` quietly load something else.
def candidate_theme_dirs(explicit=None):
    if explicit:
        return [explicit]
    candidates = []
    override = os.environ.get(ENV_THEME_DIR)
    if override:
        candidates.append(override)
    candidates.append(os.path.join(str(system_root()), THEME_SUBDIR))
    candidates.extend(FALLBACK_THEME_DIRS)
    return candidates


# Locate the first directory containing top.png, searching the disk if needed.
# A directory the caller named explicitly is authoritative: if it has no theme,
# that is an error to report, not a reason to silently load some other copy
# found somewhere else on the disk.
def find_theme_dir(explicit=None, search=True):
    for candidate in candidate_theme_dirs(explicit):
        if not candidate:
            continue
        if os.path.isfile(os.path.join(candidate, "top.png")):
            return os.path.abspath(candidate)
    if search and not explicit:
        found = discover_theme_dir()
        if found is not None:
            return found
    searched = ", ".join(candidate_theme_dirs(explicit)) or "(none)"
    if explicit:
        raise FileNotFoundError(
            f"Cannot find a VortexGlass theme in: {searched}. "
            f"The directory you named has no VortexGlass top.png in it."
        )
    if search:
        raise FileNotFoundError(
            f"Cannot find a VortexGlass theme in: {searched}, "
            f"or under any of: {', '.join(search_roots())}. "
            f"Set {ENV_THEME_DIR} or pass an explicit theme directory."
        )
    raise FileNotFoundError(
        f"Cannot find a VortexGlass theme in: {searched}. "
        f"Set {ENV_THEME_DIR} or pass an explicit theme directory."
    )


# Read width, height and colour type from a PNG IHDR chunk.
def read_png_info(path):
    with open(path, "rb") as stream:
        data = stream.read(33)
    if len(data) < 33 or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path} is not a PNG file")
    length, kind = struct.unpack(">I4s", data[8:16])
    if kind != b"IHDR" or length != 13:
        raise ValueError(f"{path} has no valid IHDR chunk")
    width, height, _depth, color = struct.unpack(">IIBB", data[16:26])
    if width <= 0 or height <= 0:
        raise ValueError(f"{path} has an invalid image size")
    return PngInfo(width=width, height=height, color=color)


# Validate the complete theme directory and report usable image paths.
def load_theme(theme_dir=None):
    directory = find_theme_dir(theme_dir)
    images = {}
    missing = []
    mismatched = []
    for asset in REQUIRED_ASSETS:
        path = os.path.join(directory, asset.name)
        if not os.path.isfile(path):
            missing.append(asset.name)
            continue
        try:
            info = read_png_info(path)
        except (OSError, ValueError) as exc:
            mismatched.append(f"{asset.name}: {exc}")
            continue
        if (info.width, info.height, info.color) != (asset.width, asset.height, asset.color):
            mismatched.append(
                f"{asset.name}: expected {asset.width}x{asset.height} "
                f"color {asset.color}, got {info.width}x{info.height} "
                f"color {info.color}"
            )
            continue
        images[asset.name] = path
    return {"directory": directory, "images": images, "missing": missing, "mismatched": mismatched}


# Report whether a loaded theme directory is complete.
def theme_complete(report):
    return not report["missing"] and not report["mismatched"]


# Return the compositor rectangle for a title button.
def title_button_rect(kind, client_x, title_y, client_width):
    widths = {"close": 41, "max": 26, "min": 26}
    if kind not in widths:
        raise ValueError(f"Unknown title button: {kind}")
    frame_right = client_x + client_width + SIDE_INSET
    if kind == "close":
        left = frame_right - 45
    elif kind == "max":
        left = frame_right - 45 - 26
    else:
        left = frame_right - 45 - 26 - 26
    return (left, title_y + BUTTON_GAP, widths[kind], BUTTON_HEIGHT)


# Return title geometry for a client width.
def title_geometry(client_x, title_y, client_width, focused=True):
    strip_x = client_x - SIDE_INSET
    strip_width = max(0, client_width + SIDE_INSET * 2)
    return {
        "strip": (strip_x, title_y, strip_width, TITLEBAR_HEIGHT),
        "art": (strip_x, title_y, strip_width, TITLE_ART_HEIGHT),
        "extra_row": (strip_x, title_y + TITLE_ART_HEIGHT, strip_width, 1),
        "text": (client_x + TITLE_LEFT, title_y + TITLE_TOP,
                 max(0, client_width - TITLE_RIGHT_RESERVE)),
        "buttons": {kind: title_button_rect(kind, client_x, title_y, client_width)
                    for kind in ("min", "max", "close")},
        "focused": bool(focused),
    }


# Window layout for a client rectangle.
class WindowLayout:
    # Create a glass-window layout around a client rectangle.
    def __init__(self, client_x, client_y, client_width, client_height,
                 title="SpaceGlass", focused=True):
        if client_width <= 0 or client_height <= 0:
            raise ValueError("Client dimensions must be positive")
        self.client_x = int(client_x)
        self.client_y = int(client_y)
        self.client_width = int(client_width)
        self.client_height = int(client_height)
        self.title = str(title)
        self.focused = bool(focused)

    # Return the complete frame and control rectangles.
    def frame(self):
        title_y = self.client_y - TITLEBAR_HEIGHT
        title = title_geometry(self.client_x, title_y, self.client_width,
                               self.focused)
        strip_y_bottom = self.client_y + self.client_height
        strip_width = self.client_width + SIDE_INSET * 2
        frame = {
            "client": (self.client_x, self.client_y,
                       self.client_width, self.client_height),
            "title": title,
            "left": (self.client_x - SIDE_INSET,
                     self.client_y - SIDE_OVERLAP_TOP,
                     SIDE_INSET,
                     self.client_height + SIDE_OVERLAP_TOP + SIDE_OVERLAP_BOTTOM),
            "right": (self.client_x + self.client_width,
                      self.client_y - SIDE_OVERLAP_TOP,
                      SIDE_INSET,
                      self.client_height + SIDE_OVERLAP_TOP + SIDE_OVERLAP_BOTTOM),
            "bottom": (self.client_x - SIDE_INSET,
                       strip_y_bottom,
                       strip_width, BOTTOM_HEIGHT),
            "frost": {
                "title": (title["strip"][0], title["strip"][1],
                          title["strip"][2], TITLEBAR_HEIGHT),
                "left": (self.client_x - SIDE_INSET + 5,
                         self.client_y - SIDE_OVERLAP_TOP,
                         6, self.client_height + SIDE_OVERLAP_TOP + SIDE_OVERLAP_BOTTOM),
                "right": (self.client_x + self.client_width + 1,
                          self.client_y - SIDE_OVERLAP_TOP,
                          6, self.client_height + SIDE_OVERLAP_TOP + SIDE_OVERLAP_BOTTOM),
                "bottom": (self.client_x - SIDE_INSET, strip_y_bottom,
                           strip_width, 8),
            },
        }
        return frame

    # Return the button at a point, or None when no button contains it.
    def hit_button(self, x, y):
        frame = self.frame()["title"]["buttons"]
        for name in ("close", "max", "min"):
            left, top, width, height = frame[name]
            if left <= x < left + width and top <= y < top + height:
                return name
        return None

    # Return True when the point is inside the draggable title strip.
    def hit_title(self, x, y):
        strip = self.frame()["title"]["strip"]
        return strip[0] <= x < strip[0] + strip[2] and strip[1] <= y < strip[1] + strip[3]


# --------------------------------------------------------------------------
# compositor-accurate strip painting
# --------------------------------------------------------------------------
# The compositor never scales the middle of a strip. It keeps the rounded caps
# at their authored width and fills the whole span with the single source
# column, so a wide title bar shows one flat glass colour instead of a stretched
# copy of the artwork. The builders below reproduce that exactly, which is why
# they work in plain RGBA instead of relying on a GUI toolkit to stretch PNGs.

# Alpha of the white gradient the compositor lays over the title bar.
PEAK_ALPHA = 12
PEAK_COLOR = (235, 245, 255)
# Source column sampled for a horizontal strip, and row for a vertical one.
STRIP_MIDDLE_COLUMN_DIVISOR = 2
BORDER_MIDDLE_ROW = 200


# Blend one straight RGBA pixel over an opaque background colour.
# The result is opaque, so callers can use it directly as four output bytes.
def blend_pixel(pixel, background):
    red, green, blue, alpha = pixel
    if alpha == 255:
        return (red, green, blue, 255)
    inverse = 255 - alpha
    return (
        (red * alpha + background[0] * inverse) // 255,
        (green * alpha + background[1] * inverse) // 255,
        (blue * alpha + background[2] * inverse) // 255,
        255,
    )


# Create a destination image already filled with the opaque backdrop colour.
# The buffer is mutable because the strip builders write into it in place, and
# the size is clamped to at least one pixel so a degenerate request from a
# collapsed window cannot raise in the middle of a repaint.
def _blank(width, height, background):
    width = max(1, width)
    height = max(1, height)
    pixel = bytes((background[0], background[1], background[2], 255))
    return pngcodec.RgbaImage(width, height, bytearray(pixel * (width * height)))


# Composite an image region into a destination image at an offset.
# Every source pixel is blended over the backdrop here, because Tk 8.6 photo
# images have no alpha channel at all: a transparent pixel handed to Tk keeps
# only its stored colour, which would turn every rounded corner of the glass
# artwork into an opaque black square.
def _blit_region(dest, dest_x, dest_y, source, source_x, source_y,
                 width, height, background):
    if width <= 0 or height <= 0:
        return
    if (dest_x < 0 or dest_y < 0 or dest_x + width > dest.width
            or dest_y + height > dest.height):
        return
    for row in range(height):
        for col in range(width):
            pixel = source.pixel(source_x + col, source_y + row)
            if pixel[3] == 255:
                value = pixel
            else:
                value = bytes(blend_pixel(pixel, background))
            target = ((dest_y + row) * dest.width + dest_x + col) * 4
            dest.pixels[target:target + 4] = value


# Build one horizontal strip: two native caps and a flat middle.
def build_horizontal_strip(source, width, height, background,
                           corner=FRAME_CORNER):
    dest = _blank(width, height, background)
    if width <= 0 or height <= 0:
        return dest
    middle_x = source.width // STRIP_MIDDLE_COLUMN_DIVISOR
    rows = min(height, source.height)
    if width < corner * 2:
        half = width // 2
        _blit_region(dest, 0, 0, source, 0, 0, half, rows, background)
        _blit_region(dest, half, 0, source, source.width - (width - half), 0,
                     width - half, rows, background)
        return dest
    _blit_region(dest, 0, 0, source, 0, 0, corner, rows, background)
    _blit_region(dest, width - corner, 0, source, source.width - corner, 0,
                 corner, rows, background)
    span = width - corner * 2
    for row in range(rows):
        pixel = source.pixel(middle_x, row)
        if pixel[3] == 0:
            continue
        colour = bytes(blend_pixel(pixel, background))
        start = (row * width + corner) * 4
        dest.pixels[start:start + span * 4] = colour * span
    return dest


# Build one vertical border: two native caps and a flat middle row.
def build_vertical_border(source, height, background, cap=SIDE_TOP_CAP):
    dest = _blank(source.width, height, background)
    if height <= 0:
        return dest
    width = source.width
    # A theme image shorter than the caps must not be read past its last row.
    cap_rows = min(cap, source.height)
    if height <= cap * 2:
        half = height // 2
        _blit_region(dest, 0, 0, source, 0, 0, width, min(half, cap_rows),
                     background)
        lower = min(height - half, cap_rows)
        _blit_region(dest, 0, height - lower, source, 0,
                     max(0, source.height - lower), width, lower, background)
        return dest
    _blit_region(dest, 0, 0, source, 0, 0, width, cap_rows, background)
    _blit_region(dest, 0, height - cap_rows, source, 0,
                 max(0, source.height - cap_rows), width, cap_rows, background)
    middle_row = min(BORDER_MIDDLE_ROW, source.height - 1)
    row = b"".join(bytes(blend_pixel(source.pixel(col, middle_row), background))
                   for col in range(width))
    for line in range(height - cap * 2):
        start = ((cap + line) * width) * 4
        dest.pixels[start:start + width * 4] = row
    return dest


# Build the one-pixel row that continues the title art under the title bar.
def build_title_extra_row(source, width, background, corner=FRAME_CORNER):
    dest = _blank(width, 1, background)
    if width <= 0:
        return dest
    last_row = source.height - 1
    middle_x = source.width // STRIP_MIDDLE_COLUMN_DIVISOR
    if width < corner * 2:
        half = width // 2
        _blit_region(dest, 0, 0, source, 0, last_row, half, 1, background)
        _blit_region(dest, half, 0, source, source.width - (width - half),
                     last_row, width - half, 1, background)
        return dest
    _blit_region(dest, 0, 0, source, 0, last_row, corner, 1, background)
    _blit_region(dest, width - corner, 0, source, source.width - corner,
                 last_row, corner, 1, background)
    pixel = source.pixel(middle_x, last_row)
    if pixel[3] != 0:
        colour = bytes(blend_pixel(pixel, background))
        dest.pixels[corner * 4:(width - corner) * 4] = colour * (width - corner * 2)
    return dest


# Build the white gradient the compositor lays over the title bar.
def build_peek(width, height, background, peak=PEAK_ALPHA):
    dest = _blank(width, height, background)
    for row in range(dest.height):
        alpha = peak * (dest.height - row) // dest.height
        if alpha <= 0:
            continue
        colour = bytes(blend_pixel(
            (PEAK_COLOR[0], PEAK_COLOR[1], PEAK_COLOR[2], alpha), background))
        start = (row * dest.width) * 4
        dest.pixels[start:start + dest.width * 4] = colour * dest.width
    return dest


# Build the screen-anchored diagonal sheen for a rectangle.
# The compositor blits the top rows of the sheen art at 1:1 and wraps
# horizontally from the destination x, so dragging the window slides the light
# under it instead of moving the highlight along with the window.
def build_sheen(source, width, height, offset_x, background):
    dest = _blank(width, height, background)
    if source.width <= 0 or width <= 0 or height <= 0:
        return dest
    start = offset_x % source.width
    for col in range(width):
        source_x = (start + col) % source.width
        for row in range(min(dest.height, source.height)):
            pixel = source.pixel(source_x, row)
            if pixel[3] == 0:
                continue
            target = (row * dest.width + col) * 4
            dest.pixels[target:target + 4] = bytes(
                blend_pixel(pixel, background))
    return dest
