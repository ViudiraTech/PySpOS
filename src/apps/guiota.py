"""System update: the A/B slots, what is staged, and rolling back.

The GUI counterpart of `ota_status` and `ota_rollback`. Read-only facts come from
the host's OTA state; the one action, rolling back, is gated on ROOT by the host
exactly as the shell command is, and takes effect on the next boot.
"""

from vortexglass import style
from vortexglass.application import View, run_app
from vortexglass.drawing import button, card, heading, label, value_row
from vortexglass.host import call

_TITLE, _TEXT, _DIM = style.TITLE, style.TEXT, style.DIM
_OK, _WARN, _BAD = style.OK, style.WARN, style.BAD

_LEFT = 20
_SLOT_ROW = 34
_SLOT_CARD = 132   # 槽位卡片高度


class Update(View):
    title, size, background = "PySpOS · 系统更新", (760, 500), style.WINDOW

    min_size = (680, 440)
    interval = 2

    def __init__(self):
        self.message = ""
        self.tone = _DIM

    # 回滚换的是启动槽位，宿主按 shell 里 ota_rollback 的同一道门判定 ROOT。
    def _rollback(self):
        ok, result = call("ota_rollback")
        if ok:
            self.message, self.tone = "回滚已排入，重启后生效", _OK
        else:
            self.message, self.tone = f"回滚失败 — {result}", _BAD
        return True

    # 一个槽位卡片：名称、版本、验签状态。当前槽位用主色标出来。
    def _slot(self, x, top, width, name, version, verified, current):
        return [
            card(x, top, width, _SLOT_CARD),
            heading(x + style.PAD, top + 10, f"{name}（{'当前' if current else '备用'}）"),
            label(x + style.PAD, top + 38, str(version or "未知版本")[:20], 20,
                  _TEXT if current else _DIM),
            label(x + style.PAD, top + 76, "已验签" if verified else "未验签", 13,
                  _OK if verified else _WARN),
            label(x + style.PAD, top + 100,
                  "Verified Boot 通过" if verified else "未通过签名校验，不参与启动",
                  11, _DIM),
        ]

    def scene(self, width, height):
        items = [label(_LEFT, 20, "系统更新", 14, _TITLE)]
        ok, status = call("ota_status")
        if not ok:
            items.append(card(_LEFT, 66, width - _LEFT * 2, 96))
            items.append(label(_LEFT + style.PAD, 100, str(status), 14, _BAD))
            return items

        inner = width - _LEFT * 2
        version = status.get("current_version") or "?"
        items.append(label(_LEFT, 42,
                           f"当前版本 {version} | 通道 "
                           f"{'启用' if status.get('ota_enabled') else '禁用'}",
                           12, _DIM))

        items.append(heading(_LEFT, 78, "更新状态"))
        items.append(card(_LEFT, 96, inner, style.SPACE * 2 + _SLOT_ROW * 3))
        enabled = bool(status.get("ota_enabled"))
        reason = status.get("ota_disable_reason")
        rows = (
            ("云更新", "启用" if enabled else f"禁用（{reason}）",
             _OK if enabled else _WARN),
            ("可用更新",
             str(status.get("update_version")) if status.get("has_update") else "无",
             _TEXT),
            ("防回滚索引", str(status.get("rollback_index", 0)), _TEXT),
        )
        for index, (title, value, tone) in enumerate(rows):
            items.extend(value_row(_LEFT, 96 + style.SPACE + index * _SLOT_ROW, inner,
                                   title, value, tone))

        items.append(heading(_LEFT, 224, "A/B 槽位"))
        half = (inner - style.CONTROL_HEIGHT) // 2
        items.extend(self._slot(_LEFT, 242, half, str(status.get("current_slot", "?")),
                                status.get("current_version"),
                                status.get("current_slot_verified"), True))
        items.extend(self._slot(_LEFT + half + style.CONTROL_HEIGHT, 242, half,
                                str(status.get("other_slot", "?")),
                                status.get("other_version"),
                                status.get("other_slot_verified"), False))

        items.append(button("rollback", _LEFT, 390, 120, 34, "回滚", "#24384ede"))
        items.append(label(_LEFT + 136, 400,
                           "回滚到上一版本需要 ROOT，重启后生效", 12, _DIM))
        items.append(label(_LEFT, 436,
                           "更新包在 shell 里用 ota_update 下载安装；本窗口负责查看与回滚",
                           11, _DIM))
        if self.message:
            items.append(label(_LEFT, 462, self.message[:96], 12, self.tone))
        return items

    def handle(self, event):
        if event["type"] == "click" and event.get("target") == "rollback":
            return self._rollback()
        return False


def main(argv=None):
    run_app(Update, argv)


if __name__ == "__exec__":
    main()
elif __name__ == "__main__":
    import sys
    main(sys.argv[1:])
