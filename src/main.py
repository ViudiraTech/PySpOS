#
#   main.py
#   PySpOS 入口（facade / 兼容层）
#
#   2026-09-24 重构：1217 行的单体 main.py 已拆分为 shell/* 包：
#     shell/util.py      路径/文件名 helpers
#     shell/sys_cmds.py  系统/文件类命令（help/echo/ls/cd/rm/open/cat/…）
#     shell/elf_cmd.py   ELF 运行命令（unicorn 默认 + 自研引擎兜底）
#     shell/ota_cmds.py  OTA 更新命令
#     shell/proc_cmds.py 进程/系统状态命令（ps/kill/signal/sysmon）
#     shell/dispatch.py  命令分发（注册表 + 重定向/管道 + handle_command）
#   本文件仅保留：启动检查、全局状态（bootcfg/rootstate/boot_time/root_dir）、
#   槽位切换、main() 入口，并逐一重导出 shell 符号，保证 kernel / recovery /
#   apps/api / parse_spf / tests 等历史调用方零改动。
#
#   By GoutouStdio
#   @ 2022~2026 GoutouStdio. Open all rights.

import os
import sys
import btcfg
import logk
import kernel

# 检查是否通过启动器启动
if not hasattr(sys, '_launcher_detected'):
    raise RuntimeError("请使用启动器（launcher）启动PySpOS！")
    sys.exit(1)

# 标记已通过启动器启动
sys._launcher_detected = True

# 设置 apps 目录为模块搜索路径
current_dir = os.getcwd()
apps_dir = os.path.join(current_dir, 'apps')
sys.path.append(apps_dir)

# 全局变量定义处
bootcfg = btcfg.load_bootcfg()
rootstate = bool(btcfg.get_bootcfg('rootstate'))
boot_time = logk.get_boot_time()

# 进程树顶层（Linux 语义）：0=idle(swapper) / 1=init / 2=shell
# 必须在 shell 之外建立：import 时即登记，任何命令执行前 ps 就能看到 init。
import process as _process
_process.boot_system()

# 获取根目录（main.py所在目录的父目录）
# 统一走 common.paths，失败时回退到历史逻辑（兼容旧槽位布局）。
script_dir = os.path.dirname(os.path.abspath(__file__))
try:
    from common.paths import get_root_dir as _get_root_dir
    root_dir = _get_root_dir(script_dir)
    in_slot = os.path.basename(script_dir) in ['slot_a', 'slot_b']
except Exception:
    if os.path.basename(script_dir) == 'src':
        # 在src目录中，根目录是src的父目录
        root_dir = os.path.dirname(script_dir)
        in_slot = False
    elif os.path.basename(script_dir) in ['slot_a', 'slot_b']:
        # 在槽位目录中，根目录是槽位的父目录
        root_dir = os.path.dirname(script_dir)
        in_slot = True
    else:
        # 其他情况，使用当前目录作为根目录
        root_dir = script_dir
        in_slot = False

# 切换到当前槽位目录
current_slot_file = os.path.join(root_dir, "current_slot")
if os.path.exists(current_slot_file):
    try:
        with open(current_slot_file, 'r') as f:
            current_slot = f.read().strip()
            slot_path = os.path.join(root_dir, current_slot)
            if os.path.exists(slot_path):
                # 如果当前不在槽位目录中，切换到槽位目录
                if not in_slot:
                    os.chdir(slot_path)
                    current_dir = os.getcwd()
                    apps_dir = os.path.join(current_dir, 'apps')
                    sys.path.append(apps_dir)
                    logk.printl("main", f"已切换到槽位: {current_slot}", boot_time)
                else:
                    # 已经在槽位目录中，保持当前目录
                    logk.printl("main", f"当前已在槽位: {current_slot}", boot_time)
            else:
                logk.printl("main", f"槽位 {current_slot} 不存在，使用src目录", boot_time)
    except Exception as e:
        logk.printl("main", f"读取槽位文件失败: {e}，使用src目录", boot_time)
else:
    logk.printl("main", "未找到槽位文件，使用src目录", boot_time)

# 主函数
def main():
    import syslocale
    from syslocale import _
    syslocale.init_from_bootcfg(bootcfg)
    logk.printl("main", _("boot.loading"), boot_time)
    logk.printl("main", f"Bootloader：{ _('boot.locked') if bootcfg['locked'] else _('boot.unlocked')}，ROOT 权限：{ _('boot.root_off') if not bootcfg['rootstate'] else _('boot.root_on')}", boot_time)
    logk.printl("main", f"{_('boot.loaded')}{sys.platform}", boot_time)
    logk.printl("main", _("boot.root_enabled") if rootstate else _("boot.root_disabled"), boot_time)

    # OOBE 实际在 kernel.loop() 里触发（覆盖 hotreset_env 直连路径），此处保留
    # 仅为直接以 `python main.py` 启动的兼容场景。
    import oobe
    oobe.maybe_run_oobe(root_dir)

    kernel.loop()

# ---- shell 包：分发与命令实现 ----
from shell.util import get_app_path, get_spf_path, is_safe_filename
from shell.dispatch import handle_command, COMMANDS, _cmd_history

# ---- 历史调用方兼容：重导出全部 cmd_* ----
from shell.sys_cmds import (
    print_sunhb,
    cmd_help, cmd_echo, cmd_osver, cmd_shutdown, cmd_clear, cmd_python,
    cmd_recovery, cmd_shb, cmd_ls, cmd_cd, cmd_finfo, cmd_rm, cmd_testroot,
    cmd_open, cmd_openspf, cmd_hotreset,
    cmd_pwd, cmd_whoami, cmd_cat, cmd_grep, cmd_mkdir, cmd_touch,
    cmd_cp, cmd_mv, cmd_history, cmd_spc_show, cmd_spc_export,
    cmd_spc_validate, cmd_spc_get, cmd_spc_set, cmd_spc_migrate,
    cmd_oobe, cmd_locale,
)
from shell.elf_cmd import cmd_run
from shell.ota_cmds import (
    cmd_ota_check, cmd_ota_update, cmd_ota_status, cmd_ota_rollback,
    cmd_ota_clean,
)
from shell.proc_cmds import cmd_ps, cmd_jobs, cmd_kill, cmd_signal, cmd_sysmon

__all__ = [
    "bootcfg", "rootstate", "boot_time", "root_dir",
    "current_dir", "apps_dir",
    "get_app_path", "get_spf_path", "is_safe_filename",
    "handle_command", "COMMANDS", "_cmd_history",
    "main",
    "print_sunhb",
    "cmd_help", "cmd_echo", "cmd_osver", "cmd_shutdown", "cmd_clear",
    "cmd_python", "cmd_recovery", "cmd_shb", "cmd_ls", "cmd_cd",
    "cmd_finfo", "cmd_rm", "cmd_testroot", "cmd_open", "cmd_openspf",
    "cmd_hotreset", "cmd_pwd", "cmd_whoami", "cmd_cat", "cmd_grep",
    "cmd_mkdir", "cmd_touch",     "cmd_cp", "cmd_mv", "cmd_history",
    "cmd_spc_show", "cmd_spc_export",
    "cmd_spc_validate", "cmd_spc_get", "cmd_spc_set", "cmd_spc_migrate",
    "cmd_oobe", "cmd_locale",
    "cmd_run",
    "cmd_ota_check", "cmd_ota_update", "cmd_ota_status", "cmd_ota_rollback",
    "cmd_ota_clean",
    "cmd_ps", "cmd_jobs", "cmd_kill", "cmd_signal", "cmd_sysmon",
]

if __name__ == "__main__":
    main()
