#!/usr/bin/env python3
'''
 *
 *      fastboot_gui.py
 *      PySpOS fastboot host client (graphical tool).
 *
 *      The device never offers a local flashing UI: this tool is the host
 *      side of the fastboot protocol, the way the Android "fastboot" binary
 *      drives a phone in fastboot mode. It talks to src/fastboot.py over
 *      loopback TCP and exposes the privileged operations (flashing, erasing,
 *      unlocking the bootloader) as buttons, plus a process panel that can
 *      send signals to running PySpOS processes.
 *
 *      Two looks are available and both share one layout: "classic" keeps the
 *      native widget rendering, "modern" is a flat dark skin. Switching takes
 *      effect immediately, and the look, host and port are remembered in a
 *      small per-user settings file.
 *
 *      2026/9/26 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import argparse
import json
import os
import queue
import socket
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk

# Where the device-side fastboot server listens by default.
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5555

# Seconds allowed for one protocol round trip.
TIMEOUT = 10.0

# Signals the process panel can deliver, mapped to the device-side names.
SIGNALS = ("SIGTERM", "SIGKILL", "SIGSTOP", "SIGCONT", "SIGUSR1", "SIGUSR2")

# Spacing scale, in pixels. Every gap in the window comes from here, so the
# layout keeps a rhythm instead of growing a padding value per widget.
GAP_XS = 4
GAP_SM = 8
GAP_MD = 12
GAP_LG = 18

# Style identifiers and the labels shown in the switcher.
STYLE_CLASSIC = "classic"
STYLE_MODERN = "modern"
STYLE_LABELS = {STYLE_CLASSIC: "经典", STYLE_MODERN: "现代"}
STYLE_CHOICES = (STYLE_CLASSIC, STYLE_MODERN)

# Variable order shown on the device tab, with the caption for each key.
VARIABLE_ROWS = (
    ("product", "产品"),
    ("version", "协议版本"),
    ("version-bootloader", "Bootloader"),
    ("unlocked", "解锁状态"),
    ("secure", "安全启动"),
    ("current-slot", "当前槽位"),
    ("pending-slot", "下次启动"),
    ("slot-count", "槽位数量"),
    ("rollback-index", "防回滚下限"),
    ("max-download-size", "最大下载"),
    ("is-userspace", "用户态"),
    ("super-partition-name", "Super 分区"),
)

# Where the client remembers its settings. Kept per user, out of the repo.
SETTINGS_DIR = os.path.join("~", ".config", "PySpOS")
SETTINGS_NAME = "fastboot_gui.json"

# Log line kinds, each with its own colour role.
LEVELS = ("OK", "FAIL", "WARN", "INFO")

# How many log lines to keep for replay after the look is switched.
LOG_HISTORY = 200


# Colour and font data for one look. Every value is plain data, so both styles
# can be inspected and tested without a display.
class Theme:
    def __init__(self, name, colors=None, fonts=None, native=False):
        self.name = name
        self.colors = colors or {}
        self.fonts = fonts or {}
        # A native theme is left untouched, which is exactly what makes the
        # classic look like the platform's own widgets.
        self.native = native

    # Return one colour role, or None when the theme has no opinion so the
    # caller can keep the platform default instead of forcing a colour.
    def color(self, role):
        return self.colors.get(role)

    # Return one font role.
    def font(self, role):
        return self.fonts.get(role)


# The classic look: the platform's own rendering, so there are no colours and
# every widget is drawn by the default theme.
THEME_CLASSIC = Theme(STYLE_CLASSIC, native=True)

# The modern look: flat dark surfaces, one accent, semantic log colours.
THEME_MODERN = Theme(
    STYLE_MODERN,
    colors={
        "bg": "#12141a",
        "panel": "#191c25",
        "sunken": "#0e1015",
        "border": "#2b3040",
        "fg": "#e7eaf2",
        "muted": "#8f97ab",
        "accent": "#5b9bff",
        "accent_fg": "#0b0d12",
        "ok": "#3ecf8e",
        "warn": "#f2b544",
        "err": "#ff6b6b",
        "active": "#2d3446",
    },
    fonts={"body": 10, "small": 9, "title": 14, "mono": 10},
)

THEMES = {STYLE_CLASSIC: THEME_CLASSIC, STYLE_MODERN: THEME_MODERN}


# Return a font family that actually exists, so the modern skin does not fall
# back to a squashed default on any of the three supported platforms.
def pick_family(root, candidates):
    try:
        available = set(tkfont.families(root))
    except Exception:
        return None
    for name in candidates:
        if name in available:
            return name
    return None


# Build the font table for a theme against a live root.
def build_fonts(root, theme):
    if theme.native:
        return {}
    family = pick_family(root, ("Segoe UI", "Helvetica Neue", "DejaVu Sans",
                                "Noto Sans", "Arial"))
    mono = pick_family(root, ("Cascadia Mono", "SF Mono", "DejaVu Sans Mono",
                              "Consolas", "Menlo", "Courier New"))
    size = theme.fonts
    if family is None:
        body = small = ("TkDefaultFont", size["body"])
        title = ("TkDefaultFont", size["title"], "bold")
    else:
        body = (family, size["body"])
        small = (family, size["small"])
        title = (family, size["title"], "bold")
    mono = (mono, size["mono"]) if mono else ("TkFixedFont", size["mono"])
    return {"body": body, "small": small, "title": title, "mono": mono}


# Widget factory. The layout code asks for a button or a section and gets the
# widget the active look needs, so there is one layout and two skins instead
# of two layouts.
class Skin:
    def __init__(self, root, theme):
        self.root = root
        self.theme = theme
        self.fonts = build_fonts(root, theme)
        self.style = ttk.Style(root)
        if theme.native:
            self._apply_classic()
        else:
            self._apply_modern()

    # Keep the classic look on the platform theme; only the fonts are named so
    # the role styles stay consistent with the rest of the window.
    def _apply_classic(self):
        try:
            self.style.configure("Accent.TButton", padding=(GAP_MD, GAP_XS))
            self.style.configure("Danger.TButton", padding=(GAP_MD, GAP_XS))
            self.style.configure("Ghost.TButton", padding=(GAP_MD, GAP_XS))
            self.style.configure("Title.TLabel", font=("TkDefaultFont", 12, "bold"))
            self.style.configure("Muted.TLabel", foreground="#666666")
            self.style.configure("Mono.TLabel", font=("TkFixedFont", 10))
        except tk.TclError:
            pass

    # Configure ttk so the comboboxes, notebook and scrollbars match the skin.
    def _apply_modern(self):
        c = self.theme.colors
        try:
            self.style.theme_use("clam")
        except tk.TclError:
            pass
        self.style.configure(".", background=c["bg"], foreground=c["fg"],
                             fieldbackground=c["sunken"], bordercolor=c["border"],
                             lightcolor=c["bg"], darkcolor=c["bg"],
                             focuscolor=c["accent"], font=self.fonts["body"])
        self.style.configure("TCombobox", fieldbackground=c["sunken"],
                             background=c["panel"], foreground=c["fg"],
                             arrowcolor=c["muted"], bordercolor=c["border"],
                             padding=(GAP_SM, GAP_XS))
        self.style.map("TCombobox",
                       fieldbackground=[("readonly", c["sunken"])],
                       foreground=[("readonly", c["fg"])],
                       bordercolor=[("focus", c["accent"])])
        self.style.configure("TNotebook", background=c["bg"], borderwidth=0,
                             tabmargins=(0, GAP_XS, 0, 0))
        self.style.configure("TNotebook.Tab", background=c["panel"],
                             foreground=c["muted"], padding=(GAP_MD, GAP_SM),
                             borderwidth=0)
        self.style.map("TNotebook.Tab",
                       background=[("selected", c["bg"])],
                       foreground=[("selected", c["fg"])])
        self.style.configure("Vertical.TScrollbar", background=c["panel"],
                             troughcolor=c["sunken"], bordercolor=c["bg"],
                             arrowcolor=c["muted"], borderwidth=0)
        self.style.configure("Horizontal.TScrollbar", background=c["panel"],
                             troughcolor=c["sunken"], bordercolor=c["bg"],
                             arrowcolor=c["muted"], borderwidth=0)
        self.root.configure(background=c["bg"])

    # The colour for a role, or None when this theme has no opinion.
    def color(self, role):
        return self.theme.color(role)

    # Translate ttk-only options into their tk equivalents. "padding" is a
    # ttk.Frame option; tk.Frame only understands padx and pady, and passing
    # it through raises TclError: unknown option "-padding".
    @staticmethod
    def _tk_opts(kwargs):
        options = dict(kwargs)
        if "padding" in options:
            pad = options.pop("padding")
            if isinstance(pad, (tuple, list)):
                sides = list(pad) + [0] * (4 - len(pad))
                options["padx"] = sides[0]
                options["pady"] = sides[1]
            else:
                options["padx"] = pad
                options["pady"] = pad
        return options

    # A plain container. Modern uses tk.Frame for exact colours; classic hands
    # back a ttk.Frame so the platform keeps drawing it.
    def frame(self, parent, **kwargs):
        if self.theme.native:
            return ttk.Frame(parent, **kwargs)
        return tk.Frame(parent, bg=self.theme.color("bg"),
                        **self._tk_opts(kwargs))

    # A sunken surface for text panes and list bodies.
    def panel(self, parent, **kwargs):
        if self.theme.native:
            return ttk.Frame(parent, relief="solid", borderwidth=1, **kwargs)
        return tk.Frame(parent, bg=self.theme.color("sunken"),
                        highlightbackground=self.theme.color("border"),
                        highlightthickness=1, bd=0, **self._tk_opts(kwargs))

    # A text label. Role picks the treatment: normal, muted, small, title, mono.
    def label(self, parent, text="", role="normal", anchor="w", **kwargs):
        if self.theme.native:
            style = {"title": "Title.TLabel", "muted": "Muted.TLabel",
                     "small": "Muted.TLabel", "mono": "Mono.TLabel"}.get(role, "TLabel")
            return ttk.Label(parent, text=text, anchor=anchor, style=style,
                             **kwargs)
        font = {"title": "title", "small": "small", "mono": "mono"}.get(role, "body")
        color = self.theme.color("muted") if role in ("muted", "small") \
            else self.theme.color("fg")
        return tk.Label(parent, text=text, bg=self.theme.color("bg"), fg=color,
                        anchor=anchor, font=self.fonts[font], justify="left",
                        **kwargs)

    # A button. Role picks the treatment: primary, normal, danger, ghost.
    def button(self, parent, text, command=None, role="normal", **kwargs):
        if self.theme.native:
            style = {"primary": "Accent.TButton", "danger": "Danger.TButton",
                     "ghost": "Ghost.TButton"}.get(role, "TButton")
            return ttk.Button(parent, text=text, command=command, style=style,
                              **kwargs)
        bg = {"primary": self.theme.color("accent"),
              "danger": self.theme.color("err"),
              "ghost": self.theme.color("panel")}.get(role, self.theme.color("panel"))
        fg = self.theme.color("accent_fg") if role in ("primary", "danger") \
            else self.theme.color("fg")
        return tk.Button(parent, text=text, command=command, font=self.fonts["body"],
                         bd=0, padx=GAP_MD, pady=GAP_SM - 2, cursor="hand2",
                         relief="flat", bg=bg, fg=fg,
                         activebackground=self.theme.color("active"),
                         activeforeground=fg,
                         highlightbackground=self.theme.color("border"),
                         highlightthickness=1, **kwargs)

    # A single line text entry.
    def entry(self, parent, textvar, width=12, **kwargs):
        if self.theme.native:
            return ttk.Entry(parent, textvariable=textvar, width=width, **kwargs)
        return tk.Entry(parent, textvariable=textvar, width=width, bd=0,
                        relief="flat", font=self.fonts["mono"],
                        bg=self.theme.color("sunken"), fg=self.theme.color("fg"),
                        insertbackground=self.theme.color("fg"),
                        highlightthickness=1,
                        highlightbackground=self.theme.color("border"),
                        highlightcolor=self.theme.color("accent"), **kwargs)

    # A read only dropdown. Both looks use ttk, only the colours differ.
    def combo(self, parent, values, textvar, width=10, **kwargs):
        return ttk.Combobox(parent, values=values, textvariable=textvar,
                            state="readonly", width=width, **kwargs)

    # A vertically scrollable region. Returns the canvas to pack and the inner
    # frame to fill. Packing content straight into a notebook tab is not safe:
    # when the content is taller than the tab, pack hands the leftover space to
    # the first children and silently squeezes the rest down to one pixel, so
    # whole sections disappear instead of being reachable.
    def scrollable(self, parent, background=None):
        holder = self.frame(parent)
        holder.columnconfigure(0, weight=1)
        holder.rowconfigure(0, weight=1)
        canvas = tk.Canvas(holder, highlightthickness=0, bd=0,
                           background=background or self.theme.color("bg"))
        canvas.grid(row=0, column=0, sticky="nsew")
        bar = ttk.Scrollbar(holder, orient="vertical", command=canvas.yview)
        bar.grid(row=0, column=1, sticky="ns")
        canvas.configure(yscrollcommand=bar.set)
        inner = self.frame(canvas)
        window = canvas.create_window((0, 0), window=inner, anchor="nw")
        # Keep the inner frame as wide as the viewport, so wrapping never
        # depends on how wide the content happens to be.
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(
            window, width=event.width))
        inner.bind("<Configure>", lambda _event: canvas.configure(
            scrollregion=canvas.bbox("all")))
        # Mouse wheel over the region scrolls it, on Windows and X11 alike.
        for widget in (canvas, inner):
            widget.bind("<MouseWheel>", lambda event: canvas.yview_scroll(
                -1 * (event.delta // 120) if event.delta else -1, "units"))
            widget.bind("<Button-4>", lambda _event: canvas.yview_scroll(-1, "units"))
            widget.bind("<Button-5>", lambda _event: canvas.yview_scroll(1, "units"))
        return holder, inner, canvas

    # A titled group, packed into the given parent. Classic uses a real
    # LabelFrame; modern uses a small caption above a flat panel. In both cases
    # the returned body is packed into the group, or it would never be laid out
    # and the whole section would collapse to a single pixel.
    def section(self, parent, title):
        if self.theme.native:
            box = ttk.LabelFrame(parent, text=title, padding=GAP_SM)
            box.pack(fill="x", pady=(GAP_MD, 0))
            body = ttk.Frame(box)
            body.pack(fill="both", expand=True)
            return box, body
        outer = tk.Frame(parent, bg=self.theme.color("bg"))
        outer.pack(fill="x", pady=(GAP_MD, 0))
        tk.Label(outer, text=title, bg=self.theme.color("bg"),
                 fg=self.theme.color("muted"),
                 font=self.fonts["small"]).pack(anchor="w", padx=2)
        body = self.panel(outer)
        body.pack(fill="both", expand=True, pady=(GAP_XS, 2))
        return outer, body

    # A read only multi line text pane.
    def text(self, parent, height=8, **kwargs):
        if self.theme.native:
            return tk.Text(parent, height=height, wrap="none", relief="solid",
                           borderwidth=1, **kwargs)
        return tk.Text(parent, height=height, wrap="none", bd=0, relief="flat",
                       highlightthickness=1,
                       highlightbackground=self.theme.color("border"),
                       bg=self.theme.color("sunken"), fg=self.theme.color("fg"),
                       insertbackground=self.theme.color("fg"),
                       font=self.fonts["mono"], **kwargs)

    # A single line list.
    def listbox(self, parent, height=10, **kwargs):
        if self.theme.native:
            return tk.Listbox(parent, height=height, relief="solid",
                              borderwidth=1, **kwargs)
        return tk.Listbox(parent, height=height, bd=0, relief="flat",
                          highlightthickness=1,
                          highlightbackground=self.theme.color("border"),
                          bg=self.theme.color("sunken"),
                          fg=self.theme.color("fg"),
                          selectbackground=self.theme.color("accent"),
                          selectforeground=self.theme.color("accent_fg"),
                          font=self.fonts["mono"], **kwargs)

    # A vertical scrollbar wired to a widget that supports yview.
    def scrollbar(self, parent, widget):
        bar = ttk.Scrollbar(parent, orient="vertical", command=widget.yview)
        widget.config(yscrollcommand=bar.set)
        return bar

    # Give a text pane its semantic colours, when this theme has any.
    def tag_log(self, widget):
        if self.theme.native:
            widget.tag_configure("FAIL", foreground="#b00020")
            widget.tag_configure("WARN", foreground="#a06000")
            widget.tag_configure("OK", foreground="#0a6b2e")
            return
        widget.tag_configure("OK", foreground=self.theme.color("ok"))
        widget.tag_configure("FAIL", foreground=self.theme.color("err"))
        widget.tag_configure("WARN", foreground=self.theme.color("warn"))
        widget.tag_configure("INFO", foreground=self.theme.color("muted"))
        widget.tag_configure("time", foreground=self.theme.color("muted"))


# Return the settings path, so tests can point it somewhere harmless.
def settings_path(root_dir=None):
    base = root_dir or os.path.expanduser(SETTINGS_DIR)
    return os.path.join(base, SETTINGS_NAME)


# Read the saved settings, falling back to the defaults on any problem. A
# broken or hostile settings file must never keep the tool from starting.
def load_settings(path=None):
    data = {"style": STYLE_CLASSIC, "host": DEFAULT_HOST, "port": DEFAULT_PORT}
    try:
        with open(path or settings_path(), "r", encoding="utf-8") as stream:
            saved = json.load(stream)
    except (OSError, ValueError):
        return data
    if not isinstance(saved, dict):
        return data
    if saved.get("style") in STYLE_CHOICES:
        data["style"] = saved["style"]
    if isinstance(saved.get("host"), str) and saved["host"].strip():
        data["host"] = saved["host"].strip()
    port = saved.get("port")
    if isinstance(port, int) and not isinstance(port, bool) and 0 < port < 65536:
        data["port"] = port
    return data


# Save the settings, reporting whether they were written. A failure is not
# fatal: the tool simply forgets the choice next time.
def save_settings(data, path=None):
    path = path or settings_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
    except OSError:
        return False
    return True


# One connection to the device: a request is one line and the reply is one
# line, except for "download", where the client sends raw bytes after DATA.
class FastbootClient:
    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT, timeout=TIMEOUT):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock = None
        self.buffer = b""
        # Every request runs on a worker thread while the UI thread may close
        # the socket, so socket use is serialized. Without this, clicking a
        # reboot button could null the socket between the worker's send and
        # its read, which surfaced as "'NoneType' object has no attribute
        # 'recv'".
        self._lock = threading.RLock()

    # Open the socket, reporting the failure instead of raising.
    def connect(self):
        self.close()
        try:
            sock = socket.create_connection((self.host, self.port), self.timeout)
        except OSError as exc:
            return False, f"无法连接 {self.host}:{self.port}：{exc}"
        with self._lock:
            self.sock = sock
            self.buffer = b""
        return True, f"已连接 {self.host}:{self.port}"

    # Report whether the socket is currently usable.
    def connected(self):
        with self._lock:
            return self.sock is not None

    # Drop the socket, ignoring an already closed one.
    def close(self):
        with self._lock:
            sock, self.sock = self.sock, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    # Read one newline-terminated reply from the device.
    def _readline(self):
        while b"\n" not in self.buffer:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise OSError("设备已断开连接")
            self.buffer += chunk
        line, self.buffer = self.buffer.split(b"\n", 1)
        return line.decode("utf-8", "replace").strip()

    # Send one command and return the raw reply line.
    def request(self, command):
        with self._lock:
            if self.sock is None:
                raise OSError("尚未连接设备")
            self.sock.sendall((command + "\n").encode("utf-8"))
            return self._readline()

    # Run a command that must succeed, raising OSError on a FAIL reply.
    def command(self, command):
        reply = self.request(command)
        if reply.startswith("FAIL"):
            raise OSError(reply[4:] or "设备拒绝了该请求")
        return reply

    # Download a file into the device, then return the flash reply. Progress is
    # reported through the callback because a large image takes a while and the
    # window would otherwise look frozen for the whole transfer.
    def flash(self, partition, path, progress=None):
        with open(path, "rb") as handle:
            data = handle.read()
        size = len(data)
        with self._lock:
            reply = self.request(f"download:{size:08x}")
            if not reply.startswith("DATA"):
                raise OSError(reply[4:] or "设备拒绝下载")
            step = max(1, size // 20)
            sent = 0
            while sent < size:
                self.sock.sendall(data[sent:sent + step])
                sent += step
                if progress is not None:
                    progress(min(sent, size), size)
            if progress is not None:
                progress(size, size)
            # The device acknowledges the payload with its own OKAY line.
            self._readline()
            reply = self.command(f"flash:{partition}")
        return reply

    # Ask the device to erase one partition.
    def erase(self, partition):
        return self.command(f"erase:{partition}")

    # Change the bootloader trust domain.
    def flashing(self, option):
        return self.command(f"flashing {option}")

    # Send a command and then hang up. The device reboots, so the connection
    # is finished either way; closing here keeps the UI thread from racing the
    # worker that is still talking to the device.
    def reboot(self, target=""):
        try:
            return self.command(f"reboot{target}")
        finally:
            self.close()

    # Ask the device to power off, then hang up.
    def powerdown(self):
        try:
            return self.command("powerdown")
        finally:
            self.close()

    # Read one getvar value, reporting the raw reply for unknown names.
    def getvar(self, name):
        return self.request(f"getvar:{name}")

    # Read every bootloader variable the device exposes.
    def all_variables(self):
        values = {}
        for name, _caption in VARIABLE_ROWS:
            reply = self.getvar(name)
            values[name] = reply[4:] if reply.startswith("OKAY") else reply
        return values


# The graphical front end: a connection bar, a status line, a device tab, a
# process tab and a log pane. One layout, skinned by the active look.
class FastbootGui:
    def __init__(self, root, host, port, style=STYLE_CLASSIC, settings_file=None):
        self.root = root
        self.client = FastbootClient(host, port)
        self.events = queue.Queue()
        self.settings_file = settings_file
        self.style_name = style if style in STYLE_CHOICES else STYLE_CLASSIC
        self.connected = False
        self.value_labels = {}
        self.device_buttons = []
        self.log_lines = []
        self.root.title("PySpOS Fastboot")
        self.root.geometry("880x660")
        self.root.minsize(760, 540)
        self.skin = Skin(self.root, THEMES[self.style_name])
        self.outer = self.skin.frame(self.root, padding=GAP_MD)
        self.outer.pack(fill="both", expand=True)
        self._populate()
        self._sync_state()
        self.root.after(100, self._drain)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # Build the whole window content into self.outer.
    def _populate(self):
        self.outer.columnconfigure(0, weight=1)
        self.outer.rowconfigure(2, weight=1)
        self._build_topbar()
        self._build_status()
        self._build_body()
        self._build_log()
        self._replay_log()

    # Throw the current widgets away and build them again with a new skin. The
    # outer container is rebuilt too, because a ttk.Frame cannot become a
    # tk.Frame just by reconfiguring it.
    def _rebuild(self):
        self.outer.destroy()
        self.value_labels = {}
        self.device_buttons = []
        self.skin = Skin(self.root, THEMES[self.style_name])
        self.outer = self.skin.frame(self.root, padding=GAP_MD)
        self.outer.pack(fill="both", expand=True)
        self._populate()
        self._sync_state()

    # Connection bar: identity, endpoint fields, actions and the look switch.
    def _build_topbar(self):
        bar = self.skin.frame(self.outer)
        bar.grid(row=0, column=0, sticky="ew", pady=(0, GAP_SM))
        bar.columnconfigure(2, weight=1)

        titles = self.skin.frame(bar)
        titles.grid(row=0, column=0, rowspan=2, sticky="w")
        self.skin.label(titles, "PySpOS Fastboot", role="title").pack(anchor="w")
        self.skin.label(titles, "fastboot 主机客户端", role="small").pack(anchor="w")

        looks = self.skin.frame(bar)
        looks.grid(row=0, column=1, rowspan=2, sticky="w", padx=GAP_LG)
        self.skin.label(looks, "界面").pack(side="left", padx=(0, GAP_XS))
        self.style_var = tk.StringVar(value=STYLE_LABELS[self.style_name])
        style_box = self.skin.combo(
            looks, tuple(STYLE_LABELS[s] for s in STYLE_CHOICES), self.style_var,
            width=6)
        style_box.pack(side="left")
        style_box.bind("<<ComboboxSelected>>", self._on_style_picked)

        fields = self.skin.frame(bar)
        fields.grid(row=0, column=2, rowspan=2, sticky="e")
        self.skin.label(fields, "设备").pack(side="left", padx=(0, GAP_XS))
        self.host_var = tk.StringVar(value=self.client.host)
        self.skin.entry(fields, self.host_var, width=13).pack(side="left",
                                                               padx=(0, GAP_SM))
        self.skin.label(fields, "端口").pack(side="left", padx=(0, GAP_XS))
        self.port_var = tk.StringVar(value=str(self.client.port))
        self.skin.entry(fields, self.port_var, width=6).pack(side="left",
                                                             padx=(0, GAP_SM))
        self.connect_btn = self.skin.button(fields, "连接", self._on_connect,
                                            role="primary")
        self.connect_btn.pack(side="left", padx=(0, GAP_XS))
        self.disconnect_btn = self.skin.button(fields, "断开",
                                               self._on_disconnect)
        self.disconnect_btn.pack(side="left")

    # One line summarising the trust domain, filled in after a connect.
    def _build_status(self):
        strip = self.skin.frame(self.outer)
        strip.grid(row=1, column=0, sticky="ew", pady=(0, GAP_SM))
        strip.columnconfigure(3, weight=1)
        self.dot = self.skin.label(strip, "●", role="normal")
        self.dot.grid(row=0, column=0, padx=(0, GAP_XS))
        self.state_label = self.skin.label(strip, "未连接", role="normal")
        self.state_label.grid(row=0, column=1, sticky="w")
        self.summary_label = self.skin.label(strip, "", role="small")
        self.summary_label.grid(row=0, column=2, sticky="w", padx=GAP_MD)
        self.hint_label = self.skin.label(strip, "设备端需处于 fastboot 模式",
                                          role="small")
        self.hint_label.grid(row=0, column=4, sticky="e")

    # The two tabs.
    def _build_body(self):
        holder = self.skin.frame(self.outer)
        holder.grid(row=2, column=0, sticky="nsew")
        holder.columnconfigure(0, weight=1)
        holder.rowconfigure(0, weight=1)
        self.notebook = ttk.Notebook(holder)
        self.notebook.grid(row=0, column=0, sticky="nsew")
        self._build_device_tab()
        self._build_process_tab()

    # A small explanatory line under a section. The wrap length follows the
    # widget width, because ttk.Label does not wrap on its own and would
    # simply cut the text off at the column edge.
    def _hint(self, parent, text, row, column=0, columnspan=1):
        label = self.skin.label(parent, text, role="small", wraplength=160)
        label.grid(row=row, column=column, columnspan=columnspan, sticky="w",
                   padx=GAP_SM, pady=(GAP_XS, GAP_SM))

        def follow(event, widget=label):
            wanted = max(120, event.width - GAP_MD)
            try:
                if abs(int(widget.cget("wraplength")) - wanted) > 8:
                    widget.configure(wraplength=wanted)
            except (tk.TclError, ValueError):
                pass

        label.bind("<Configure>", follow)
        return label

    # Device tab: variables on the left, partition work and the trust domain
    # on the right, all inside a scrollable region so a short window never
    # squeezes a section out of existence.
    def _build_device_tab(self):
        tab = self.skin.frame(self.notebook, padding=GAP_MD)
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)
        holder, columns, _canvas = self.skin.scrollable(tab)
        holder.grid(row=0, column=0, sticky="nsew")
        columns.columnconfigure(0, weight=3, uniform="dev")
        columns.columnconfigure(1, weight=2, uniform="dev")

        left = self.skin.frame(columns)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, GAP_MD))
        _box, body = self.skin.section(left, "Bootloader 变量")
        body.grid_columnconfigure(1, weight=1)
        for row, (name, caption) in enumerate(VARIABLE_ROWS):
            self.skin.label(body, caption, role="small").grid(
                row=row, column=0, sticky="w", padx=(GAP_SM, GAP_MD), pady=1)
            value = self.skin.label(body, "—", role="mono")
            value.grid(row=row, column=1, sticky="w", padx=(0, GAP_SM), pady=1)
            self.value_labels[name] = value
        refresh = self.skin.button(body, "重新读取", self._on_refresh)
        refresh.grid(row=len(VARIABLE_ROWS), column=0, columnspan=2, sticky="w",
                     padx=GAP_SM, pady=(GAP_SM, GAP_SM))
        self.device_buttons.append(refresh)

        right = self.skin.frame(columns)
        right.grid(row=0, column=1, sticky="nsew")

        _box, ops = self.skin.section(right, "分区操作")
        ops.grid_columnconfigure(1, weight=1)
        self.skin.label(ops, "目标槽位").grid(row=0, column=0, sticky="w",
                                        padx=(GAP_SM, GAP_XS), pady=GAP_SM)
        self.slot_var = tk.StringVar(value="slot_a")
        slot_box = self.skin.combo(ops, ("slot_a", "slot_b"), self.slot_var, width=8)
        slot_box.grid(row=0, column=1, sticky="w", padx=(0, GAP_SM), pady=GAP_SM)
        flash_btn = self.skin.button(ops, "刷写镜像…", self._on_flash)
        flash_btn.grid(row=1, column=0, sticky="w", padx=GAP_SM, pady=GAP_XS)
        erase_btn = self.skin.button(ops, "擦除数据", self._on_erase)
        erase_btn.grid(row=1, column=1, sticky="w", padx=GAP_SM, pady=GAP_XS)
        self.device_buttons.extend([slot_box, flash_btn, erase_btn])
        self._hint(ops, "刷写会验签并直接安装进目标槽位，未通过则拒绝", row=2, columnspan=2)

        _box, trust = self.skin.section(right, "信任域与电源")
        trust.grid_columnconfigure(1, weight=1)
        unlock_btn = self.skin.button(trust, "解锁 Bootloader",
                                      lambda: self._on_flashing("unlock"),
                                      role="danger")
        unlock_btn.grid(row=0, column=0, columnspan=2, sticky="w",
                        padx=GAP_SM, pady=GAP_SM)
        lock_btn = self.skin.button(trust, "锁定",
                                    lambda: self._on_flashing("lock"))
        lock_btn.grid(row=1, column=0, sticky="w", padx=GAP_SM, pady=GAP_XS)
        reboot_btn = self.skin.button(trust, "重启", self._on_reboot)
        reboot_btn.grid(row=1, column=1, sticky="w", padx=GAP_SM, pady=GAP_XS)
        bootloader_btn = self.skin.button(trust, "重启到 fastboot",
                                          self._on_reboot_bl)
        bootloader_btn.grid(row=2, column=0, sticky="w", padx=GAP_SM, pady=GAP_XS)
        power_btn = self.skin.button(trust, "关机", self._on_poweroff)
        power_btn.grid(row=2, column=1, sticky="w", padx=GAP_SM, pady=GAP_XS)
        self.device_buttons.extend([unlock_btn, lock_btn, reboot_btn,
                                    bootloader_btn, power_btn])
        self._hint(trust, "解锁会清空用户数据；槽位无签名镜像时锁定会被拒绝",
                   row=3, columnspan=2)

        self.notebook.add(tab, text="设备")

    # Process tab: a column header, the table, and the signal actions.
    def _build_process_tab(self):
        tab = self.skin.frame(self.notebook, padding=GAP_MD)
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)

        header = self.skin.frame(tab)
        header.grid(row=0, column=0, sticky="ew", pady=(0, GAP_XS))
        for col, title in enumerate(("PID", "PPID", "状态", "类型", "命令")):
            self.skin.label(header, title, role="small").grid(
                row=0, column=col, sticky="w", padx=(GAP_SM, GAP_MD))
        refresh_btn = self.skin.button(header, "刷新", self._on_refresh_ps)
        refresh_btn.grid(row=0, column=5, sticky="e", padx=GAP_SM)
        self.device_buttons.append(refresh_btn)

        holder = self.skin.panel(tab)
        holder.grid(row=1, column=0, sticky="nsew")
        holder.rowconfigure(0, weight=1)
        holder.columnconfigure(0, weight=1)
        self.pid_list = self.skin.listbox(holder, height=14, selectmode="browse")
        self.pid_list.grid(row=0, column=0, sticky="nsew", padx=GAP_XS, pady=GAP_XS)
        self.pid_list.bind("<Double-Button-1>", lambda _event: self._on_signal())
        self.skin.scrollbar(holder, self.pid_list).grid(row=0, column=1,
                                                        sticky="ns", pady=GAP_XS)

        actions = self.skin.frame(tab)
        actions.grid(row=2, column=0, sticky="ew", pady=(GAP_SM, 0))
        self.skin.label(actions, "信号").grid(row=0, column=0,
                                        padx=(GAP_SM, GAP_XS))
        self.sig_var = tk.StringVar(value="SIGTERM")
        sig_box = self.skin.combo(actions, SIGNALS, self.sig_var, width=10)
        sig_box.grid(row=0, column=1, padx=(0, GAP_SM))
        send_btn = self.skin.button(actions, "发送信号", self._on_signal,
                                    role="primary")
        send_btn.grid(row=0, column=2, padx=(0, GAP_SM))
        self.skin.label(actions, "双击进程行可直接发送", role="small").grid(
            row=0, column=3, sticky="w", padx=GAP_SM)
        self.device_buttons.extend([sig_box, send_btn])

        self.notebook.add(tab, text="进程信号")

    # Log pane at the bottom, with a clear action.
    def _build_log(self):
        box = self.skin.frame(self.outer)
        box.grid(row=3, column=0, sticky="ew", pady=(GAP_MD, 0))
        box.columnconfigure(0, weight=1)

        head = self.skin.frame(box)
        head.grid(row=0, column=0, sticky="ew", pady=(0, GAP_XS))
        self.skin.label(head, "日志", role="title").grid(row=0, column=0, sticky="w")
        self.skin.button(head, "清空", self._on_clear_log).grid(row=0, column=1,
                                                                sticky="e")

        holder = self.skin.panel(box)
        holder.grid(row=1, column=0, sticky="ew")
        holder.columnconfigure(0, weight=1)
        self.log_text = self.skin.text(holder, height=9)
        self.log_text.grid(row=0, column=0, sticky="ew", padx=GAP_XS, pady=GAP_XS)
        self.skin.scrollbar(holder, self.log_text).grid(row=0, column=1,
                                                        sticky="ns", pady=GAP_XS)
        self.skin.tag_log(self.log_text)

    # Show the buffered log lines again after the window was rebuilt.
    def _replay_log(self):
        for level, text in self.log_lines[-LOG_HISTORY:]:
            self._log(text, level, remember=False)

    # Append one timestamped line to the log pane, coloured by level.
    def _log(self, text, level="INFO", remember=True):
        if remember:
            self.log_lines.append((level, text))
            if len(self.log_lines) > LOG_HISTORY:
                del self.log_lines[:-LOG_HISTORY]
        stamp = time.strftime("%H:%M:%S")
        self.log_text.config(state="normal")
        self.log_text.insert("end", f"{stamp} ", "time")
        self.log_text.insert("end", f"{level:<5}", level)
        self.log_text.insert("end", f"{text}\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    # Enable or disable everything that needs a live connection.
    def _sync_state(self):
        live = self.connected
        for widget in self.device_buttons:
            try:
                widget.config(state="normal" if live else "disabled")
            except tk.TclError:
                pass
        self.connect_btn.config(state="disabled" if live else "normal")
        self.disconnect_btn.config(state="normal" if live else "disabled")
        color = self.skin.color("ok" if live else "muted")
        if color and not self.skin.theme.native:
            self.dot.config(fg=color)
        self.state_label.config(text="已连接" if live else "未连接")
        if not live:
            self.summary_label.config(text="")
        self.hint_label.config(text="" if live else "设备端需处于 fastboot 模式")

    # Queue work for the UI thread and report the result in the log. The
    # optional apply callback runs on the UI thread, because Tk forbids widget
    # access from anywhere else. Workers must only fetch data.
    def _run(self, label, work, apply=None):
        def task():
            try:
                result = work()
                self.events.put((label, True, result, apply))
            except Exception as exc:
                self.events.put((label, False, str(exc), None))
        threading.Thread(target=task, daemon=True).start()

    # Move finished background results into the widgets. A label of None means
    # a progress note rather than a finished result.
    def _drain(self):
        try:
            while True:
                label, ok, message, apply = self.events.get_nowait()
                if ok is None:
                    self._log(label, "INFO")
                    continue
                if ok:
                    # A worker may return (message, payload): the log gets the
                    # short message, the callback gets the payload.
                    payload = message
                    if isinstance(message, tuple):
                        message, payload = message
                    if apply is not None:
                        try:
                            apply(payload)
                        except Exception as exc:
                            self._log(f"{label}: 更新界面失败: {exc}", "FAIL")
                    self._log(f"{label}: {message}", "OK")
                else:
                    self._log(f"{label}: {message}", "FAIL")
                # A finished request may have closed the socket, for example
                # after a reboot, so the button states have to follow.
                if self.connected and not self.client.connected():
                    self.connected = False
                    self._sync_state()
        except queue.Empty:
            pass
        self.root.after(100, self._drain)

    # Connect to the device, then read its variables.
    def _on_connect(self):
        host = self.host_var.get().strip() or DEFAULT_HOST
        try:
            port = int(self.port_var.get().strip() or DEFAULT_PORT)
        except ValueError:
            self._log("端口必须是数字", "FAIL")
            return
        if not 0 < port < 65536:
            self._log("端口超出范围", "FAIL")
            return
        self.client.host, self.client.port = host, port
        self._run("连接", self._connect_then_read)
        self.connected = True
        self._sync_state()
        # The variable table needs an open socket, so it follows the connect.
        self.root.after(300, self._on_refresh)

    # Open the socket and pull the variable table once it is up.
    def _connect_then_read(self):
        ok, message = self.client.connect()
        if not ok:
            raise OSError(message)
        return message

    # Close the socket and forget the device.
    def _on_disconnect(self):
        self.client.close()
        self.connected = False
        self._sync_state()
        self._log("已断开", "INFO")

    # Fetch the variable table. Runs on a worker thread, so it must not touch
    # any widget; _apply_vars does that on the UI thread.
    def _fetch_vars(self):
        return self.client.all_variables()

    # Paint the variable table into the value labels.
    def _apply_vars(self, values):
        for name, label in self.value_labels.items():
            label.config(text=values.get(name) or "—")
        unlocked = values.get("unlocked", "")
        slot = values.get("current-slot", "?")
        pending = values.get("pending-slot", "")
        if unlocked == "yes":
            summary = f"已解锁 · 当前槽位 {slot}"
        elif unlocked == "no":
            summary = f"已锁定 · 当前槽位 {slot}"
        else:
            summary = f"状态未知 · 当前槽位 {slot}"
        if pending:
            summary += f" · 已标记下次启动 {pending}"
        self.summary_label.config(text=summary)

    # Read variables on a background thread and paint them when they arrive.
    def _on_refresh(self):
        def job():
            values = self._fetch_vars()
            return f"读取 {len(values)} 个变量", values

        self._run("getvar", job, self._apply_vars)

    # Flash a chosen image file into the selected slot.
    def _on_flash(self):
        path = filedialog.askopenfilename(
            title="选择要刷写的镜像",
            filetypes=[("更新包", "*.zip"), ("镜像", "*.img *.bin"),
                       ("全部文件", "*.*")])
        if not path:
            return
        slot = self.slot_var.get()

        def report(done, total):
            percent = int(done * 100 / total) if total else 100
            self.events.put((f"传输 {percent}%", None, None))

        def job():
            reply = self.client.flash(slot, path, progress=report)
            return reply[4:]

        self._run(f"刷写 {slot}", job)

    # Erase the selected slot after an explicit confirmation.
    def _on_erase(self):
        slot = self.slot_var.get()
        if not messagebox.askyesno(
                "确认擦除",
                f"确定要擦除 {slot} 的数据吗？\n\n此操作不可撤销。"):
            return
        self._run(f"擦除 {slot}", lambda: self.client.erase(slot)[4:])

    # Change the bootloader trust domain.
    def _on_flashing(self, option):
        if option == "unlock" and not messagebox.askyesno(
                "确认解锁", "解锁 Bootloader 会清空用户数据。\n\n确定继续吗？"):
            return
        if option == "lock" and not messagebox.askyesno(
                "确认锁定",
                "锁定后只接受已签名镜像。\n\n槽位没有签名镜像时会被拒绝。\n\n继续吗？"):
            return
        self._run(option, lambda: self.client.flashing(option)[4:])

    # Reboot the device. The client hangs up itself once the request is sent.
    def _on_reboot(self):
        self._run("重启", lambda: self.client.reboot()[4:])

    # Reboot back into fastboot.
    def _on_reboot_bl(self):
        self._run("重启到 fastboot", lambda: self.client.reboot("-bootloader")[4:])

    # Power the device off.
    def _on_poweroff(self):
        self._run("关机", lambda: self.client.powerdown()[4:])

    # Empty the log pane.
    def _on_clear_log(self):
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")
        self.log_lines.clear()

    # Ask the device for the process list over the OEM extension. Runs on a
    # worker thread and returns the rows; _apply_ps paints them.
    def _fetch_ps(self):
        reply = self.client.request("oem pyspos-ps")
        if not reply.startswith("OKAY"):
            raise OSError(reply[4:] or "设备不支持该命令")
        body = reply[4:]
        return [] if body.startswith("(") else body.split(";")

    # Paint the process rows into the list.
    def _apply_ps(self, rows):
        self.pid_list.delete(0, "end")
        for line in rows:
            self.pid_list.insert("end", line)

    # Refresh the process list on a background thread.
    def _on_refresh_ps(self):
        def job():
            rows = self._fetch_ps()
            return f"共 {len(rows)} 个进程", rows

        self._run("进程列表", job, self._apply_ps)

    # Send the selected signal to the highlighted process.
    def _on_signal(self):
        selection = self.pid_list.curselection()
        if not selection:
            self._log("请先选中一个进程", "FAIL")
            return
        row = self.pid_list.get(selection[0]).split()
        if not row:
            self._log("这一行没有 PID", "FAIL")
            return
        pid, signame = row[0], self.sig_var.get()
        self._run(f"信号 {pid} {signame}",
                  lambda: self.client.request(
                      f"oem pyspos-signal {pid} {signame}")[4:])

    # Switch between the two looks and remember the choice.
    def _on_style_picked(self, _event=None):
        wanted = self.style_var.get()
        for name, text in STYLE_LABELS.items():
            if text == wanted:
                if name != self.style_name:
                    self.style_name = name
                    self._rebuild()
                    self._log(f"已切换到{STYLE_LABELS[name]}界面", "INFO")
                self._save_settings()
                return

    # Persist the endpoint and the look for the next run.
    def _save_settings(self):
        try:
            port = int(self.port_var.get().strip() or self.client.port)
        except ValueError:
            port = self.client.port
        save_settings({
            "style": self.style_name,
            "host": self.host_var.get().strip() or DEFAULT_HOST,
            "port": port,
        }, self.settings_file)

    # Close the socket and remember the settings before the window goes away.
    def _on_close(self):
        self._save_settings()
        self.client.close()
        self.root.destroy()


# Parse the command line and start the window.
def main(argv=None):
    parser = argparse.ArgumentParser(description="PySpOS fastboot 图形客户端")
    parser.add_argument("--host", default=None, help="设备地址")
    parser.add_argument("--port", type=int, default=None, help="设备端口")
    parser.add_argument("--style", choices=STYLE_CHOICES, default=None,
                        help="界面样式：classic 经典 / modern 现代")
    args = parser.parse_args(argv)

    saved = load_settings()
    host = args.host or saved["host"]
    port = args.port or saved["port"]
    style = args.style or saved["style"]

    try:
        root = tk.Tk()
    except Exception as exc:
        print(f"无法启动图形界面：{exc}", file=sys.stderr)
        print("请确认已安装 tkinter（Linux 需要 python3-tk）。", file=sys.stderr)
        return 1
    gui = FastbootGui(root, host, port, style)
    gui._log(f"界面：{STYLE_LABELS[gui.style_name]}", "INFO")
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
