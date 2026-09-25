'''
 *
 *      force_sync.py
 *      Developer utility for synchronizing source into an unlocked boot slot.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import argparse
import os
import shutil
import sys
import uuid

import secure_boot

EXCLUDED_NAMES = {"__pycache__", ".git", ".hotreset", "current_slot",
                  "boot_manifest.json", "boot_manifest.sig"}
EXCLUDED_SUFFIXES = (".pyc", ".pyo")


# Read the active slot marker and fall back to slot_a for missing or invalid values.
def _current_slot(root_dir):
    try:
        with open(os.path.join(root_dir, "current_slot"), encoding="utf-8") as stream:
            value = stream.read().strip()
    except OSError:
        return "slot_a"
    return value if value in secure_boot.SLOTS else "slot_a"


# Copy source files while excluding generated state and rejecting symbolic links.
def _copy_source(source, destination):
    for root, dirs, files in os.walk(source, topdown=True, followlinks=False):
        dirs[:] = [name for name in dirs
                   if name not in EXCLUDED_NAMES and not name.startswith("__pycache__")]
        for name in files:
            if name in EXCLUDED_NAMES or name.endswith(EXCLUDED_SUFFIXES):
                continue
            source_path = os.path.join(root, name)
            if os.path.islink(source_path):
                raise RuntimeError(f"源目录包含符号链接: {source_path}")
            relative = os.path.relpath(source_path, source)
            target_path = os.path.join(destination, relative)
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            shutil.copy2(source_path, target_path)


# Replace a development slot from src, preserving selected runtime state.
def sync_slot(root_dir, slot=None, assume_yes=False):
    root_dir = os.path.abspath(root_dir)
    if secure_boot.read_locked(root_dir):
        raise RuntimeError("当前是 LOCKED 信任域，拒绝使用强制同步")
    slot = slot or _current_slot(root_dir)
    if slot not in secure_boot.SLOTS:
        raise ValueError("槽位必须是 slot_a 或 slot_b")
    source = os.path.join(root_dir, "src")
    target = os.path.join(root_dir, slot)
    if not os.path.isdir(source) or os.path.islink(source):
        raise RuntimeError("找不到可信的 src 源码目录")
    if os.path.islink(target):
        raise RuntimeError("目标槽位是符号链接")
    if not assume_yes:
        answer = input(f"将用 src 覆盖 {slot}，继续？(y/n): ").strip().lower()
        if answer not in ("y", "yes"):
            print("已取消")
            return False
    staging = os.path.join(root_dir, f".{slot}.sync-{uuid.uuid4().hex[:12]}")
    os.makedirs(staging)
    try:
        _copy_source(source, staging)
        old_etc = os.path.join(target, "etc")
        if os.path.isdir(old_etc) and not os.path.islink(old_etc):
            shutil.copytree(old_etc, os.path.join(staging, "etc"), symlinks=True)
        old_log = os.path.join(target, "update_log.json")
        if os.path.isfile(old_log) and not os.path.islink(old_log):
            shutil.copy2(old_log, os.path.join(staging, "update_log.json"))
        secure_boot.stage_directory_replace(root_dir, slot, staging)
    except Exception:
        if os.path.isdir(staging):
            shutil.rmtree(staging, ignore_errors=True)
        raise
    print(f"同步完成: {slot} <- {source}")
    print("该操作只适用于 UNLOCKED 开发模式；重启后重新执行验签。")
    return True


# Parse command-line options and return a process-style status code.
def main(argv=None):
    parser = argparse.ArgumentParser(description="强制把 src 同步到当前开发槽位")
    parser.add_argument("--root-dir", default=os.path.dirname(os.path.abspath(__file__)))
    parser.add_argument("--slot", choices=secure_boot.SLOTS)
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args(argv)
    try:
        return 0 if sync_slot(args.root_dir, args.slot, args.yes) else 1
    except Exception as exc:
        print(f"同步失败: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
