import argparse
import os
import shutil
import sys

import secure_boot


def _safe_slot_path(root_dir, slot):
    if slot not in secure_boot.SLOTS:
        raise ValueError("槽位必须是 slot_a 或 slot_b")
    root = os.path.realpath(root_dir)
    path = os.path.realpath(os.path.join(root, slot))
    if os.path.commonpath((root, path)) != root or os.path.basename(path) != slot:
        raise RuntimeError("槽位路径越界")
    return path


def wipe_slots(root_dir, slots, assume_yes=False):
    root_dir = os.path.abspath(root_dir)
    if secure_boot.read_locked(root_dir):
        raise RuntimeError("当前是 LOCKED 信任域，拒绝删除槽位")
    if not assume_yes:
        answer = input(f"将删除槽位 {', '.join(slots)}，继续？(y/n): ").strip().lower()
        if answer not in ("y", "yes"):
            print("已取消")
            return False
    for slot in slots:
        path = _safe_slot_path(root_dir, slot)
        if os.path.islink(path):
            os.unlink(path)
        elif os.path.isdir(path):
            shutil.rmtree(path)
        elif os.path.exists(path):
            raise RuntimeError(f"槽位路径不是目录: {path}")
        print(f"已删除槽位: {slot}")
    print("policy、rollback state 和 etc 未删除；下次启动将从 src 重建。")
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description="清空 PySpOS 开发槽位")
    parser.add_argument("--root-dir", default=os.path.dirname(os.path.abspath(__file__)))
    parser.add_argument("--slot", action="append", choices=secure_boot.SLOTS)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args(argv)
    slots = list(secure_boot.SLOTS) if args.all else (args.slot or [])
    if not slots:
        parser.error("请指定 --slot 或 --all")
    try:
        return 0 if wipe_slots(args.root_dir, slots, args.yes) else 1
    except Exception as exc:
        print(f"清空失败: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
