"""System settings: the bootcfg preferences, plus the trust state they sit in.

The GUI counterpart of `locale` and `spc_show`. The layout follows the boxed-list
pattern — related settings share one card, a row puts its title on the leading
edge with the control on the trailing edge, and rows are separated by dividers
rather than each carrying its own border. That is what the GNOME HIG, Windows 11
and macOS all do, and what keeps a settings screen from reading as a stack of
boxes.
"""

from vortexglass import style
from vortexglass.application import View, run_app
from vortexglass.drawing import (BLOCK_HEIGHT, card, chip, divider, heading, label,
                                 segmented, segmented_width, setting_block,
                                 setting_row, value_row)
from vortexglass.host import call
from vortexglass.widgets import TextEditor

# 语言代码到显示名，与 syslocale 的目录一致。
_LANGS = (("zh_CN", "简体中文"), ("en", "English"))
_CHANNELS = (("stable", "稳定版"), ("beta", "测试版"))
# 短名单而非 zoneinfo 全表：够切换时区，又不会把面板撑成长列表。标签用简称，
# 完整 zone id 才是写进配置的值——五个全 id 横排放不下。当前值若不在名单里会
# 追加进去，所以从 shell 设的时区这里照样看得见、也能改回来。
_ZONES = (("Asia/Shanghai", "上海"), ("UTC", "UTC"), ("Asia/Tokyo", "东京"),
          ("Europe/London", "伦敦"), ("America/New_York", "纽约"))

_LEFT = 20                      # 卡片左边距
_NAME_FIELD = 190               # 显示名输入框宽度
_APPLY_WIDTH = 64
_VALUE_ROW = 38                 # 只读行的高度


