"""Reusable controls for the display-list API.

An app keeps its controls as objects and calls scene() each frame with the
rectangle it wants them in. That is the split Ratatui draws: a control earns its
statefulness only when rebuilding it would lose something the user can notice —
a drag in progress, a caret, a hover. Choice controls therefore stay plain
display-list buttons, because the compositor already hit-tests those for us;
only continuous controls need to hold on to the pointer.

The interaction model follows immediate-mode toolkits: a control records the
rectangle it drew into, hit-tests pointer events against that same rectangle,
and once a press lands inside it keeps the pointer until the matching release —
so dragging a slider that leaves its row keeps working.
"""

from . import style
from .drawing import INVISIBLE, button, label, rectangle

# 触摸/WCAG 2.5.8 要求指针目标至少 24x24；轨道画得细，命中区仍给足高度。
TOUCH = 24
TRACK_HEIGHT = 5
THUMB_WIDTH = 12
THUMB_HEIGHT = 20


class Control:
    """Base: draw into a rectangle, answer events against the same rectangle."""

    def __init__(self):
        self.bounds = (0, 0, 0, 0)
        self.hover = False
        self.active = False        # holding the pointer, i.e. a drag is running
        self.enabled = True

    # Remember where this control ended up, so hit-testing needs no second pass
    # over the same layout maths and cannot drift from what was drawn.
    def place(self, x, y, width, height):
        self.bounds = (x, y, width, height)
        return x, y, width, height

    def contains(self, event):
        x, y, width, height = self.bounds
        return (x <= event.get("x", -1) < x + width
                and y <= event.get("y", -1) < y + height)

    # Route one event. Returns True when the caller should repaint.
    def handle(self, event):
        kind = event["type"]
        if kind == "pointer":
            return self.pointer(event)
        if kind == "key":
            return self.key(event)
        return False

    # A press inside takes the pointer; only the matching release gives it back,
    # wherever that release happens.
    def pointer(self, event):
        phase = event.get("phase")
        if phase == "press":
            self.active = self.enabled and self.contains(event)
            return self.active and self.on_press(event)
        if phase == "move":
            self.hover = self.contains(event)
            return bool(self.active) and self.on_drag(event)
        if phase == "release" and self.active:
            self.active = False
            self.on_release(event)
            # The control's own appearance changes with active, so ending a drag
            # always warrants a repaint even when no control overrides the hook.
            return True
        return False

    def on_press(self, _event):
        return False

    def on_drag(self, _event):
        return False

    def on_release(self, _event):
        return False

    def key(self, _event):
        return False

    def scene(self, x, y, width, height):
        raise NotImplementedError


