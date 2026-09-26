'''
 *
 *      main.py
 *      Compatibility facade that boots PySpOS.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import os
import sys
import btcfg
import logk
import kernel

# Refuse to run unless the launcher started us.
if not hasattr(sys, '_launcher_detected'):
    raise RuntimeError("请使用启动器（launcher）启动PySpOS！")
    sys.exit(1)

sys._launcher_detected = True

# Put the apps directory on the module search path.
current_dir = os.getcwd()
apps_dir = os.path.join(current_dir, 'apps')
sys.path.append(apps_dir)

bootcfg = btcfg.load_bootcfg()
boot_locked = os.environ.get("PYSPOS_BOOT_LOCKED") == "1"
bootcfg["locked"] = boot_locked
rootstate = bool(btcfg.get_bootcfg('rootstate')) and not boot_locked
boot_time = logk.get_boot_time()

# Top of the process tree (Linux semantics): 0=idle(swapper)
# / 1=init / 2=shell Created outside the shell: registering at
# import time means ps already shows init before any command runs.
import process as _process
_process.boot_system()

# Resolve the root directory and the verified boot context.
script_dir = os.path.dirname(os.path.abspath(__file__))
boot_root = os.environ.get("PYSPOS_BOOT_ROOT")
boot_system = os.environ.get("PYSPOS_BOOT_SYSTEM")
if boot_root:
    root_dir = os.path.abspath(boot_root)
else:
    try:
        from common.paths import get_root_dir as _get_root_dir
        root_dir = _get_root_dir(script_dir)
    except Exception:
        root_dir = script_dir
in_slot = os.path.basename(script_dir) in ['slot_a', 'slot_b']
if boot_system and os.path.isdir(boot_system):
    current_dir = os.path.abspath(boot_system)
    apps_dir = os.path.join(current_dir, 'apps')
    if apps_dir not in sys.path:
        sys.path.append(apps_dir)
    if os.getcwd() != current_dir:
        os.chdir(current_dir)


# True when the shell currently has root; a locked boot never counts as root.
def is_root():
    return bool(rootstate or (not boot_locked and bootcfg.get('rootstate', False)))


# Raise PermissionError naming the operation unless the shell has root.
def require_root(operation):
    if not is_root():
        raise PermissionError(f"{operation} 需要 ROOT 权限")



# Boot PySpOS: report the trust state, offer OOBE, then enter the command loop.
def main():
    import syslocale
    from syslocale import _
    syslocale.init_from_bootcfg(bootcfg)
    logk.printl("main", _("boot.loading"), boot_time)
    logk.printl("main", f"Bootloader：{ _('boot.locked') if boot_locked else _('boot.unlocked')}，ROOT 权限：{ _('boot.root_off') if not rootstate else _('boot.root_on')}", boot_time)
    logk.printl("main", f"{_('boot.loaded')}{sys.platform}", boot_time)
    logk.printl("main", _("boot.root_enabled") if rootstate else _("boot.root_disabled"), boot_time)

    # OOBE really runs inside kernel.loop() (that also covers the hotreset_env path); the call
    # here only serves the compatibility case of starting with `python main.py`.
    import oobe
    oobe.maybe_run_oobe(root_dir)

    kernel.loop()

# ---- shell package: dispatch and command implementations ----
from shell.util import get_app_path, get_spf_path, is_safe_filename
from shell.dispatch import handle_command, COMMANDS, _cmd_history

# ---- legacy callers: re-export every cmd_* ----
from shell.sys_cmds import (
    print_sunhb,
    cmd_help, cmd_echo, cmd_osver, cmd_shutdown, cmd_clear, cmd_python,
    cmd_recovery, cmd_shb, cmd_ls, cmd_cd, cmd_finfo, cmd_rm, cmd_testroot,
    cmd_open, cmd_openspf, cmd_hotreset,
    cmd_pwd, cmd_whoami, cmd_cat, cmd_grep, cmd_mkdir, cmd_touch,
    cmd_cp, cmd_mv, cmd_history, cmd_spc_show, cmd_spc_export,
    cmd_spc_validate, cmd_spc_get, cmd_spc_set, cmd_spc_migrate,
    cmd_oobe, cmd_locale, cmd_bootloader_status,
)
from shell.elf_cmd import cmd_run
from shell.ota_cmds import (
    cmd_ota_check, cmd_ota_update, cmd_ota_status, cmd_ota_rollback,
    cmd_ota_clean,
)
from shell.proc_cmds import cmd_ps, cmd_jobs, cmd_kill, cmd_signal, cmd_sysmon

__all__ = [
    "bootcfg", "rootstate", "boot_locked", "boot_time", "root_dir",
    "current_dir", "apps_dir", "is_root", "require_root",
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
    "cmd_oobe", "cmd_locale", "cmd_bootloader_status",
    "cmd_run",
    "cmd_ota_check", "cmd_ota_update", "cmd_ota_status", "cmd_ota_rollback",
    "cmd_ota_clean",
    "cmd_ps", "cmd_jobs", "cmd_kill", "cmd_signal", "cmd_sysmon",
]

if __name__ == "__main__":
    main()
