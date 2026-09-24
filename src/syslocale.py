#
#   syslocale.py
#   系统语言（i18n）+ 时区。标准库 only，被 kernel/main 早期导入，
#   因此本模块禁止 import 主工程模块（main/btcfg/kernel），只做纯逻辑。
#
#   语言：_('key') 查目录，缺省回退 key 本身；set_language 切换即时生效，
#   由 OOBE/开机 init_from_bootcfg 持久化（bootcfg.lang）。
#   目录覆盖：OOBE 全流程 + TUI 框体 + locale 命令 + 开机 banner。
#   （shell 历史命令体的中文串保持原样，属增量翻译范畴，见 TODO。）
#
#   时区：set_timezone(name) 用 zoneinfo 校验并立即生效——POSIX 写 TZ+tzset，
#   全平台同时登记 _TZ 供 now_str() 使用；init_from_bootcfg 开机应用。
#

import os
import time
from datetime import datetime

try:
    from zoneinfo import ZoneInfo, available_timezones
    _ZONEINFO_OK = True
except ImportError:  # 极旧 Python 回退
    ZoneInfo = None
    available_timezones = lambda: set()
    _ZONEINFO_OK = False

SUPPORTED_LANGS = {
    "zh_CN": "简体中文",
    "en": "English",
}
DEFAULT_LANG = "zh_CN"
DEFAULT_TIMEZONE = "Asia/Shanghai"

_current_lang = DEFAULT_LANG
_current_tz = DEFAULT_TIMEZONE