class Slider(Control):
    """A value on a fixed range, set by dragging, clicking or the arrow keys.

    Keyboard follows the ARIA slider pattern: arrows move one step, Home and End
    jump to the ends, Page Up and Page Down move ten.
    """

    def __init__(self, minimum, maximum, value, step=1, on_change=None,
                 label_width=0):
        super().__init__()
        if maximum <= minimum:
            raise ValueError("slider maximum must exceed its minimum")
        self.minimum, self.maximum = minimum, maximum
        self.step = step
        self.value = self._snap(value)
        self.on_change = on_change
        self.label_width = label_width    # 数值文字占的宽度，画在轨道右侧

    # Quantise to the step and clamp, so every path into the value agrees.
    def _snap(self, value):
        stepped = round((value - self.minimum) / self.step) * self.step + self.minimum
        return max(self.minimum, min(self.maximum, stepped))

    def set(self, value):
        snapped = self._snap(value)
        if snapped == self.value:
            return False
        self.value = snapped
        if self.on_change:
            self.on_change(snapped)
        return True

    def place(self, x, y, width, height):
        # The track excludes the value text, which sits at the trailing edge.
        return super().place(x, y, width, height)

    def _track(self):
        x, y, width, height = self.bounds
        span = width - self.label_width
        track_y = y + (height - TRACK_HEIGHT) // 2
        return x, track_y, max(1, span - THUMB_WIDTH), span

    def _value_at(self, pointer_x):
        x, _track_y, track_width, _span = self._track()
        ratio = (pointer_x - x - THUMB_WIDTH / 2) / track_width
        return self.minimum + ratio * (self.maximum - self.minimum)

    def on_press(self, event):
        return self.set(self._value_at(event["x"]))

    def on_drag(self, event):
        return self.set(self._value_at(event["x"]))

    def key(self, event):
        # 方向键按 ARIA：右/上增，左/下减；Page 键各走十步，PageUp 是增。
        moves = {0x01000012: -1, 0x01000013: +1,      # Left / Up
                 0x01000015: -1, 0x01000014: +1,      # Down / Right
                 0x01000016: +10, 0x01000017: -10}    # PageUp / PageDown
        if event.get("key") == 0x01000010:            # Home
            return self.set(self.minimum)
        if event.get("key") == 0x01000011:            # End
            return self.set(self.maximum)
        move = moves.get(event.get("key"))
        return bool(move) and self.set(self.value + move * self.step)

    def scene(self, x, y, width, height):
        self.place(x, y, width, height)
        track_x, track_y, track_width, span = self._track()
        ratio = (self.value - self.minimum) / (self.maximum - self.minimum)
        filled = int(track_width * ratio)
        # The empty part of the track is the only hit target the pointer needs;
        # the whole row still reports bounds so hover reads the full height.
        items = [
            rectangle(track_x, track_y, track_width + THUMB_WIDTH, TRACK_HEIGHT,
                      style.CONTROL, TRACK_HEIGHT // 2),
            rectangle(track_x, track_y, filled + THUMB_WIDTH // 2, TRACK_HEIGHT,
                      style.CONTROL_ACTIVE if self.enabled else style.DIVIDER,
                      TRACK_HEIGHT // 2),
            rectangle(track_x + filled, track_y - (THUMB_HEIGHT - TRACK_HEIGHT) // 2,
                      THUMB_WIDTH, THUMB_HEIGHT,
                      style.TEXT if (self.hover or self.active) else style.TITLE,
                      THUMB_WIDTH // 2),
        ]
        if self.label_width:
            items.append(label(x + span, y + (height - 14) // 2,
                               f"{self.value:g}", 14, style.TEXT))
        return items


class Switch(Control):
    """An immediately effective on/off state.

    The GNOME HIG draws the line this way: a switch is for a state that applies
    the moment you touch it. Anything confirmed later is a checkbox or a button.
    """

    def __init__(self, value=False, on_change=None):
        super().__init__()
        self.value = bool(value)
        self.on_change = on_change

    def on_press(self, _event):
        if not self.enabled:
            return False
        self.value = not self.value
        if self.on_change:
            self.on_change(self.value)
        return True

    def key(self, event):
        # 空格和回车都能切换：Qt 的 Return 是 0x01000004，小键盘 Enter 是
        # 0x01000005，和 guicalc 里用的那两个码一致。
        if event.get("key") in (0x20, 0x01000004, 0x01000005):
            return self.on_press(event)
        return False

    def scene(self, x, y, width, height):
        self.place(x, y, width, height)
        knob = height - 6
        travel = width - knob - 6
        offset = travel if self.value else 0
        track = style.CONTROL_ACTIVE if self.value else style.CONTROL
        if not self.enabled:
            track = style.DIVIDER
        elif self.hover or self.active:
            track = style.CONTROL_ACTIVE if self.value else style.DIVIDER
        return [
            rectangle(x, y, width, height, track, height // 2),
            rectangle(x + 3 + offset, y + 3, knob, knob,
                      style.TEXT if self.value else style.DIM, knob // 2),
        ]


class Progress(Control):
    """A read-only bar. Not interactive: it exists so a busy screen can show how
    far along something is without inventing a fake button."""

    def __init__(self, value=0.0):
        super().__init__()
        self.enabled = False
        self.value = max(0.0, min(1.0, float(value)))

    def scene(self, x, y, width, height):
        self.place(x, y, width, height)
        track_y = y + (height - TRACK_HEIGHT) // 2
        # 宽度至少 1：协议不接受零宽矩形，而 0% 正是常见的起始值。
        return [
            rectangle(x, track_y, width, TRACK_HEIGHT, style.CONTROL,
                      TRACK_HEIGHT // 2),
            rectangle(x, track_y, max(1, int(width * self.value)), TRACK_HEIGHT,
                      style.OK, TRACK_HEIGHT // 2),
        ]


# 把事件交给第一个认领它的控件。应用不必自己解析 target 字符串，也不必将
# 事件逐个转发——这正是 immediate-mode 工具包"输入先过控件"的那条规则。
def route(controls, event):
    for control in controls:
        if control.handle(event):
            return True
    return False


# 只有需要在矩形内自行命中时才用得上；其余控件走平台提供的按钮目标。
def hit_area(target, x, y, width, height):
    return button(target, x, y, width, height, "", INVISIBLE)
