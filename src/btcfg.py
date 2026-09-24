#
#   btcfg.py
#   bootcfg.json 操作模块
#
#   By GoutouStdio
#   @ 2022~2026 GoutouStdio. Open all rights.

import json
import sys
import os
import shutil
import printk
import hashlib

# 获取btcfg.py所在目录
# 统一走 common.paths，失败时回退到历史逻辑。
script_dir = os.path.dirname(os.path.abspath(__file__))
try:
    from common.paths import get_root_dir as _get_root_dir
    root_dir = _get_root_dir(script_dir)
except Exception:
    if os.path.basename(script_dir) == 'src':
        # 在src目录中，根目录是src的父目录
        root_dir = os.path.dirname(script_dir)
    elif os.path.basename(script_dir) in ['slot_a', 'slot_b']:
        # 在槽位目录中，根目录是槽位的父目录
        root_dir = os.path.dirname(script_dir)
    else:
        # 其他情况，使用当前目录作为根目录
        root_dir = script_dir

# bootcfg.json 的位置（使用根目录的etc文件夹）
boot_config = os.path.join(root_dir, 'etc', 'bootcfg.json')

# 全局bootcfg变量
bootcfg = {}

# 计算配置校验和（排除校验和自身）
def calculate_checksum(cfg):
    cfg_copy = cfg.copy()
    cfg_copy.pop('checksum', None)
    return hashlib.sha256(json.dumps(cfg_copy, sort_keys=True).encode()).hexdigest()

# 公共异常处理函数
def _handle_bootcfg_error(error_msg: str, allow_repair: bool = True) -> None:
    print(f"\033[31m{error_msg}\033[0m")
    if allow_repair and printk.confirm(f"系统启动失败（原因：{error_msg}），是否尝试自动修复？"):
        create_bootcfg()
        print("操作成功完成\n")
    else:
        input("按下任意键关闭系统...")
        sys.exit(0)

# 创建/修复 bootcfg 文件
# 2026-09-24: 移除历史 raise（此前直接抛异常导致自动修复入口不可用），
# 改为：先备份损坏的 etc/ 再写入默认配置。如需恢复旧行为，置环境变量 PYSPOS_BTCFG_NOREPAIR=1。
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
        bootcfg['locked'] = True
        bootcfg['rootstate'] = False
        # 计算并添加校验和
        bootcfg['checksum'] = calculate_checksum(bootcfg)
        printk.ok("create_bootcfg: 成功写入了默认配置！")
        save_bootcfg_data(bootcfg)
        printk.ok("create_bootcfg: 所有步骤全部完成！")

# 存储引导配置
def save_bootcfg_data(bootcfg_data):
    try:
        # 保存前更新校验和
        bootcfg_data['checksum'] = calculate_checksum(bootcfg_data)
        os.makedirs(os.path.dirname(boot_config), exist_ok=True)
        with open(boot_config, 'w') as f:
            json.dump(bootcfg_data, f)
    except Exception as e:
        printk.error(f"保存引导配置时出错: {e}")

# 读取引导配置
def get_bootcfg(cfg):
    global bootcfg
    return bootcfg[cfg]

# 设置引导配置为 True
def set_bootcfg_to_true(cfg):
    global bootcfg
    bootcfg[cfg] = True
    save_bootcfg_data(bootcfg)

# 设置引导配置为 False
def set_bootcfg_to_false(cfg):
    global bootcfg
    bootcfg[cfg] = False
    save_bootcfg_data(bootcfg)

# 通用设置引导配置值
def set_bootcfg_value(cfg, value):
    global bootcfg
    bootcfg[cfg] = value
    save_bootcfg_data(bootcfg)

# 加载引导配置
def load_bootcfg():
    global bootcfg
    try:
        with open(boot_config, 'r') as f:
            bootcfg = json.load(f)
        
        # 校验和验证
        current_checksum = bootcfg.get('checksum')
        if not current_checksum:
            _handle_bootcfg_error("配置文件缺少校验和，可能被篡改！")
        
        expected_checksum = calculate_checksum(bootcfg)
        if current_checksum != expected_checksum:
            _handle_bootcfg_error("配置文件校验失败，可能被篡改！")
        
        return bootcfg
    except FileNotFoundError as e:
        # 文件不存在时自动创建默认配置
        print(f"bootcfg.json 不存在，正在创建默认配置...")
        bootcfg = {
            'locked': True,
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

# 模块加载时自动加载配置
load_bootcfg()