'''
 *
 *      recovery.py
 *      Recovery mode: standby screen, menu and actions.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import main
import kernel
import logk
import tui
from tui import BACK, TUIAbort
import printk
import re
import shutil
import os
import gc
import ota
import sys
import subprocess

# Go through common.paths; fall back to the historical layout if that fails.
script_dir = os.path.dirname(os.path.abspath(__file__))
try:
    from common.paths import get_root_dir as _get_root_dir
    root_dir = _get_root_dir(script_dir)
except Exception:
    if os.path.basename(script_dir) == 'src':
        # Running from src, the root is src's parent directory.
        root_dir = os.path.dirname(script_dir)
    elif os.path.basename(script_dir) in ['slot_a', 'slot_b']:
        # Running from a slot directory, the root is the slot's parent.
        root_dir = os.path.dirname(script_dir)
    else:
        # Any other layout: the script directory itself is the root.
        root_dir = script_dir

# Put src and the slots on the module path, then chdir to the root.
def ensure_root_directory():
    for path in (os.path.join(root_dir, "src"),
                 os.path.join(root_dir, "slot_a"),
                 os.path.join(root_dir, "slot_b")):
        if os.path.isdir(path) and path not in sys.path:
            sys.path.insert(0, path)
    current_dir = os.getcwd()
    if current_dir != root_dir:
        logk.printl("recovery", f"切换到根目录: {root_dir}", main.boot_time)
        os.chdir(root_dir)
        logk.printl("recovery", f"当前目录已切换到: {os.getcwd()}", main.boot_time)


# Run a root-requiring step, printing the refusal instead of raising; True
# when allowed.
def _require_root(operation):
    try:
        main.require_root(operation)
        return True
    except PermissionError as exc:
        printk.error(str(exc))
        return False

# Find and kill a main.py left running by the system we came from.
def check_and_terminate_main_process():
    try:
        # Ask the OS which python processes exist (tasklist on Windows, ps elsewhere).
        if os.name == 'nt':  # Windows
            result = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq python.exe', '/FO', 'CSV'], 
                                  capture_output=True, text=True, cwd=root_dir)
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                current_pid = str(os.getpid())
                
                for line in lines[1:]:  # skip the header line
                    if not line:
                        continue
                    parts = line.split(',')
                    if len(parts) < 2:
                        continue
                    pid = parts[1].strip('"')
                    if not pid.isdigit() or pid == current_pid:
                        continue
                    # read that process's command line
                    cmd_result = subprocess.run(['wmic', 'process', 'where', f'ProcessId={pid}', 'get', 'ProcessId,CommandLine'], 
                                              capture_output=True, text=True)
                    if cmd_result.returncode != 0:
                        continue
                    # Match one line at a time and only act on a line that names
                    # this pid. A 'main.py' anywhere in the whole output said
                    # nothing about which process it belonged to, so a match in
                    # another row could kill an innocent process by mistake.
                    for row in cmd_result.stdout.splitlines():
                        row = row.strip()
                        if not row or 'main.py' not in row:
                            continue
                        if not re.search(r'(?<!\d)' + re.escape(pid) + r'(?!\d)', row):
                            continue
                        logk.printl("recovery", f"发现正在运行的 main 进程 (PID: {pid})，正在终止...", main.boot_time)
                        subprocess.run(['taskkill', '/PID', pid, '/F'], cwd=root_dir)
                        logk.printl("recovery", f"main 进程已终止", main.boot_time)
                        break
        else:  # Linux/Unix
            result = subprocess.run(['ps', 'aux'], capture_output=True, text=True, cwd=root_dir)
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                current_pid = str(os.getpid())
                
                for line in lines[1:]:  # skip the header line
                    if not line or 'main.py' not in line:
                        continue
                    parts = line.split()
                    if len(parts) < 2:
                        continue
                    pid = parts[1]
                    # compare the pid field itself, never a substring of the line:
                    # "1234" must not match a process whose pid is 51234
                    if not pid.isdigit() or pid == current_pid:
                        continue
                    logk.printl("recovery", f"发现正在运行的 main 进程 (PID: {pid})，正在终止...", main.boot_time)
                    subprocess.run(['kill', '-9', pid], cwd=root_dir)
                    logk.printl("recovery", f"main 进程已终止", main.boot_time)
    except Exception as e:
        logk.printl("recovery", f"检查进程时出错: {e}", main.boot_time)

# Enter recovery from the running system; returns reboot so the caller restarts.
def recovery_main(jumpinfo) -> str:
    ensure_root_directory()

    check_and_terminate_main_process()

    kernel.screen_clear()
    logk.printl("recovery", f"跳入到recovery, jumpinfo={jumpinfo}", main.boot_time)
    _no_command_screen()
    _menu_loop()
    logk.printl("recovery", "Recovery已退出", main.boot_time)
    return "reboot"


# ---------------------------------------------------------------------------
# AOSP-style interface: standby screen plus menu
# ---------------------------------------------------------------------------

_DROID = r"""
      ___
   .-"   "-.
  /  .-.  .-\
  |  | |  | |
   \  '-'  '-/
    '.   .'
      | |
     _| |_
    |_____|
""".rstrip("\n")


# Read one line through ttyutil (normalised, with a retry limit), falling back to
# input().
def _read(prompt=""):
    try:
        import ttyutil
        return ttyutil.read_line(prompt)
    except Exception:
        try:
            return input(prompt)
        except EOFError:
            return ""


# Wait for Enter so the output stays on screen before the menu is drawn again.
def _pause(msg="按回车返回菜单..."):
    _read(msg)


# Build the version line at the top of the menu: real
# slot and version where available, else unknown.
def _build_id():
    import pyspos
    slot = version = "unknown"
    try:
        st = ota.get_ota_status()
        slot = st.get("current_slot", slot)
        version = st.get("current_version", version)
    except Exception:
        pass
    return ("PySpOS Recovery\n"
            f"pyspos/{slot}/{slot}\n"
            f"{pyspos.OS_VERSION}/{pyspos.OS_DEVELOP_STAGE}/"
            f"{pyspos.OS_VENDOR}")


# Print the AOSP-style standby screen and wait for Enter.
def _no_command_screen():
    print(_DROID)
    print("No command.")
    print()
    _read("按回车显示菜单...")


# Run the menu until an action returns reboot or poweroff, or the user aborts
# the input.
def _menu_loop():
    items = [
        ("Reboot system now", _act_reboot),
        ("Apply update from cloud", _act_ota_update),
        ("Install version from cloud...", _act_install_version),
        ("Check for updates", _act_ota_check),
        ("Show slot / OTA status", _act_ota_status),
        ("Wipe cache partition", _act_ota_clean),
        ("Wipe data/factory reset", _act_erase),
        ("Run recovery command", _act_shell),
        ("Power off", _act_poweroff),
    ]
    titles = [title for title, _fn in items]
    while True:
        kernel.screen_clear()
        try:
            idx = tui.ask_menu(_build_id(), titles)
        except (TUIAbort, EOFError, KeyboardInterrupt):
            # Aborting the input means leaving recovery: the old code let EOF bubble up to
            # kernel.loop(), which ended the session anyway; returning explicitly is cleaner.
            return
        if idx is BACK:
            continue
        action = items[idx][1]()
        if action in ("reboot", "poweroff"):
            return


# ---------------------------------------------------------------------------
# Menu actions; the command loop reuses the very same functions
# ---------------------------------------------------------------------------

# Menu action: hand control back to the system.
def _act_reboot():
    print("正在返回系统...\n")
    return "reboot"


# Menu action: shut the system down.
def _act_poweroff():
    print("正在关机...\n")
    kernel.exit()
    return "poweroff"


# Menu action: drop into the recovery command loop.
def _act_shell():
    kernel.screen_clear()
    print("Recovery 命令行（输入 exit 返回菜单）。\n")
    recovery_shell()
    return None


# Menu action: factory reset, only after an explicit second confirmation.
def _act_erase():
    if not _require_root("recovery erase"):
        _pause()
        return None
    try:
        sel = tui.ask_menu(
            "Wipe all user data?\nThis can not be undone!",
            ["No", "Factory reset"], 0)
    except (TUIAbort, EOFError, KeyboardInterrupt):
        return None
    # Default to No: Esc, an empty answer and an explicit No all count as refuse, as in AOSP.
    if sel is BACK or sel != 1:
        print("操作已取消\n")
        _pause()
        return None
    # Factory reset: shares common.reset with the tests, so nothing is left behind
    # and the next boot runs OOBE (etc/.oobe_done goes away together with etc/).
    from common.reset import factory_reset
    report = factory_reset(root_dir)
    for _name, (ok, msg) in report.items():
        if ok:
            printk.ok(msg)
        else:
            printk.error(msg)
    gc.collect()
    logk.printl("recovery", "出厂重置完成，重启后将进入首次开机向导（OOBE）\n", main.boot_time)
    _pause()
    return None


# Menu action: ask the cloud whether a newer build exists.
def _act_ota_check():
    logk.printl("recovery", "检查是否有可用的更新...", main.boot_time)
    update_info = ota.check_cloud_update()
    if update_info:
        if update_info.get('disabled'):
            print(f"OTA 已临时禁用: {update_info.get('reason', '')}")
            print(f"当前版本: {update_info.get('current_version', 'unknown')}")
        elif update_info['has_update']:
            print(f"发现新版本: {update_info['remote_version']}")
            print(f"当前版本: {update_info['current_version']}")
            print(f"更新内容: {update_info['release_notes']}")
        else:
            print(f"当前已是最新版本: {update_info['current_version']}")
    else:
        print("无法获取云端版本信息（网络失败或 OTA 被禁用）。")
    print()
    _pause()
    return None


# Menu action: download and install the newest build; needs root.
def _act_ota_update():
    if not _require_root("recovery OTA 更新"):
        _pause()
        return None
    logk.printl("recovery", "下载并安装更新...", main.boot_time)
    result = ota.download_and_install_update()
    if result:
        print("更新已成功安装，重启后生效\n")
    else:
        print("更新失败\n")
    _pause()
    return None


# Menu action: print the slot, version and update status.
def _act_ota_status():
    logk.printl("recovery", "查看OTA更新状态...", main.boot_time)
    status = ota.get_ota_status()
    if not status.get('ota_enabled', True):
        print(f"OTA 状态: 已临时禁用 ({status.get('ota_disable_reason', '')})")
    print(f"当前槽位: {status['current_slot']}")
    print(f"当前版本: {status['current_version']}")
    print(f"其他槽位: {status['other_slot']}")
    print(f"其他版本: {status['other_version']}")
    print(f"是否有更新: {'是' if status['has_update'] else '否'}")
    if status['update_version']:
        print(f"更新版本: {status['update_version']}")
    print()
    _pause()
    return None


# Menu action: pick a cloud version and a target slot, then install it.
# The boot slot is not switched; the user is asked afterwards. A downgrade or
# same-version install needs a second explicit confirmation, and the signature and
# anti-rollback checks always run.
def _act_install_version():
    if not _require_root("recovery 指定版本安装"):
        _pause()
        return None
    entries = ota.list_cloud_versions()
    if not entries:
        print("未能获取云端版本列表（网络失败或 OTA 被禁用）。\n")
        _pause()
        return None
    try:
        ver_labels = []
        for e in entries:
            tag = f"v{e['version']}"
            if e.get('date'):
                tag += f"  {e['date']}"
            if e.get('type'):
                tag += f"  [{e['type']}]"
            ver_labels.append(tag)
        ver_idx = tui.ask_menu("Select a version to install:", ver_labels, 0)
    except (TUIAbort, EOFError, KeyboardInterrupt):
        return None
    if ver_idx is BACK:
        return None
    entry = entries[ver_idx]
    try:
        current_slot = ota.get_current_slot()
    except Exception:
        current_slot = None
    other_slot = ota.SLOT_B if current_slot == ota.SLOT_A else ota.SLOT_A
    slot_options = [other_slot, current_slot]
    slot_labels = []
    for s in slot_options:
        if s is None:
            continue
        mark = "当前" if s == current_slot else "非当前"
        slot_labels.append(f"{s}（{mark}槽位）")
    try:
        slot_idx = tui.ask_menu(
            f"Install v{entry['version']} to which slot?", slot_labels, 0)
    except (TUIAbort, EOFError, KeyboardInterrupt):
        return None
    if slot_idx is BACK:
        return None
    slot = slot_options[slot_idx]
    try:
        current_ver = ota.get_current_version()
    except Exception:
        current_ver = "unknown"
    try:
        newer = ota.compare_versions(entry['version'], current_ver) > 0
    except Exception:
        newer = True
    print(f"版本: v{entry['version']}  →  槽位: {slot}")
    print(f"当前版本: {current_ver}，当前槽位: {current_slot}")
    if entry.get('sha256'):
        print(f"SHA-256: {entry['sha256'][:16]}…")
    print()
    if newer:
        if not printk.confirm(f"下载 v{entry['version']} 并安装到 {slot}？"):
            print("操作已取消\n")
            _pause()
            return None
        allow_downgrade = False
    else:
        print("所选版本不高于当前版本（同级或降级）。")
        if not printk.confirm("仍要安装到指定槽位？签名验签与防回滚照常执行。"):
            print("操作已取消\n")
            _pause()
            return None
        allow_downgrade = True
    ok = ota.download_and_install_version(entry, slot, allow_downgrade)
    if not ok:
        print("安装失败\n")
        _pause()
        return None
    print(f"v{entry['version']} 已安装到 {slot}\n")
    if slot != current_slot and printk.confirm(f"把启动槽位切换到 {slot}？（否则下次启动仍进 {current_slot}）"):
        try:
            ota.set_current_slot(slot)
            print(f"启动槽位已切换到 {slot}，重启后生效\n")
        except Exception as e:
            printk.error(f"切换槽位失败: {e}\n")
    else:
        print(f"保持启动槽位 {current_slot}，新槽位留待以后切换\n")
    _pause()
    return None


# Menu action: delete the downloaded update packages, mirroring AOSP wipe cache.
def _act_ota_clean():
    # Mirrors AOSP's wipe cache partition: harmless enough to skip the second confirmation.
    if not _require_root("recovery OTA 清理"):
        _pause()
        return None
    logk.printl("recovery", "清理更新包文件...", main.boot_time)
    ota.clean_update_package()
    print()
    _pause()
    return None


# ---------------------------------------------------------------------------
# Legacy command loop, entered from the last menu entry (the recovery > ota_* steps)
# ---------------------------------------------------------------------------

# The legacy recovery command loop, reached from the last menu entry.
def recovery_shell():
    logk.printl("recovery", "欢迎使用PySpOS Recovery，输入help获取可用命令", main.boot_time)
    while 1:
        prompt = _read("recovery> ")

        if prompt == "help":
            print("help     打印本帮助信息")
            print("erase    出厂重置（清配置/槽位/缓存/答题记录，下次启动进入OOBE）")
            print("optimize 调用GC垃圾回收，让性能更高（实验性的）")
            print("ota_check  检查是否有可用的更新")
            print("ota_update 下载并安装更新")
            print("ota_status 查看OTA更新状态")
            print("ota_rollback 回滚到上一个版本")
            print("ota_clean  清理更新包文件")
            print("exit     返回Recovery菜单\n")
        elif prompt == "erase":
            if not _require_root("recovery erase"):
                continue
            if not printk.confirm("erase 将删除全部用户数据并回到首次开机状态，继续？"):
                print("操作已取消\n")
            else:
                from common.reset import factory_reset
                report = factory_reset(root_dir)
                for _name, (ok, msg) in report.items():
                    if ok:
                        printk.ok(msg)
                    else:
                        printk.error(msg)
                gc.collect()
                logk.printl("recovery", "出厂重置完成，重启后将进入首次开机向导（OOBE）\n", main.boot_time)
        elif prompt == "exit":
            break
        elif prompt == "optimize":
            gc.collect()
            gc.collect(2)
            logk.printl("recovery", "GC垃圾回收执行完毕！\n", main.boot_time)
        elif prompt == "ota_check":
            logk.printl("recovery", "检查是否有可用的更新...", main.boot_time)
            update_info = ota.check_cloud_update()
            if update_info:
                if update_info.get('disabled'):
                    print(f"OTA 已临时禁用: {update_info.get('reason', '')}")
                    print(f"当前版本: {update_info.get('current_version', 'unknown')}")
                elif update_info['has_update']:
                    print(f"发现新版本: {update_info['remote_version']}")
                    print(f"当前版本: {update_info['current_version']}")
                    print(f"更新内容: {update_info['release_notes']}")
                else:
                    print(f"当前已是最新版本: {update_info['current_version']}")
            else:
                print("无法获取云端版本信息（网络失败或 OTA 被禁用）。")
            print()
        elif prompt == "ota_update":
            if not _require_root("recovery OTA 更新"):
                continue
            logk.printl("recovery", "下载并安装更新...", main.boot_time)
            result = ota.download_and_install_update()
            if result:
                print("更新已成功安装，重启后生效\n")
            else:
                print("更新失败\n")
        elif prompt == "ota_status":
            logk.printl("recovery", "查看OTA更新状态...", main.boot_time)
            status = ota.get_ota_status()
            if not status.get('ota_enabled', True):
                print(f"OTA 状态: 已临时禁用 ({status.get('ota_disable_reason', '')})")
            print(f"当前槽位: {status['current_slot']}")
            print(f"当前版本: {status['current_version']}")
            print(f"其他槽位: {status['other_slot']}")
            print(f"其他版本: {status['other_version']}")
            print(f"是否有更新: {'是' if status['has_update'] else '否'}")
            if status['update_version']:
                print(f"更新版本: {status['update_version']}")
            print()
        elif prompt == "ota_rollback":
            if not _require_root("recovery OTA 回滚"):
                continue
            logk.printl("recovery", "回滚到上一个版本...", main.boot_time)
            result = ota.rollback_update()
            if result:
                print("回滚成功，重启后生效\n")
            else:
                print("回滚失败\n")
        elif prompt == "ota_clean":
            if not _require_root("recovery OTA 清理"):
                continue
            logk.printl("recovery", "清理更新包文件...", main.boot_time)
            ota.clean_update_package()
            print()
        elif prompt == "":
            continue
        else:
            print(f"找不到 {prompt} 命令")
