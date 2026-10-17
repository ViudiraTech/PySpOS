"""Boot trust: the verified-boot chain and the runtime privileges it leaves open.

A read-only panel over states that are decided elsewhere — the lock state comes
from the signed policy on disk, slot verification from the boot chain, and ROOT
from the host session. Nothing here is the user's to change from inside a
window, so nothing here is clickable; the shell commands remain the way to act.
"""

from vortexglass import style
from vortexglass.application import View, run_app
from vortexglass.drawing import card, heading, label, value_row
from vortexglass.host import call

_TITLE, _TEXT, _DIM = style.TITLE, style.TEXT, style.DIM
_OK, _WARN, _BAD = style.OK, style.WARN, style.BAD

_LEFT = 20
_ROW = 34


class Trust(View):
    title, size, background = "PySpOS · 启动信任", (720, 470), style.WINDOW

    min_size = (640, 420)
    interval = 2

    # 三份状态来自三个不同的地方：bootcfg、宿主会话、OTA/secure_boot 的验签
    # 结果。任何一份拿不到都不能画出一个看似完整的信任链。
    def _state(self):
        cfg_ok, cfg = call("get_bootcfg")
        root_ok, root = call("get_rootstate")
        ota_ok, ota = call("ota_status")
        if not (cfg_ok and ota_ok):
            return None, (cfg if not cfg_ok else ota)
        return {"cfg": cfg, "root": bool(root) if root_ok else None, "ota": ota}, None

    # 一张分组卡片：若干标签/值行，值自带语气色。
    def _group(self, title, top, inner, rows):
        items = [heading(_LEFT, top - 18, title),
                 card(_LEFT, top, inner, style.SPACE * 2 + _ROW * len(rows))]
        for index, (name, value, tone) in enumerate(rows):
            items.extend(value_row(_LEFT, top + style.SPACE + index * _ROW, inner,
                                   name, value, tone))
        return items

    def scene(self, width, height):
        items = [label(_LEFT, 20, "启动信任链", 14, _TITLE)]
        state, problem = self._state()
        if problem is not None:
            items.append(card(_LEFT, 60, width - _LEFT * 2, 96))
            items.append(label(_LEFT + style.PAD, 94, str(problem), 14, _BAD))
            return items

        cfg, ota = state["cfg"], state["ota"]
        inner = width - _LEFT * 2
        items.append(label(_LEFT, 42,
                           f"槽位 {ota.get('current_slot', '?')} | "
                           f"版本 {ota.get('current_version', '?')}", 12, _DIM))

        locked = bool(cfg.get("locked"))
        items.extend(self._group("启动信任", 88, inner, (
            ("Bootloader", "LOCKED" if locked else "UNLOCKED",
             _OK if locked else _WARN),
            ("防回滚索引", str(ota.get("rollback_index", 0)), _TEXT),
            ("当前槽位", "已验签" if ota.get("current_slot_verified") else "未验签",
             _OK if ota.get("current_slot_verified") else _WARN),
            ("备用槽位", "已验签" if ota.get("other_slot_verified") else "未验签",
             _OK if ota.get("other_slot_verified") else _WARN),
        )))

        root = state["root"]
        items.extend(self._group("运行权限", 268, inner, (
            ("ROOT", "未知" if root is None else ("是" if root else "否"),
             _DIM if root is None else (_OK if root else _DIM)),
            ("OTA 云端", "启用" if ota.get("ota_enabled") else "禁用",
             _OK if ota.get("ota_enabled") else _WARN),
            ("语言 / 时区", f"{cfg.get('lang', '?')} / {cfg.get('timezone', '?')}",
             _TEXT),
        )))

        note = ("LOCKED 拒收未签名镜像，且不计作 ROOT"
                if locked else "UNLOCKED 允许刷入未签名镜像；改锁状态要签名 policy")
        items.append(label(_LEFT, 404, note, 11, _DIM))
        items.append(label(_LEFT, 424,
                           "这些状态在别处决定，本窗口只读；操作请用 shell 命令",
                           11, _DIM))
        return items


def main(argv=None):
    run_app(Trust, argv)


if __name__ == "__exec__":
    main()
elif __name__ == "__main__":
    import sys
    main(sys.argv[1:])
