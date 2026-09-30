'''
 *
 *      spaceglass.py
 *      VortexGlass socket GUI demo and compatible offline theme renderer.
 *
 *      Interactive windows belong to the system compositor and are requested
 *      over its local socket. The legacy painter remains available for offline
 *      theme previews and compatibility checks without a display server.
 *
 *      2026/9/27 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import base64
import os
import shlex
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pngcodec
import spaceglass_theme as theme

# Tk is optional: without a display the app still renders the window to a file.
try:
    import tkinter as tk
    TK_AVAILABLE = True
except ImportError:
    tk = None
    TK_AVAILABLE = False

# Backdrop and content colours, matching the compositor's dark glass bed.
BACKDROP = "#0d1117"
TITLE_FG = "#e6edf3"
TITLE_FG_BLUR = "#8b949e"
CLIENT_BG = "#161b22"
CLIENT_BORDER = "#30363d"
# Small app badge drawn where the compositor blits a 16-pixel app icon.
BADGE_SIZE = 16
BADGE_X = theme.SIDE_INSET
BADGE_Y = 5
# Title text starts where the compositor places it, clear of the badge.
TITLE_TEXT_X = 32
# The orb is the PySpOS launcher mark, so it animates in the content area
# rather than in the title bar, which the compositor keeps icon-and-text only.
ORB_X = 24
ORB_Y = 20
HINT_X = 24
HINT_Y = 68
# Where the offline renderer writes its image when nothing else is asked for.
DEFAULT_RENDER = "spaceglass.png"


# Parse one "#rrggbb" string into a byte triple for the pixel painters.
def parse_colour(value):
    value = value.lstrip("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


# Create one Tk image from an RgbaImage, caching by a caller-supplied key.
# Tk drops a PhotoImage when Python drops the last reference, so every image
# this class makes is kept in the cache for the lifetime of the window.
class ImageCache:
    # Create an image cache bound to one Tk interpreter.
    def __init__(self, master, background):
        self.master = master
        self.background = background
        self.images = {}

    # Return a PhotoImage for a painted image, building it on first use.
    def photo(self, key, image):
        found = self.images.get(key)
        if found is not None:
            return found
        data = base64.b64encode(pngcodec.write_png(image)).decode("ascii")
        photo = tk.PhotoImage(master=self.master, data=data)
        self.images[key] = photo
        return photo

    # Drop every cached image, because a resize repaints all of them.
    def prune(self):
        self.images.clear()


# Load the theme artwork the window needs as raw pixels, once.
class ThemePixels:
    # Decode the strips, the sheen, the orb frames and the caption buttons.
    def __init__(self, report):
        self.paths = report["images"]
        self.top = pngcodec.read_png(self.paths["top.png"])
        self.bottom = pngcodec.read_png(self.paths["bottom.png"])
        self.left = pngcodec.read_png(self.paths["left.png"])
        self.right = pngcodec.read_png(self.paths["right.png"])
        self.reflection = pngcodec.read_png(self.paths["reflection.png"])
        self.orb = [pngcodec.read_png(self.paths[name])
                    for name in theme.ORB_STATES]
        wanted = sorted({name for states in theme.TITLE_BUTTONS.values()
                         for name in states.values()})
        self.buttons = {name: pngcodec.read_png(self.paths[name])
                        for name in wanted}

    # Return the decoded orb state for an index.
    def orb_state(self, index):
        return self.orb[index % len(self.orb)]

    # Return the decoded caption button for a theme file name.
    def button(self, name):
        return self.buttons[name]


# The VortexGlass window: a client area wrapped in glass bands and a title strip.
class SpaceGlassWindow:
    # Build the window for a loaded theme report.
    def __init__(self, report, title="SpaceGlass", width=760, height=520,
                 x=None, y=None):
        self.painted = {}
        self.pixels = ThemePixels(report)
        self.title_text = str(title)
        self.client_width = int(width)
        self.client_height = int(height)
        self.background = parse_colour(BACKDROP)
        self.focused = True
        self.maximized = False
        self.hover_button = None
        self.pressed_button = None
        self.drag_origin = None
        self.orb_index = 0
        self.restore_box = None
        self.restore_pos = None

        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title(self.title_text)
        self.root.configure(bg=BACKDROP)
        self.cache = ImageCache(self.root, self.background)

        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        self.origin_x = int(x) if x is not None else max(0, (screen_w - width) // 2)
        self.origin_y = int(y) if y is not None else max(0, (screen_h - height) // 3)

        self.canvas = tk.Canvas(self.root, highlightthickness=0, bd=0,
                                bg=BACKDROP)
        self.canvas.pack(fill="both", expand=True)
        self.client = tk.Frame(self.canvas, bg=CLIENT_BG,
                               highlightthickness=1,
                               highlightbackground=CLIENT_BORDER)
        self.hint = tk.Label(
            self.client, bg=CLIENT_BG, fg=TITLE_FG_BLUR, anchor="nw",
            justify="left", font=("TkDefaultFont", 9),
            text="Drag the title bar to move the window.\n"
                 "Double-click it or press the middle button to maximize.\n"
                 "Escape closes the window.")
        self.orb_label = tk.Label(self.client, bg=CLIENT_BG, bd=0)
        self.orb_label.place(x=ORB_X, y=ORB_Y)
        self.title_item = None
        self.badge_item = None
        self.button_items = {}
        self.frame_size = None

        self._bind_events()
        self.apply_geometry()
        self.root.update_idletasks()
        self.redraw()
        self.root.deiconify()

    # Compute the layout for the current client size.
    # The title bar sits above the client and the side bands overlap it by two
    # pixels, exactly as the compositor draws them.
    def layout(self):
        return theme.WindowLayout(theme.SIDE_INSET, theme.TITLEBAR_HEIGHT,
                                  self.client_width, self.client_height,
                                  self.title_text, self.focused)

    # Resize the window from the current client size.
    def apply_geometry(self):
        total_w = self.client_width + theme.SIDE_INSET * 2
        total_h = (self.client_height + theme.TITLEBAR_HEIGHT
                   + theme.BOTTOM_HEIGHT)
        self.root.geometry(f"{total_w}x{total_h}+{self.origin_x}+{self.origin_y}")
        self.root.minsize(theme.FRAME_CORNER * 2,
                          theme.TITLEBAR_HEIGHT + theme.BOTTOM_HEIGHT + 120)

    # Return the painted frame parts for a size, rebuilding them only on resize.
    # The four title layers are flattened into one image so the caption buttons
    # can be composited over exactly the pixels they will sit on.
    def frame_images(self, frame):
        strip = frame["title"]["strip"]
        width = strip[2]
        background = self.background
        title = _PaintCanvas(width, theme.TITLEBAR_HEIGHT, background)
        title.blit(theme.build_horizontal_strip(self.pixels.top, width,
                                                theme.TITLE_ART_HEIGHT,
                                                background), 0, 0)
        title.blit(theme.build_title_extra_row(self.pixels.top, width,
                                               background), 0,
                   theme.TITLE_ART_HEIGHT)
        title.blend(theme.build_peek(width, theme.TITLEBAR_HEIGHT, background),
                    0, 0)
        title.blend(theme.build_sheen(self.pixels.reflection, width,
                                      theme.TITLEBAR_HEIGHT, self.origin_x,
                                      background), 0, 0)
        return {
            "title": title.image(),
            "left": theme.build_vertical_border(self.pixels.left,
                                                frame["left"][3], background),
            "right": theme.build_vertical_border(self.pixels.right,
                                                 frame["right"][3], background),
            "bottom": theme.build_horizontal_strip(self.pixels.bottom, width,
                                                   theme.BOTTOM_HEIGHT,
                                                   background),
        }

    # Draw the whole window: client, glass frame, then the controls on top.
    def redraw(self):
        canvas = self.canvas
        canvas.delete("all")
        layout = self.layout()
        frame = layout.frame()
        client = frame["client"]
        self.client.place(x=client[0], y=client[1], width=client[2],
                          height=client[3])
        self.hint.place(x=HINT_X, y=HINT_Y)

        size = (self.client_width, self.client_height, self.origin_x)
        if size != self.frame_size:
            self.frame_size = size
            self.cache.prune()
            self.painted = self.frame_images(frame)
            self._place_painted("title", self.painted["title"],
                                frame["title"]["strip"][0],
                                frame["title"]["strip"][1])
            self._place_painted("left", self.painted["left"], frame["left"][0],
                                frame["left"][1])
            self._place_painted("right", self.painted["right"],
                                frame["right"][0], frame["right"][1])
            self._place_painted("bottom", self.painted["bottom"],
                                frame["bottom"][0], frame["bottom"][1])

        self._draw_controls(frame)

    # Place one painted piece at its exact size.
    def _place_painted(self, key, image, x, y):
        photo = self.cache.photo(("paint", key, image.width, image.height), image)
        return self.canvas.create_image(x, y, image=photo, anchor="nw")

    # Draw the badge, title text and caption buttons.
    def _draw_controls(self, frame):
        canvas = self.canvas
        text = frame["title"]["text"]
        self.badge_item = canvas.create_rectangle(
            BADGE_X, BADGE_Y, BADGE_X + BADGE_SIZE, BADGE_Y + BADGE_SIZE,
            fill="#2d6a9f", outline="#4d90c8")
        self.title_item = canvas.create_text(
            TITLE_TEXT_X, text[1] + BADGE_Y + 8, text=self.title_text,
            anchor="w", fill=TITLE_FG if self.focused else TITLE_FG_BLUR,
            font=("TkDefaultFont", 10, "bold"))
        title = self.painted["title"]
        for kind, rect in frame["title"]["buttons"].items():
            state = "hover" if self.hover_button == kind else "normal"
            name = theme.TITLE_BUTTONS[kind][state]
            image = button_over_title(self.pixels.button(name), title, rect,
                                      frame["title"]["strip"])
            photo = self.cache.photo(("button", name, image.width,
                                      image.height), image)
            self.button_items[kind] = canvas.create_image(
                rect[0], rect[1], image=photo, anchor="nw")
        self._draw_orb()

    # Refresh the animated orb shown in the content area.
    def _draw_orb(self):
        state = self.orb_index % len(theme.ORB_STATES)
        self.orb_label.configure(image=self.cache.photo(
            ("orb", state), self.pixels.orb_state(state)))

    # Wire mouse handling for dragging, caption buttons and the badge.
    def _bind_events(self):
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Leave>", self._on_leave)
        self.canvas.bind("<Double-Button-1>", self._on_double)
        self.root.bind("<Escape>", lambda _event: self.close())

    # Start a drag or press a caption button.
    def _on_press(self, event):
        kind = self.layout().hit_button(event.x, event.y)
        if kind is not None:
            self.pressed_button = kind
            return
        if self.layout().hit_title(event.x, event.y):
            self.drag_origin = (event.x_root - self.origin_x,
                                event.y_root - self.origin_y)
            return
        self.pressed_button = None
        self.drag_origin = None

    # Move the window while dragging.
    def _on_drag(self, event):
        if self.drag_origin is None or self.maximized:
            return
        self.origin_x = max(0, event.x_root - self.drag_origin[0])
        self.origin_y = max(0, event.y_root - self.drag_origin[1])
        self.apply_geometry()

    # Run the caption action on release.
    def _on_release(self, _event):
        kind = self.pressed_button
        self.pressed_button = None
        if kind == "close":
            self.close()
        elif kind == "max":
            self.toggle_maximize()

    # Track hover state for caption buttons.
    def _on_motion(self, event):
        kind = self.layout().hit_button(event.x, event.y)
        if kind != self.hover_button:
            self.hover_button = kind
            self.canvas.configure(cursor="hand2" if kind else "")
            self._draw_controls(self.layout().frame())

    # Clear hover state when the pointer leaves the window.
    def _on_leave(self, _event):
        if self.hover_button is not None:
            self.hover_button = None
            self._draw_controls(self.layout().frame())

    # Toggle between the normal frame and a maximized frame.
    def _on_double(self, event):
        if self.layout().hit_title(event.x, event.y):
            self.toggle_maximize()

    # Cycle the orb animation state.
    def tick_orb(self):
        self.orb_index = (self.orb_index + 1) % len(theme.ORB_STATES)
        self._draw_orb()
        self.root.after(120, self.tick_orb)

    # Swap between maximized and restored geometry.
    def toggle_maximize(self):
        if self.maximized:
            self.client_width, self.client_height = self.restore_box
            self.origin_x, self.origin_y = self.restore_pos
        else:
            self.restore_box = (self.client_width, self.client_height)
            self.restore_pos = (self.origin_x, self.origin_y)
            self.client_width = max(320, self.root.winfo_screenwidth()
                                    - theme.SIDE_INSET * 2)
            self.client_height = max(
                200, self.root.winfo_screenheight() - theme.TITLEBAR_HEIGHT
                - theme.BOTTOM_HEIGHT)
            self.origin_x = 0
            self.origin_y = 0
        self.maximized = not self.maximized
        self.apply_geometry()
        self.redraw()

    # Destroy the window.
    def close(self):
        self.root.destroy()

    # Show the window and run the orb animation loop.
    def run(self):
        self.tick_orb()
        self.root.mainloop()


# A tiny RGBA scratch buffer, so the offline render can paste pieces in order.
class _PaintCanvas:
    # Create a buffer pre-filled with the opaque backdrop colour.
    def __init__(self, width, height, background):
        pixel = bytes((background[0], background[1], background[2], 255))
        self.width = width
        self.height = height
        self.pixels = bytearray(pixel * (width * height))

    # Fill a rectangle with one opaque colour.
    def fill_rect(self, rect, colour):
        value = bytes((colour[0], colour[1], colour[2], 255))
        for row in range(rect[1], rect[1] + rect[3]):
            start = (row * self.width + rect[0]) * 4
            self.pixels[start:start + rect[2] * 4] = value * rect[2]

    # Copy an already opaque image at an offset, clipping at the edges.
    def blit(self, image, x, y):
        for row in range(image.height):
            target_y = y + row
            if target_y < 0 or target_y >= self.height:
                continue
            for col in range(image.width):
                target_x = x + col
                if target_x < 0 or target_x >= self.width:
                    continue
                source = (row * image.width + col) * 4
                target = (target_y * self.width + target_x) * 4
                self.pixels[target:target + 4] = image.pixels[source:source + 4]

    # Composite an image that still carries alpha over what is already here.
    def blend(self, image, x, y):
        for row in range(image.height):
            target_y = y + row
            if target_y < 0 or target_y >= self.height:
                continue
            for col in range(image.width):
                target_x = x + col
                if target_x < 0 or target_x >= self.width:
                    continue
                source = (row * image.width + col) * 4
                pixel = image.pixels[source:source + 4]
                if pixel[3] == 255:
                    value = pixel
                else:
                    target = (target_y * self.width + target_x) * 4
                    value = bytes(theme.blend_pixel(
                        pixel, tuple(self.pixels[target:target + 3])))
                target = (target_y * self.width + target_x) * 4
                self.pixels[target:target + 4] = value

    # Return the finished image.
    def image(self):
        return pngcodec.RgbaImage(self.width, self.height, bytes(self.pixels))


# Blend one caption button over the title bar pixels underneath it.
# The button artwork has transparent corners, and Tk 8.6 cannot carry alpha, so
# the art has to arrive already composited or those corners would show up as
# whatever colour the PNG happened to store there.
def button_over_title(art, title, rect, strip):
    left = max(0, min(rect[0] - strip[0], title.width - art.width))
    top = max(0, min(rect[1] - strip[1], title.height - art.height))
    out = _PaintCanvas(art.width, art.height, (0, 0, 0))
    out.blit(title.crop(left, top, art.width, art.height), 0, 0)
    out.blend(art, 0, 0)
    return out.image()


# Compose the whole window into one image, without any text.
# A guest has no display server and no font engine, so the offline render shows
# the frame artwork, the client bed, the badge, the orb and the caption buttons.
# The title string is the one thing it cannot draw, and it is left out on
# purpose rather than faked with a placeholder glyph.
def compose_window(pixels, client_width, client_height, background,
                   orb_index=0, sheen_offset=0):
    layout = theme.WindowLayout(theme.SIDE_INSET, theme.TITLEBAR_HEIGHT,
                                client_width, client_height)
    frame = layout.frame()
    strip = frame["title"]["strip"]
    width = client_width + theme.SIDE_INSET * 2
    height = client_height + theme.TITLEBAR_HEIGHT + theme.BOTTOM_HEIGHT
    canvas = _PaintCanvas(width, height, background)
    canvas.fill_rect(frame["client"], parse_colour(CLIENT_BG))

    title = _PaintCanvas(strip[2], theme.TITLEBAR_HEIGHT, background)
    title.blit(theme.build_horizontal_strip(pixels.top, strip[2],
                                            theme.TITLE_ART_HEIGHT, background),
               0, 0)
    title.blit(theme.build_title_extra_row(pixels.top, strip[2], background),
               0, theme.TITLE_ART_HEIGHT)
    title.blend(theme.build_peek(strip[2], theme.TITLEBAR_HEIGHT, background),
                0, 0)
    title.blend(theme.build_sheen(pixels.reflection, strip[2],
                                  theme.TITLEBAR_HEIGHT, sheen_offset,
                                  background), 0, 0)
    title = title.image()
    canvas.blit(title, strip[0], strip[1])
    canvas.blit(theme.build_vertical_border(pixels.left, frame["left"][3],
                                            background),
                frame["left"][0], frame["left"][1])
    canvas.blit(theme.build_vertical_border(pixels.right, frame["right"][3],
                                            background),
                frame["right"][0], frame["right"][1])
    canvas.blit(theme.build_horizontal_strip(pixels.bottom, width,
                                             theme.BOTTOM_HEIGHT, background),
                frame["bottom"][0], frame["bottom"][1])
    canvas.fill_rect((BADGE_X, BADGE_Y, BADGE_SIZE, BADGE_SIZE),
                     (77, 132, 190))
    # The orb lives in the content area, so it is placed relative to the client.
    canvas.blend(pixels.orb_state(orb_index), frame["client"][0] + ORB_X,
                 frame["client"][1] + ORB_Y)
    for kind, rect in frame["title"]["buttons"].items():
        canvas.blit(button_over_title(pixels.button(
            theme.TITLE_BUTTONS[kind]["normal"]), title, rect, strip),
            rect[0], rect[1])
    return canvas.image()


# Read the argument list the shell passed in PYSPOS_APP_ARGS.
# The launcher imports an app as a module, so sys.argv still belongs to the
# launcher and carries its own switches such as --kernel. Apps must read their
# own arguments from the environment, exactly like pkg.py does.
def app_args():
    raw = os.environ.get("PYSPOS_APP_ARGS", "")
    try:
        return shlex.split(raw)
    except ValueError:
        return raw.split()


# Parse simple key=value arguments and reject anything else.
def parse_args(argv):
    options = {"theme_dir": None, "title": "SpaceGlass",
               "width": 760, "height": 520, "render": None, "window": None}
    usage = ("usage: spaceglass [--theme-dir=DIR] [--title=TEXT] "
             "[--size=WIDTHxHEIGHT] [--render[=FILE]] [--window]")
    for arg in argv:
        if arg.startswith("--theme-dir="):
            options["theme_dir"] = arg.split("=", 1)[1]
        elif arg.startswith("--title="):
            options["title"] = arg.split("=", 1)[1]
        elif arg.startswith("--size="):
            try:
                width, height = arg.split("=", 1)[1].lower().split("x")
                options["width"] = int(width)
                options["height"] = int(height)
            except ValueError:
                print("invalid --size, use WIDTHxHEIGHT")
                raise SystemExit(2)
        elif arg == "--render":
            options["render"] = DEFAULT_RENDER
        elif arg.startswith("--render="):
            options["render"] = arg.split("=", 1)[1]
        elif arg == "--window":
            options["window"] = True
        else:
            print(f"unknown argument: {arg}")
            print(usage)
            raise SystemExit(2)
    return options


# Report whether an interactive window can be opened on this machine.
def display_available():
    return bool(os.name == "nt" or sys.platform == "darwin" or
                os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


# Write the window to a PNG file and report where it went.
def render_to_file(pixels, options):
    path = options["render"] or DEFAULT_RENDER
    image = compose_window(pixels, options["width"], options["height"],
                           parse_colour(BACKDROP))
    pngcodec.write_png(image, path)
    print(f"rendered {image.width}x{image.height} VortexGlass window: {path}")
    return path


# Load the theme, then show a real window or render one to a file.
def main():
    options = parse_args(app_args())
    interactive = options["window"] or (options["render"] is None and display_available())
    if interactive and options["theme_dir"] is None:
        from apps.guicanvas import main as run_canvas
        arguments = ["--title", options["title"], "--size",
                     f"{options['width']}x{options['height']}"]
        run_canvas(arguments)
        return
    try:
        report = theme.load_theme(options["theme_dir"])
    except FileNotFoundError as exc:
        print(str(exc))
        raise SystemExit(1)
    if not theme.theme_complete(report):
        for name in report["missing"]:
            print(f"missing theme image: {name}")
        for problem in report["mismatched"]:
            print(f"invalid theme image: {problem}")
        raise SystemExit(1)
    print(f"VortexGlass theme: {report['directory']}")
    if interactive:
        from apps.guicanvas import main as run_canvas
        run_canvas(["--title", options["title"], "--size",
                    f"{options['width']}x{options['height']}"])
        return
    pixels = ThemePixels(report)
    render_to_file(pixels, options)


if __name__ == "__exec__":
    main()
else:
    print("can't run!!!!!!!!")
