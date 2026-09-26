'''
 *
 *      ota_cmds.py
 *      Built-in OTA update shell commands.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import ota
import main


# Ask for ROOT and return False after printing the refusal.
def _require_root(operation):
    try:
        main.require_root(operation)
    except PermissionError as exc:
        print(f"{exc}")
        return False
    return True


# Ask the cloud whether a newer version exists and report what came back.
def cmd_ota_check():
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
        # when the fetch fails after the retries have given up, keep the old behaviour: print a single line
        print("无法获取云端版本信息（网络失败或 OTA 被禁用）。")
    print()

# Download and install the available update, which needs ROOT.
def cmd_ota_update():
    if not _require_root("OTA 更新"):
        return
    result = ota.download_and_install_update()
    if result:
        print("更新已成功安装，系统将自动重启\n")
    else:
        print("更新失败\n")

# Print the OTA state: enable flag, slots, signatures and rollback index.
def cmd_ota_status():
    status = ota.get_ota_status()
    if not status.get('ota_enabled', True):
        print(f"OTA 状态: 已临时禁用 ({status.get('ota_disable_reason', '')})")
    print(f"Bootloader: {'LOCKED' if status.get('boot_locked') else 'UNLOCKED'}")
    print(f"防回滚版本: {status.get('rollback_index', 0)}")
    print(f"当前槽位: {status['current_slot']} ({'已验签' if status.get('current_slot_verified') else '未验签'})")
    print(f"当前版本: {status['current_version']}")
    print(f"其他槽位: {status['other_slot']} ({'已验签' if status.get('other_slot_verified') else '未验签'})")
    print(f"其他版本: {status['other_version']}")
    print(f"是否有更新: {'是' if status['has_update'] else '否'}")
    if status['update_version']:
        print(f"更新版本: {status['update_version']}")
    print()

# Roll back to the previous version, which needs ROOT.
def cmd_ota_rollback():
    if not _require_root("OTA 回滚"):
        return
    result = ota.rollback_update()
    if result:
        print("回滚成功，重启后生效\n")
    else:
        print("回滚失败\n")

# Delete the downloaded update packages, which needs ROOT.
def cmd_ota_clean():
    if not _require_root("清理 OTA"):
        return
    ota.clean_update_package()
    print()