CATALOGS = {
    "zh_CN": {
        # TUI 框体
        "tui.cont": "继续",
        "tui.back": "返回",
        "tui.cancel": "取消",
        "tui.default_hint": "（回车接受默认值）",
        "tui.back_hint": "（输入 < 返回上一步）",
        "tui.empty_hint": "（输入 ! 表示留空）",
        "tui.choose": "请输入编号",
        "tui.invalid": "输入无效，请重试",
        "tui.press_enter": "按回车继续…",
        # 开机 banner
        "boot.loading": "加载 PySpKernel...",
        "boot.locked": "已上锁",
        "boot.unlocked": "已解锁",
        "boot.root_off": "未启用",
        "boot.root_on": "已启用",
        "boot.loaded": "加载完成，您使用的操作系统为：",
        "boot.root_enabled": "ROOT已启用",
        "boot.root_disabled": "ROOT未启用",
        "boot.welcome": "欢迎使用 PySpOS 操作系统，{user}！",
        # locale 命令
        "locale.usage": "用法: locale [lang <zh_CN|en> | tz <时区> | user <显示名>]",
        "locale.current": "当前语言：{lang}，时区：{tz}，显示名：{user}",
        "locale.lang_ok": "语言已切换为 {lang}，重启后依然有效",
        "locale.lang_bad": "不支持的语言（可选：{langs}）",
        "locale.tz_ok": "时区已切换为 {tz}，当前时间 {now}",
        "locale.tz_bad": "未知时区：{tz}",
        "locale.user_ok": "显示名已设为 {user}",
        # OOBE
        "oobe.step": "步骤 {i}/{n}",
        "oobe.welcome_t": "欢迎使用 PySpOS",
        "oobe.welcome_b": "这是首次开机向导（OOBE），将用几分钟完成初始设置。\n随时可用「返回」回到上一步。",
        "oobe.lang_t": "选择语言 / Select language",
        "oobe.lang_b": "请选择系统语言，之后的向导将使用该语言显示。",
        "oobe.license_t": "许可证",
        "oobe.license_b": "PySpOS 采用 MIT License 开源（见根目录 LICENSE）。\n继续即表示你接受该许可证。",
        "oobe.license_q": "是否接受 MIT License？",
        "oobe.must_accept": "必须接受许可证才能继续。若放弃，可返回上一步或中止（下次开机将重新进入向导）。",
        "oobe.tz_region_t": "选择时区：地区",
        "oobe.tz_region_b": "先选择地区，再选择城市。所选时区将立即影响系统显示的所有时间。",
        "oobe.tz_city_t": "选择时区：城市",
        "oobe.tz_city_b": "请选择城市，确认后将预览当前时间。",
        "oobe.tz_preview": "该时区现在是：{now}（{tz}）",
        "oobe.user_t": "设置显示名",
        "oobe.user_b": "检测到系统用户为：{detected}\n可输入一个显示名（回车沿用系统用户，! 表示留空用系统用户）。",
        "oobe.user_q": "显示名",
        "oobe.root_t": "ROOT 权限",
        "oobe.root_b": "ROOT 拥有系统全部权限。建议保持关闭，需要时可用 open getroot 临时获取（操作会被审计）。",
        "oobe.root_q": "是否默认启用 ROOT（持久化）？",
        "oobe.bl_t": "Bootloader 状态",
         "oobe.bl_b": "Bootloader 当前：{state}。\nLOCKED 时 ROOT 仅临时有效；信任域只能由设备外部签发 policy 改变。",

        "oobe.ota_t": "OTA 更新通道",
        "oobe.ota_b": "选择更新通道（云端恢复前仅做记录，恢复后生效）。",
        "oobe.ota_stable": "stable（仅正式版）",
        "oobe.ota_beta": "beta（抢先体验）",
         "oobe.token_t": "安全策略",
         "oobe.token_b": "Bootloader 信任由固定公钥和外部签名 policy 决定。\nUNLOCKED 首次设置会生成开发签名密钥；ROOT 不会改变 OEM 签名，旧 Token 也不具备授权能力。",

        "oobe.summary_t": "确认配置",
        "oobe.summary_b": "语言：{lang}\n时区：{tz}\n显示名：{user}\nROOT：{root}\n更新通道：{channel}\n\n确认写入并完成向导？",
        "oobe.done_t": "设置完成",
        "oobe.done_b": "初始设置已写入，即将进入系统。\n随时可执行 oobe 命令重新运行本向导。",
        "oobe.abort": "已中止向导（未写入标记），下次启动将重新进入 OOBE。",
    },
    "en": {
        "tui.cont": "Continue",
        "tui.back": "Go Back",
        "tui.cancel": "Cancel",
        "tui.default_hint": "(Enter accepts default)",
        "tui.back_hint": "(type < to go back)",
        "tui.empty_hint": "(type ! for empty)",
        "tui.choose": "Enter number",
        "tui.invalid": "Invalid input, try again",
        "tui.press_enter": "Press Enter to continue...",
        "boot.loading": "Loading PySpKernel...",
        "boot.locked": "locked",
        "boot.unlocked": "unlocked",
        "boot.root_off": "disabled",
        "boot.root_on": "enabled",
        "boot.loaded": "Loaded, host OS: ",
        "boot.root_enabled": "ROOT enabled",
        "boot.root_disabled": "ROOT disabled",
        "boot.welcome": "Welcome to PySpOS, {user}!",
        "locale.usage": "Usage: locale [lang <zh_CN|en> | tz <timezone> | user <name>]",
        "locale.current": "Language: {lang}, timezone: {tz}, display name: {user}",
        "locale.lang_ok": "Language switched to {lang}, persists after reboot",
        "locale.lang_bad": "Unsupported language (choices: {langs})",
        "locale.tz_ok": "Timezone switched to {tz}, local time {now}",
        "locale.tz_bad": "Unknown timezone: {tz}",
        "locale.user_ok": "Display name set to {user}",
        "oobe.step": "Step {i}/{n}",
        "oobe.welcome_t": "Welcome to PySpOS",
        "oobe.welcome_b": "This is the out-of-box experience (OOBE); initial setup takes a few minutes.\nYou can go back to the previous step at any time.",
        "oobe.lang_t": "Select language / 选择语言",
        "oobe.lang_b": "Choose the system language; the rest of the wizard uses it.",
        "oobe.license_t": "License",
        "oobe.license_b": "PySpOS is MIT licensed (see LICENSE at repo root).\nContinuing means you accept it.",
        "oobe.license_q": "Accept the MIT License?",
        "oobe.must_accept": "You must accept to continue. Go back or abort (OOBE reruns next boot).",
        "oobe.tz_region_t": "Timezone: region",
        "oobe.tz_region_b": "Pick a region first, then a city. It immediately affects all displayed times.",
        "oobe.tz_city_t": "Timezone: city",
        "oobe.tz_city_b": "Pick a city; a time preview follows.",
        "oobe.tz_preview": "Local time there: {now} ({tz})",
        "oobe.user_t": "Display name",
        "oobe.user_b": "Detected system user: {detected}\nEnter a display name (Enter keeps it, ! also keeps it).",
        "oobe.user_q": "Display name",
        "oobe.root_t": "ROOT privilege",
        "oobe.root_b": "ROOT has full power. Keep it off; use open getroot when needed (audited).",
        "oobe.root_q": "Enable persistent ROOT by default?",
        "oobe.bl_t": "Bootloader status",
         "oobe.bl_b": "Bootloader is {state}.\nLOCKED keeps ROOT temporary; trust changes only through an externally signed policy.",

        "oobe.ota_t": "OTA channel",
        "oobe.ota_b": "Choose an update channel (recorded now, honored once the server is back).",
        "oobe.ota_stable": "stable (releases only)",
        "oobe.ota_beta": "beta (early access)",
         "oobe.token_t": "Security policy",
         "oobe.token_b": "Bootloader trust is fixed by a public key and an externally signed policy.\nUNLOCKED first setup creates a developer signing key; ROOT cannot change the OEM signature.",

        "oobe.summary_t": "Confirm",
        "oobe.summary_b": "Language: {lang}\nTimezone: {tz}\nDisplay name: {user}\nROOT: {root}\nChannel: {channel}\n\nWrite config and finish?",
        "oobe.done_t": "Done",
        "oobe.done_b": "Setup saved, entering the system.\nRun the oobe command anytime to rerun this wizard.",
        "oobe.abort": "Wizard aborted (marker not written); OOBE reruns next boot.",
    },
}


