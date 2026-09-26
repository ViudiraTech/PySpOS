'''
 *
 *      reset.py
 *      Factory reset: wipes every piece of state OOBE checks.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import glob
import json
import os
import shutil

QUESTION_BANK_RELPATH = os.path.join("src", "apps", "question_bank.json")
READLINE_HISTORY = os.path.join(os.path.expanduser("~"), ".pyspos_history")
DEFAULT_SLOT = "slot_a"


# Remove a tree, but only for a real directory, never a symlink.
def _rmtree(path):
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path, ignore_errors=False)
        return True
    return False


# Remove a file or symlink, reporting whether anything went away.
def _remove(path):
    if os.path.isfile(path) or os.path.islink(path):
        os.remove(path)
        return True
    return False


# Wipe the device state the next OOBE run judges, shared by recovery
# erase and the tests. Per-item failures are reported as
# {category: (ok, note)} for the caller to display.
def factory_reset(root_dir, include_host_history=True):
    report = {}
    try:
        import secure_boot
        policy = secure_boot.read_policy(root_dir)
        locked = bool(policy and policy.get("locked"))
    except Exception:
        locked = True

    # 1. etc/: bootcfg, audit log and OOBE markers
    etc_path = os.path.join(root_dir, "etc")
    if _rmtree(etc_path):
        report["etc"] = (True, f"已删除 {etc_path}（bootcfg/audit/OOBE标记）")
    else:
        report["etc"] = (True, "etc 不存在，无需清理")

    # 2. etc.bak-*: leftovers renamed aside by the btcfg repair
    bak_paths = sorted(glob.glob(os.path.join(root_dir, "etc.bak-*")))
    removed_bak = 0
    for p in bak_paths:
        try:
            if os.path.isdir(p):
                shutil.rmtree(p)
            else:
                os.remove(p)
            removed_bak += 1
        except OSError:
            report.setdefault("etc_bak_failed", []).append(p)
    if "etc_bak_failed" in report:
        report["etc_bak"] = (False, f"部分备份删除失败: {report.pop('etc_bak_failed')}")
    elif removed_bak:
        report["etc_bak"] = (True, f"已删除 {removed_bak} 个引导备份（etc.bak-*）")
    else:
        report["etc_bak"] = (True, "无引导备份残留")

    # 3. slot_a/ and slot_b/: the per-slot system files
    for slot in ("slot_a", "slot_b"):
        slot_path = os.path.join(root_dir, slot)
        if locked:
            report[f"slot_{slot}"] = (True, f"锁定模式保留已验证槽位 {slot}")
        elif _rmtree(slot_path):
            report[f"slot_{slot}"] = (True, f"已删除槽位 {slot}")
        else:
            report[f"slot_{slot}"] = (True, f"槽位 {slot} 不存在")

    # 4. current_slot: reset to the default slot
    slot_file = os.path.join(root_dir, "current_slot")
    if locked:
        report["current_slot"] = (True, "锁定模式保留当前槽位选择")
    else:
        try:
            with open(slot_file, "w", encoding="utf-8") as f:
                f.write(DEFAULT_SLOT)
            report["current_slot"] = (True, f"已重置为默认槽位 {DEFAULT_SLOT}")
        except OSError as e:
            report["current_slot"] = (False, f"重置 current_slot 失败: {e}")

    # 5. ota/*.zip: drop the downloaded updates, keep the directory
    ota_dir = os.path.join(root_dir, "ota")
    zips = sorted(glob.glob(os.path.join(ota_dir, "*.zip")))
    removed_zip = 0
    for z in zips:
        try:
            os.remove(z)
            removed_zip += 1
        except OSError:
            pass
    if removed_zip:
        report["ota"] = (True, f"已删除 {removed_zip} 个更新包")
    else:
        report["ota"] = (True, "无更新包残留")

    # 6. question bank history: clear the records, keep the questions
    bank_path = os.path.join(root_dir, QUESTION_BANK_RELPATH)
    try:
        with open(bank_path, "r", encoding="utf-8") as f:
            bank = json.load(f)
        n = len(bank.get("history", []))
        bank["history"] = []
        with open(bank_path, "w", encoding="utf-8") as f:
            json.dump(bank, f, ensure_ascii=False, indent=2)
        report["question_bank"] = (True, f"已清除 {n} 条答题记录（题目保留）")
    except FileNotFoundError:
        report["question_bank"] = (True, "题库文件不存在，无需清理")
    except (OSError, ValueError) as e:
        report["question_bank"] = (False, f"题库历史清除失败: {e}")

    # 7. the readline history in the home directory
    if include_host_history:
        if _remove(READLINE_HISTORY):
            report["readline_history"] = (True, f"已删除 {READLINE_HISTORY}")
        else:
            report["readline_history"] = (True, "家目录无命令历史残留")

    # 8. every __pycache__ and *.pyc under the root
    purged_dirs = 0
    purged_files = 0
    for dirpath, dirnames, filenames in os.walk(root_dir):
        if ".git" in dirpath.split(os.sep):
            continue
        for d in list(dirnames):
            if d == "__pycache__":
                try:
                    shutil.rmtree(os.path.join(dirpath, d))
                    purged_dirs += 1
                except OSError:
                    pass
        for fn in filenames:
            if fn.endswith(".pyc"):
                try:
                    os.remove(os.path.join(dirpath, fn))
                    purged_files += 1
                except OSError:
                    pass
    report["pycache"] = (True, f"已清除 {purged_dirs} 个 __pycache__ / {purged_files} 个 .pyc")

    return report
