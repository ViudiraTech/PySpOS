'''
 *
 *      oobe.py
 *      First-boot setup wizard.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import os

import syslocale
from syslocale import _
import tui
from tui import BACK, TUIAbort

MARKER_NAME = os.path.join("etc", ".oobe_done")
OTA_CHANNELS = ("stable", "beta")


# Return the path of the etc/.oobe_done marker.
def marker_path(root_dir):
    return os.path.join(root_dir, MARKER_NAME)


# Report whether the wizard should run, that is whether the done marker is missing.
def should_run(root_dir):
    return not os.path.isfile(marker_path(root_dir))


# Split the zone list into region names, with 'Other' collecting the zones that have none.
def _regions():
    zones = syslocale.list_timezones()
    regions = sorted({z.split("/")[0] for z in zones if "/" in z})
    singles = sorted([z for z in zones if "/" not in z])
    if singles:
        regions.append("Other")
    return regions, zones


# Return the cities of one region, with the region prefix stripped off.
def _cities_of(region, zones):
    if region == "Other":
        return sorted([z for z in zones if "/" not in z])
    prefix = region + "/"
    return sorted([z[len(prefix):] for z in zones if z.startswith(prefix)])


# Run the steps in order; ctx supplies root_dir, username, locked and a
# persist(values) callback, so the wizard is testable with the line backend and
# a scripted stdin. Returns True when finished and written, False on abort.
def run_wizard(ctx):
    steps = [
        "welcome", "language", "license", "tz_region", "tz_city",
        "username", "root", "bootloader", "ota", "token", "summary",
    ]
    n = len(steps)
    values = {
        "lang": syslocale.get_language(),
        "timezone": syslocale.get_timezone(),
        "display_name": "",
        "root": False,
        "channel": "stable",
    }
    idx = 0
    i1 = lambda: idx + 1
    while 0 <= idx < n:
        step = steps[idx]
        nxt = _run_step(step, ctx, values, i1(), n)
        if nxt == "back":
            idx -= 1
            if idx < 0:
                return False
        elif nxt == "abort":
            return False
        else:
            idx += 1
    try:
        ctx["persist"](values)
    except Exception as e:
        print(f"写入配置失败: {e}")
        return False
    tui.note(_("oobe.done_t"), _("oobe.done_b"), n + 1, n + 1)
    return True


# Run one wizard step and return 'next', 'back' or 'abort'.
def _run_step(step, ctx, values, i, n):
    if step == "welcome":
        r = tui.note(_("oobe.welcome_t"), _("oobe.welcome_b"), i, n)
        return "back" if r == BACK else "next"

    if step == "language":
        opts = [f"{code} — {name}" for code, name in syslocale.SUPPORTED_LANGS.items()]
        codes = list(syslocale.SUPPORTED_LANGS)
        cur = codes.index(syslocale.get_language()) if syslocale.get_language() in codes else 0
        r = tui.ask_select(_("oobe.lang_t"), _("oobe.lang_b"), opts, cur, i, n)
        if r == BACK:
            return "back"
        syslocale.set_language(codes[r])
        values["lang"] = codes[r]
        return "next"

    if step == "license":
        while True:
            r = tui.confirm(_("oobe.license_t"), _("oobe.license_b"),
                            _("oobe.license_q"), True, i, n)
            if r == BACK:
                return "back"
            if r:
                return "next"
            tui.note(_("oobe.license_t"), _("oobe.must_accept"), i, n)

    if step == "tz_region":
        regions, zones = _regions()
        cur_tz = values["timezone"]
        cur_region = cur_tz.split("/")[0] if "/" in cur_tz else "Other"
        dflt = regions.index(cur_region) if cur_region in regions else 0
        r = tui.ask_select(_("oobe.tz_region_t"), _("oobe.tz_region_b"), regions, dflt, i, n)
        if r == BACK:
            return "back"
        values["_region"] = regions[r]
        values["_zones"] = zones
        return "next"

    if step == "tz_city":
        region = values.get("_region", "Asia")
        zones = values.get("_zones") or syslocale.list_timezones()
        cities = _cities_of(region, zones)
        full = (region + "/" if region != "Other" else "")
        cur = values["timezone"]
        dflt = 0
        if cur.startswith(full):
            tail = cur[len(full):]
            if tail in cities:
                dflt = cities.index(tail)
        r = tui.ask_select(_("oobe.tz_city_t"), _("oobe.tz_city_b"), cities, dflt, i, n)
        if r == BACK:
            return "back"
        chosen = (region + "/" if region != "Other" else "") + cities[r]
        if syslocale.set_timezone(chosen):
            values["timezone"] = chosen
        tui.note(_("oobe.tz_city_t"),
                 _("oobe.tz_preview", now=syslocale.now_str("%Y-%m-%d %H:%M:%S"),
                     tz=values["timezone"]), i, n)
        return "next"

    if step == "username":
        detected = ctx.get("username", "")
        r = tui.ask_text(_("oobe.user_t"), _("oobe.user_b", detected=detected),
                         _("oobe.user_q"), detected, i, n)
        if r == BACK:
            return "back"
        values["display_name"] = r if r not in ("", "!") else detected
        return "next"

    if step == "root":
        r = tui.confirm(_("oobe.root_t"), _("oobe.root_b"), _("oobe.root_q"), False, i, n)
        if r == BACK:
            return "back"
        values["root"] = bool(r)
        return "next"

    if step == "bootloader":
        state = _("boot.locked") if ctx.get("locked", True) else _("boot.unlocked")
        r = tui.note(_("oobe.bl_t"), _("oobe.bl_b", state=state), i, n)
        return "back" if r == BACK else "next"

    if step == "ota":
        opts = [_("oobe.ota_stable"), _("oobe.ota_beta")]
        dflt = 0 if values["channel"] == "stable" else 1
        r = tui.ask_select(_("oobe.ota_t"), _("oobe.ota_b"), opts, dflt, i, n)
        if r == BACK:
            return "back"
        values["channel"] = OTA_CHANNELS[r]
        return "next"

    if step == "token":
        r = tui.note(_("oobe.token_t"), _("oobe.token_b"), i, n)
        return "back" if r == BACK else "next"

    if step == "summary":
        lang_name = syslocale.SUPPORTED_LANGS.get(values["lang"], values["lang"])
        body = _("oobe.summary_b", lang=f"{lang_name} ({values['lang']})",
                 tz=values["timezone"],
                 user=values["display_name"] or ctx.get("username", ""),
                 root=_("boot.root_on") if values["root"] else _("boot.root_off"),
                 channel=values["channel"])
        r = tui.confirm(_("oobe.summary_t"), body, _("oobe.summary_t"), True, i, n)
        if r == BACK:
            return "back"
        return "next" if r else "back"

    return "next"


# Build the real context: read the system user, bootcfg and secure boot state from the running system.
def _live_ctx(root_dir):
    import btcfg
    import kernel

    try:
        username = kernel.get_system_username()
    except Exception:
        username = ""
    cfg = {}
    try:
        cfg = btcfg.load_bootcfg()
    except Exception:
        pass
    try:
        import secure_boot
        locked = secure_boot.read_locked(root_dir)
    except Exception:
        locked = bool(cfg.get("locked", False))

# Write the collected values into bootcfg, apply the locale and create the
# done marker; ROOT is only persisted when the bootloader is unlocked.
    def persist(values):
        import main
        effective_root = bool(values["root"] and not locked)
        btcfg.set_bootcfg_value("lang", values["lang"])
        btcfg.set_bootcfg_value("timezone", values["timezone"])
        btcfg.set_bootcfg_value("display_name", values["display_name"])
        btcfg.set_bootcfg_value("ota_channel", values["channel"])
        btcfg.set_bootcfg_value("rootstate", effective_root)
        main.rootstate = effective_root
        syslocale.init_from_bootcfg({"lang": values["lang"],
                                     "timezone": values["timezone"]})
        if not locked:
            try:
                secure_boot.ensure_developer_key(root_dir, locked=False)
                secure_boot.configure_runtime_keys(root_dir, False)
            except Exception as exc:
                print(f"开发签名密钥生成失败: {exc}")
        etc = os.path.join(root_dir, "etc")
        os.makedirs(etc, exist_ok=True)
        with open(marker_path(root_dir), "w", encoding="utf-8") as f:
            f.write("oobe-done-v1\n")

    return {"root_dir": root_dir, "username": username,
            "locked": bool(locked), "persist": persist}


# Boot entry point: True when the wizard is not needed, otherwise run it;
# an abort also returns False. The terminal is always restored, since a Ctrl-C
# (TUIAbort) skips the curses teardown and would leave readline reading junk.
def maybe_run_oobe(root_dir):
    try:
        import secure_boot
        locked = secure_boot.read_locked(root_dir)
        if not locked:
            secure_boot.ensure_developer_key(root_dir, locked=False)
            secure_boot.configure_runtime_keys(root_dir, False)
    except Exception:
        pass
    if not should_run(root_dir):

        return True
    try:
        return run_wizard(_live_ctx(root_dir))
    except TUIAbort:
        print(_("oobe.abort"))
        return False
    except Exception as e:
        print(f"OOBE 出错已跳过: {e}")
        return False
    finally:
        try:
            import ttyutil
            ttyutil.ensure_sane_tty()
        except Exception:
            pass