class Settings(View):
    title, size, background = "PySpOS · 系统设置", (760, 600), style.WINDOW

    min_size = (700, 500)
    interval = 2

    def __init__(self):
        self.editor = TextEditor("")
        self.message = ""
        self.tone = style.TEXT
        self.loaded_name = None

    # 只在显示名没有被改动过时才跟着刷新，免得把正在输入的内容冲掉。
    def _refresh(self, cfg):
        name = str(cfg.get("display_name", ""))
        if self.loaded_name is None or self.editor.content == self.loaded_name:
            self.editor = TextEditor(name)
        self.loaded_name = name

    # 通过宿主改一项设置：校验和持久化都在宿主侧，和 shell 命令走同一条路。
    def _apply(self, key, value):
        ok, result = call("set_bootcfg", key, value)
        if ok:
            self.message, self.tone = f"{key} 已设为 {value}", style.OK
        else:
            self.message, self.tone = f"{key} 设置失败 — {result}", style.BAD
        return True

    def _name_control(self):
        def build(x, y, control_width):
            items = self.editor.scene(x, y, _NAME_FIELD, style.CONTROL_HEIGHT)
            items.append(chip("apply_name", x + _NAME_FIELD + style.SPACE * 2, y,
                              _APPLY_WIDTH, "应用"))
            return items
        return build

    def scene(self, width, height):
        items = [label(_LEFT, 20, "系统设置", 14, style.TITLE)]
        ok, cfg = call("get_bootcfg")
        if not ok:
            items.append(card(_LEFT, 66, width - _LEFT * 2, 96))
            items.append(label(_LEFT + style.PAD, 100, str(cfg), 14, style.BAD))
            return items
        self._refresh(cfg)

        ident_ok, snap = call("sm_snapshot")
        ident = snap.get("identity", {}) if ident_ok else {}
        items.append(label(_LEFT, 42,
                           f"PySpOS {ident.get('version', '?')} | 槽位 "
                           f"{ident.get('slot', '?')}({ident.get('slot_version', '?')})",
                           12, style.DIM))

        inner = width - _LEFT * 2
        items.extend(self._appearance(cfg, inner))
        items.extend(self._updates(cfg, inner))
        items.extend(self._status(cfg, ident, inner))

        if self.message:
            items.append(label(_LEFT, 576, self.message[:96], 12, self.tone))
        return items

    # 外观：显示名、语言、时区同属一类，放在一个卡片里。
    def _appearance(self, cfg, inner):
        items = [heading(_LEFT, 78, "外观")]
        height = style.SPACE * 2 + style.ROW_HEIGHT * 2 + 2 + BLOCK_HEIGHT
        top = 96
        items.append(card(_LEFT, top, inner, height))
        y = top + style.SPACE

        items.extend(setting_row(_LEFT, y, inner, "显示名",
                                 _NAME_FIELD + style.SPACE * 2 + _APPLY_WIDTH,
                                 self._name_control()))
        y += style.ROW_HEIGHT
        items.append(divider(_LEFT, y, inner))
        y += 1

        lang_width = segmented_width(len(_LANGS))
        items.extend(setting_row(
            _LEFT, y, inner, "语言", lang_width,
            lambda x, cy, cw: segmented("lang", _LANGS, cfg.get("lang"), x, cy, cw)))
        y += style.ROW_HEIGHT
        items.append(divider(_LEFT, y, inner))
        y += 1

        # 时区五个选项横排不下，改成通栏项：控件占满卡片内宽是选项本身撑开的。
        zones = list(_ZONES)
        current = cfg.get("timezone")
        if current and current not in [value for value, _label in zones]:
            zones.append((current, current))
        items.extend(setting_block(
            _LEFT, y, inner, "时区",
            lambda x, cy, cw: segmented("timezone", zones, current, x, cy, cw)))
        return items

    def _updates(self, cfg, inner):
        top = 314
        items = [heading(_LEFT, top - 18, "更新"),
                 card(_LEFT, top, inner, style.SPACE * 2 + style.ROW_HEIGHT)]
        channel_width = segmented_width(len(_CHANNELS))
        items.extend(setting_row(
            _LEFT, top + style.SPACE, inner, "更新通道", channel_width,
            lambda x, cy, cw: segmented("ota_channel", _CHANNELS,
                                        cfg.get("ota_channel"), x, cy, cw)))
        return items

    # 系统状态：只读，所以右侧是值不是控件。（只读）写在分组标题里，锁定与 ROOT
    # 不属于本会话可以改的范围，界面上就不给出可点的东西。单列而不是两列——两列
    # 会让左栏的值和右栏的标题挤在一起。
    def _status(self, cfg, ident, inner):
        top = 402
        locked = bool(cfg.get("locked"))
        root = bool(cfg.get("rootstate"))
        rows = (
            ("Bootloader", "LOCKED" if locked else "UNLOCKED",
             style.WARN if locked else style.OK),
            ("ROOT", "是" if root else "否", style.OK if root else style.DIM),
            ("当前槽位", str(ident.get("slot", "?")), style.TEXT),
            ("OTA 云端", "禁用" if ident.get("ota") == "禁用" else "启用", style.TEXT),
        )
        items = [heading(_LEFT, top - 18, "系统状态（只读）"),
                 card(_LEFT, top, inner, style.SPACE * 2 + _VALUE_ROW * len(rows))]
        for index, (title, value, tone) in enumerate(rows):
            items.extend(value_row(_LEFT, top + style.SPACE + index * _VALUE_ROW,
                                   inner, title, value, tone))
        return items

    # 文本事件给输入框，其余都是控件。
    def handle(self, event):
        if event["type"] == "click":
            target = event.get("target") or ""
            if target == "apply_name":
                # 显示名按定义只有一行，空名宿主也会拒，两件都先在这里了结。
                name = self.editor.content.replace("\n", " ").strip()[:64]
                self.editor = TextEditor(name)
                return self._apply("display_name", name)
            key, _, value = target.partition(":")
            if key in ("lang", "timezone", "ota_channel") and value:
                return self._apply(key, value)
            return False
        return self.editor.handle(event)


def main(argv=None):
    run_app(Settings, argv)


if __name__ == "__exec__":
    main()
elif __name__ == "__main__":
    import sys
    main(sys.argv[1:])
