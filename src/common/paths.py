'''
 *
 *      paths.py
 *      Shared root directory and slot path resolution.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import os

SLOT_DIRS = ("slot_a", "slot_b")
SRC_DIR = "src"


# Resolve the device root from any file's directory: the parent when
# the directory is src/ or a slot, otherwise the directory itself.
def get_root_dir(caller_dir: str) -> str:
    caller_dir = os.path.abspath(caller_dir)
    base = os.path.basename(caller_dir)
    if base == SRC_DIR or base in SLOT_DIRS:
        return os.path.dirname(caller_dir)
    return caller_dir


# Same as get_root_dir, for a caller holding a file path.
def get_root_dir_for_file(caller_file: str) -> str:
    return get_root_dir(os.path.dirname(os.path.abspath(caller_file)))


# Report whether the path is one of the slot directories.
def is_slot_dir(path: str) -> bool:
    return os.path.basename(os.path.abspath(path)) in SLOT_DIRS


# Path of a named slot under the device root.
def slot_path(root_dir: str, slot: str) -> str:
    return os.path.join(root_dir, slot)


# Read current_slot, falling back to default when it is missing or
# names a slot that does not exist.
def read_current_slot(root_dir: str, default: str = "slot_a") -> str:
    try:
        with open(os.path.join(root_dir, "current_slot"), "r", encoding="utf-8") as f:
            slot = f.read().strip()
            if slot in SLOT_DIRS:
                return slot
    except OSError:
        pass
    return default
