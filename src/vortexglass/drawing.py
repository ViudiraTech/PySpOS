"""Optional client-side display-list helpers. No GUI toolkit is required."""


def label(x, y, value, size=16, color="#e6edf3"):
    return {"type": "text", "x": x, "y": y, "text": str(value), "size": size, "color": color}


def rectangle(x, y, width, height, color, radius=0):
    return {"type": "rect", "x": x, "y": y, "width": width, "height": height,
            "color": color, "radius": radius}


def button(target, x, y, width, height, value, color="#30465fdc"):
    return {"type": "button", "id": target, "x": x, "y": y, "width": width,
            "height": height, "text": value, "color": color, "size": 18, "radius": 6}


def line(x, y, x2, y2, color="#e6edf3", width=1):
    return {"type": "line", "x": x, "y": y, "x2": x2, "y2": y2,
            "color": color, "width": width}


# --------------------------------------------------------------------------
# 布局词汇
#
# 这一层存在的理由：设置页和设备页的排版有公认的写法（GNOME HIG 的 boxed
# list、Windows 11 与 macOS 的设置面板都是同一套），而它靠的是几条结构约定，
# 不是逐像素调参。约定是：
#
#   1. 相关的行共用一个卡片，而不是每项各画一个面板；
#   2. 一行里标题贴左、控件贴右，控件宽度由内容决定，不撑满整行；
#   3. 行与行之间用分隔线，不用各自的边框；
#   4. 分组上方有标题，组与组之间留出比行距更大的空白。
#
# 把这几条做成函数，应用就不必各自重新发明——之前每个应用都自己堆面板，于是
# 三个界面三套间距。
# --------------------------------------------------------------------------

from . import style


# 完全透明但可点击：合成器按坐标命中按钮，整行因此可以是一个点击目标。
INVISIBLE = "#00000000"


# 分组卡片：相关行共用这一个容器。
def card(x, y, width, height):
    return rectangle(x, y, width, height, style.CARD, style.CARD_RADIUS)


# 卡片上方的分组标题。
def heading(x, y, value):
    return label(x, y, value, 12, style.DIM)


# 卡片内的行分隔线，左右各缩进一个内边距，不与卡片边缘相连。
def divider(x, y, width):
    return line(x + style.PAD, y, x + width - style.PAD, y, style.DIVIDER)


# 控件贴右时的 x：调用方先算它，再把控件画在那儿。
def trailing_x(x, width, control_width):
    return x + width - style.PAD - control_width


# 单个值控件（当前值直接写在上面，点一下换下一个）。
def chip(target, x, y, width, value, active=False):
    return button(target, x, y, width, style.CONTROL_HEIGHT, value,
                  style.CONTROL_ACTIVE if active else style.CONTROL)


# 分段控件的总宽：调用方要先知道它，才能把控件贴到行尾。
def segmented_width(count, segment=None):
    return count * (segment or style.SEGMENT_WIDTH)


# 分段控件：选项少时用它代替通栏按钮。宽度由调用方给定并按选项数均分，所以
# 贴右时传内容宽度、需要通栏时传整行内宽，两种用法同一个函数。
def segmented(prefix, options, current, x, y, width):
    count = len(options)
    if count == 0:
        return []
    step = width // count
    items = []
    for index, (value, text) in enumerate(options):
        # 最后一段吃掉整除的余数，右侧才不留缝。
        span = width - step * (count - 1) if index == count - 1 else step
        items.append(button(f"{prefix}:{value}", x + index * step, y, span,
                            style.CONTROL_HEIGHT, text,
                            style.CONTROL_ACTIVE if value == current else style.CONTROL))
    return items


# 一行设置项：标题（可带副标题）贴左，控件由 build_control 画在贴右的位置上，
# 整行都是点击目标，所以点标题和点控件是一回事。
# build_control(x, y, width) 返回控件项。
def setting_row(x, y, width, title, control_width, build_control,
                subtitle=None, target=None):
    items = []
    if target:
        items.append(button(target, x, y, width, style.ROW_HEIGHT, "", INVISIBLE))
    items.append(label(x + style.PAD, y + (10 if subtitle else 15), title, 14,
                       style.TEXT))
    if subtitle:
        items.append(label(x + style.PAD, y + 29, subtitle, 11, style.DIM))
    control_y = y + (style.ROW_HEIGHT - style.CONTROL_HEIGHT) // 2
    items.extend(build_control(trailing_x(x, width, control_width), control_y,
                               control_width))
    return items


# 只读的一行：同样的左右结构，右边是一个值而不是控件。
def value_row(x, y, width, title, value, tone=None):
    return [label(x + style.PAD, y + 15, title, 14, style.TEXT),
            label(x + width - style.PAD - len(str(value)) * 7, y + 15, value, 13,
                  tone or style.DIM)]


# 通栏设置项：标题占一行，控件另起一行占满卡片内宽。选项横向排不下时用它，
# 这时控件由内容撑满一行是合理的——撑满的是选项本身，不是单个按钮。
BLOCK_HEAD = 34          # 控件相对行首的偏移
BLOCK_HEIGHT = BLOCK_HEAD + style.CONTROL_HEIGHT + 12


def setting_block(x, y, width, title, build_control, subtitle=None):
    items = [label(x + style.PAD, y + 10, title, 14, style.TEXT)]
    if subtitle:
        items.append(label(x + style.PAD, y + 29, subtitle, 11, style.DIM))
    items.extend(build_control(x + style.PAD, y + BLOCK_HEAD, width - style.PAD * 2))
    return items
