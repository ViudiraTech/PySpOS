#!/usr/bin/env python3
import os
import sys
import time


def get_boot_time():
    return time.time()


def _log(message):
    print(f"[launcher] {message}", flush=True)


def _read_choice(prompt, valid=("y", "n"), default="n", max_retries=5):
    for _ in range(max_retries):
        try:
            value = input(prompt).strip().lower()
        except (EOFError, KeyboardInterrupt):
            return default
        if value in valid:
            return value
    return default


def _read_legacy_slot(root_dir):
    try:
        with open(os.path.join(root_dir, "current_slot"), "r", encoding="utf-8") as stream:
            value = stream.read().strip()
    except OSError:
        return None
    return value if value in ("slot_a", "slot_b") else None


def _load_terminal_helper(system_path):
    sys.path.insert(0, system_path)
    try:
        import ttyutil
        ttyutil.ensure_sane_tty()
        return ttyutil
    except Exception:
        return None


def main():
    boot_time = get_boot_time()
    script_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = script_dir

    try:
        import secure_boot
    except Exception as exc:
        _log(f"无法加载 Bootloader 验证器: {exc}")
        return 1

    try:
        locked = secure_boot.read_locked(root_dir)
        secure_boot.configure_runtime_keys(root_dir, locked)
        selection = secure_boot.prepare_boot(
            root_dir, locked, legacy_slot=_read_legacy_slot(root_dir))
    except secure_boot.BootVerificationError as exc:
        _log(f"启动被拒绝: {exc}")
        return 1
    except Exception as exc:
        _log(f"启动验证失败: {exc}")
        return 1

    if selection is None:
        if locked:
            _log("锁定模式禁止回退到未签名的 src 目录")
            return 1
        system_path = os.path.join(root_dir, "src")
        _log("未找到可启动槽位，进入未签名开发模式")
    else:
        slot = selection["slot"]
        system_path = os.path.join(root_dir, slot)
        if selection.get("manifest") is not None:
            _log(f"槽位 {slot} 签名验证通过")
        else:
            _log(f"警告：槽位 {slot} 未签名，仅允许未锁定开发模式启动")

    main_py = os.path.join(system_path, "main.py")
    if not os.path.isfile(main_py):
        _log(f"错误: 找不到 main.py: {main_py}")
        return 1

    ttyutil = _load_terminal_helper(system_path)
    if ttyutil is not None and hasattr(ttyutil, "read_choice"):
        ttyutil.read_choice = _read_choice

    apps_path = os.path.join(system_path, "apps")
    if os.path.isdir(apps_path) and apps_path not in sys.path:
        sys.path.insert(0, apps_path)

    os.chdir(system_path)
    _log(f"工作目录: {os.getcwd()}")
    _log(f"Bootloader 状态: {'LOCKED' if locked else 'UNLOCKED'}")

    os.environ["PYSPOS_BOOT_ROOT"] = root_dir
    os.environ["PYSPOS_BOOT_SYSTEM"] = system_path
    os.environ["PYSPOS_BOOT_SLOT"] = selection["slot"] if selection else ""
    os.environ["PYSPOS_BOOT_VERIFIED"] = "1" if selection and selection.get("manifest") else "0"
    os.environ["PYSPOS_BOOT_LOCKED"] = "1" if locked else "0"
    sys._launcher_detected = True

    try:
        _log("启动热重启环境...")
        import hotreset_env
        hotreset_env.run()
    except Exception as exc:
        _log(f"启动失败: {exc}")
        import traceback
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
