#
#   common/paths.py
#   统一的根目录/槽位路径解析（替代原来散落在 main/ota/recovery/btcfg 的 5 份拷贝）。
#
#   约定：
#   - Caller 传任意文件所在目录（通常是 __file__ 的 dirname）；
#   - 若该目录名为 src / slot_a / slot_b，则根目录为其父目录；
#   - 否则回退为该目录本身（兼容单文件/测试场景）。
#
import os

SLOT_DIRS = ("slot_a", "slot_b")
SRC_DIR = "src"


def get_root_dir(caller_dir: str) -> str:
    caller_dir = os.path.abspath(caller_dir)
    base = os.path.basename(caller_dir)
    if base == SRC_DIR or base in SLOT_DIRS:
        return os.path.dirname(caller_dir)
    return caller_dir


def get_root_dir_for_file(caller_file: str) -> str:
    return get_root_dir(os.path.dirname(os.path.abspath(caller_file)))


def is_slot_dir(path: str) -> bool:
    return os.path.basename(os.path.abspath(path)) in SLOT_DIRS


def slot_path(root_dir: str, slot: str) -> str:
    return os.path.join(root_dir, slot)


def read_current_slot(root_dir: str, default: str = "slot_a") -> str:
    try:
        with open(os.path.join(root_dir, "current_slot"), "r", encoding="utf-8") as f:
            slot = f.read().strip()
            if slot in SLOT_DIRS:
                return slot
    except OSError:
        pass
    return default
