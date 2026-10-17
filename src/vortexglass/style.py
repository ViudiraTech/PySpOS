"""Shared look for apps/ views: the palette and metrics the display list draws with.

Apps used to each declare their own _TITLE/_TEXT/_DIM, which is how two screens
of the same desktop end up with two slightly different greys. The desktop shell
keeps its own tokens in qml/Theme.qml; tests/ui/test_app_style.py checks the
colours both sides use so the two cannot drift apart.

Metrics sit on a 4px base, the same scale Theme.qml's space tokens use.
"""

# --------------------------------------------------------------------------
# 颜色
# --------------------------------------------------------------------------
TITLE = "#9bc5e9"        # 区块和卡片标题
TEXT = "#e6edf3"         # 正文
DIM = "#8b949e"          # 次要文字、表头
OK = "#86cd9a"
WARN = "#e8c07d"
BAD = "#e88b8b"

WINDOW = "#132033ec"     # View.background：窗口自己的底
CARD = "#0b1829de"       # 分组卡片：相关行共用一个
DIVIDER = "#20364eee"    # 卡片内的行分隔
CONTROL = "#24384ede"    # 未选中的控件底
CONTROL_ACTIVE = "#2f7ca6e8"
FIELD = "#0f2237"

# --------------------------------------------------------------------------
# 尺寸（4px 基数）
# --------------------------------------------------------------------------
SPACE = 4
GAP = 12
PAD = 16                 # 卡片内边距
CARD_RADIUS = 8
CONTROL_RADIUS = 4
ROW_HEIGHT = 46          # 一行设置项的高度
CONTROL_HEIGHT = 30
SEGMENT_WIDTH = 92       # 分段控件每段的默认宽度
