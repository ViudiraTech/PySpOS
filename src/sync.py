'''
 *
 *      sync.py
 *      Legacy fix/ directory synchronisation helpers.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import filecmp
import os
import shutil
import printk

# deprecated on 2026-09-24: the fix/ directory this module refers to is not in the repository,
# and the OTA slot mechanism has taken over its job. The file is kept so old imports still work,
# but sync_fix_to_root() now just returns False after printing a deprecation notice and copies nothing.

# files that must be synchronised
REQUIRED_FILES = [
    "kernel.py", "main.py", "fs.py", "printk.py", "sync.py", "btcfg.py"
]
# directories that must be synchronised
REQUIRED_DIRS = ["apps", "etc"]

# Return the size of a file
def get_file_size(path: str) -> int:
    if os.path.isfile(path):
        try:
            return os.path.getsize(path)
        except Exception as e:
            printk.warn(f"获取文件大小失败 {path}: {str(e)}")
            return -1
    return 0

# Report whether two files hold the same bytes. Size alone is not content: a
# patched file of the same length has to be copied, or the destination keeps
# running the old bytes and the caller believes the sync happened.
def same_content(src_path: str, dest_path: str) -> bool:
    try:
        if os.path.getsize(src_path) != os.path.getsize(dest_path):
            return False
        return filecmp.cmp(src_path, dest_path, shallow=False)
    except OSError as e:
        printk.warn(f"比较文件内容失败: {str(e)}")
        return False

# Copy one file out of the fix directory
def sync_file_from_fix(src_path: str, dest_path: str) -> bool:
    if not os.path.exists(src_path):
        printk.warn(f"源文件不存在，跳过同步: {src_path}")
        return False
    
    dest_dir = os.path.dirname(dest_path)
    # A bare file name has no directory part, and makedirs("") is an error
    if dest_dir:
        os.makedirs(dest_dir, exist_ok=True)
    
    # compare the file contents, not just the sizes
    if os.path.isfile(dest_path) and same_content(src_path, dest_path):
        printk.info(f"内容一致，无需同步: {os.path.basename(dest_path)}")
        return True
    
    try:
        shutil.copy2(src_path, dest_path)
        printk.ok(f"同步文件成功: {os.path.basename(src_path)} -> {dest_path}")
        return True
    except Exception as e:
        printk.error(f"同步文件失败 {src_path} -> {dest_path}: {str(e)}")
        return False

# Synchronise a directory recursively
def sync_dir_from_fix(src_dir: str, dest_dir: str) -> bool:
    if not os.path.isdir(src_dir):
        printk.warn(f"源目录不存在，跳过同步: {src_dir}")
        return False
    
    os.makedirs(dest_dir, exist_ok=True)
    sync_success = True
    
    for item in os.listdir(src_dir):
        src_item = os.path.join(src_dir, item)
        dest_item = os.path.join(dest_dir, item)
        
        if os.path.isfile(src_item):
            if not sync_file_from_fix(src_item, dest_item):
                sync_success = False
        elif os.path.isdir(src_item):
            if not sync_dir_from_fix(src_item, dest_item):
                sync_success = False
    
    return sync_success

# Copy the fix directory into the root directory
def sync_fix_to_root() -> bool:
    printk.warn("sync.fix 已弃用：fix/ 目录不存在，OTA 槽位机制已替代其职责，本次调用不执行任何复制。")
    return False

if __name__ == "__main__":
    sync_fix_to_root()
