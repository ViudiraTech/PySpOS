'''
 *
 *      btcfg.py
 *      bootcfg.json reader and writer with validation.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import json
import sys
import os
import shutil
import tempfile
import printk
import hashlib

# Directory holding btcfg.py
# Ask common.paths first, falling back to the old logic if that fails
script_dir = os.path.dirname(os.path.abspath(__file__))
try:
    from common.paths import get_root_dir as _get_root_dir
    root_dir = _get_root_dir(script_dir)
except Exception:
    if os.path.basename(script_dir) == 'src':
        # Running from src, so the root is its parent
        root_dir = os.path.dirname(script_dir)
    elif os.path.basename(script_dir) in ['slot_a', 'slot_b']:
        # Running from a slot directory, so the root is its parent
        root_dir = os.path.dirname(script_dir)
    else:
        # Anything else, treat the directory itself as the root
        root_dir = script_dir

# Where bootcfg.json lives, under the root's etc directory
boot_config = os.path.join(root_dir, 'etc', 'bootcfg.json')

# The in-memory bootcfg
bootcfg = {}

# Hash the config, excluding the checksum field itself.
def calculate_checksum(cfg):
    cfg_copy = cfg.copy()
    cfg_copy.pop('checksum', None)
    return hashlib.sha256(json.dumps(cfg_copy, sort_keys=True).encode()).hexdigest()

# Shared handler for a rejected or corrupt bootcfg: offer a repair, else stop.
def _handle_bootcfg_error(error_msg: str, allow_repair: bool = True) -> None:
    print(f"\033[31m{error_msg}\033[0m")
    if os.environ.get("PYSPOS_BOOT_LOCKED") == "1":
        raise RuntimeError(error_msg)
    if allow_repair and printk.confirm(f"系统启动失败（原因：{error_msg}），是否尝试自动修复？"):
        create_bootcfg()
        print("操作成功完成\n")
    else:
        input("按下任意键关闭系统...")
        sys.exit(0)

# Create or repair bootcfg.json.
# 2026-09-24: dropped the historical raise, which had made the repair entry point unreachable,
# and replaced it with: back up the broken etc/ first, then write the defaults. Set PYSPOS_BTCFG_NOREPAIR=1 for the old behaviour.
def create_bootcfg():
    global bootcfg
    if os.environ.get("PYSPOS_BTCFG_NOREPAIR") == "1":
        raise RuntimeError("create_bootcfg 已被环境变量禁用（PYSPOS_BTCFG_NOREPAIR=1）")
    print("自动创建或修复 bootcfg 实用工具")
    print("本程序会自动写入：校验开启状态和root关闭状态")
    if printk.confirm("\n 是否修复 bootcfg？"):
        etc_dir = os.path.join(root_dir, 'etc')
        if os.path.isdir(etc_dir):
            import time as _time
            backup = etc_dir + f".bak-{_time.strftime('%Y%m%d-%H%M%S')}"
            try:
                os.rename(etc_dir, backup)
                printk.ok(f"create_bootcfg: 已备份损坏的引导文件到 {backup}")
            except OSError:
                shutil.rmtree(etc_dir, ignore_errors=True)
                printk.ok("create_bootcfg: 损坏的引导文件已删除！")
        else:
            pass
    
        printk.info("create_bootcfg: 尝试创建新的引导文件夹")
        os.makedirs(etc_dir, exist_ok=True)
        printk.ok("create_bootcfg: 引导文件夹创建成功！")
        bootcfg['locked'] = False
        bootcfg['rootstate'] = False
        # Recompute the checksum
        bootcfg['checksum'] = calculate_checksum(bootcfg)
        printk.ok("create_bootcfg: 成功写入了默认配置！")
        save_bootcfg_data(bootcfg)
        printk.ok("create_bootcfg: 所有步骤全部完成！")

# Check that a bootcfg value is a dict with bool 'locked' and 'rootstate', else raise ValueError.
def _validate_bootcfg(value):
    if not isinstance(value, dict):
        raise ValueError("配置文件必须是 JSON 对象")
    for key in ("locked", "rootstate"):
        if not isinstance(value.get(key), bool):
            raise ValueError(f"配置项 {key} 必须是布尔值")
    return value


# Write JSON to a temporary file in the same directory, fsync it, then os.replace it into place and chmod 600.
def _write_json_atomic(path, value):
    parent = os.path.dirname(path)
    os.makedirs(parent, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".bootcfg-", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


# Store the boot config, refreshing its checksum first.
def save_bootcfg_data(bootcfg_data):
    try:
        _validate_bootcfg(bootcfg_data)
        bootcfg_data['checksum'] = calculate_checksum(bootcfg_data)
        _write_json_atomic(boot_config, bootcfg_data)
    except Exception as e:
        printk.error(f"保存引导配置时出错: {e}")
        raise

# Return one value from the in-memory boot config.
def get_bootcfg(cfg):
    global bootcfg
    return bootcfg[cfg]

# Set a boot config flag to True and save.
def set_bootcfg_to_true(cfg):
    global bootcfg
    bootcfg[cfg] = True
    save_bootcfg_data(bootcfg)

# Set a boot config flag to False and save.
def set_bootcfg_to_false(cfg):
    global bootcfg
    bootcfg[cfg] = False
    save_bootcfg_data(bootcfg)

# Set any boot config value and save.
def set_bootcfg_value(cfg, value):
    global bootcfg
    bootcfg[cfg] = value
    save_bootcfg_data(bootcfg)

# Load and verify bootcfg.json, writing a default when it is missing and repairing it when it is bad.
def load_bootcfg():
    global bootcfg
    try:
        with open(boot_config, 'r') as f:
            bootcfg = json.load(f)
        
        _validate_bootcfg(bootcfg)
        current_checksum = bootcfg.get('checksum')
        if not current_checksum:
            _handle_bootcfg_error("配置文件缺少校验和，可能被篡改！")
        
        expected_checksum = calculate_checksum(bootcfg)
        if current_checksum != expected_checksum:
            _handle_bootcfg_error("配置文件校验失败，可能被篡改！")
        
        return bootcfg
    except FileNotFoundError as e:
        # Create a default config when the file is missing
        print(f"bootcfg.json 不存在，正在创建默认配置...")
        bootcfg = {
            'locked': False,
            'rootstate': False,
            'checksum': ''
        }
        bootcfg['checksum'] = calculate_checksum(bootcfg)
        save_bootcfg_data(bootcfg)
        print("默认配置创建成功！")
        return bootcfg
    except json.JSONDecodeError as e:
        _handle_bootcfg_error(f"bootcfg.json 已损坏（{e}）")
    except ValueError as e:
        _handle_bootcfg_error(f"检测到非法修改启动配置，拒绝启动。")

# Load the config as soon as this module is imported
load_bootcfg()