def _(key, **kwargs):
    text = CATALOGS.get(_current_lang, {}).get(key, CATALOGS[DEFAULT_LANG].get(key, key))
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            return text
    return text


def get_language():
    return _current_lang


def set_language(lang):
    global _current_lang
    if lang not in SUPPORTED_LANGS:
        return False
    _current_lang = lang
    return True


def get_timezone():
    return _current_tz


def list_timezones():
    try:
        zones = sorted(available_timezones())
    except Exception:
        zones = []
    if not zones:
        zones = ["UTC", "Asia/Shanghai", "Asia/Tokyo", "Europe/London",
                 "Europe/Berlin", "America/New_York", "Australia/Sydney"]
    return zones


def set_timezone(name):
    """校验并立即生效；失败返回 False（不改动当前状态）。"""
    global _current_tz
    name = (name or "").strip()
    if not name:
        return False
    if _ZONEINFO_OK:
        try:
            ZoneInfo(name)
        except Exception:
            return False
    elif name not in list_timezones():
        return False
    _current_tz = name
    try:
        if os.name == "posix":
            os.environ["TZ"] = name
            time.tzset()
    except Exception:
        pass
    return True


def now_str(fmt="%H:%M:%S"):
    try:
        if _ZONEINFO_OK:
            return datetime.now(ZoneInfo(_current_tz)).strftime(fmt)
    except Exception:
        pass
    return time.strftime(fmt)


def full_timestamp(fmt="%Y-%m-%d %H:%M:%S"):
    return now_str(fmt)


def init_from_bootcfg(bootcfg):
    """开机应用持久化语言/时区。bootcfg 缺键时用默认，不抛异常。"""
    try:
        lang = (bootcfg or {}).get("lang", DEFAULT_LANG)
        if lang in SUPPORTED_LANGS:
            set_language(lang)
        tz = (bootcfg or {}).get("timezone", DEFAULT_TIMEZONE)
        if tz:
            set_timezone(tz)
    except Exception:
        pass
