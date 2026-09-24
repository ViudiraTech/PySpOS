# api.py - 提供给 apps 目录下应用程序调用的 API 接口
import os
import sys
from pathlib import Path
import uuid  # 用于生成唯一标识
import hashlib  # 用于生成哈希unlock token

# 设置路径
current_directory = Path.cwd()
main_dir = current_directory.parent
syscall = os.path.join(main_dir)

sys.path.append(syscall)

# Import printk 和 kernel 和 main 模块
import printk
import kernel
import main
import btcfg

# API: 获取系统用户名
def get_system_username():
    return kernel.get_system_username()

# API: 进入内核主循环
def enter_kernel_loop():
    kernel.loop()

# API: 退出系统
def exit_system():
    kernel.exit()

def api_confirm(prompt: str) -> bool:
    # NOTE: kernel 模块从未提供 confirm，统一走 printk.confirm（历史 bug 修复）。
    return printk.confirm(prompt)

# API: 打印信息
def api_info(message: str) -> None:
    printk.info(message)

# API: 打印不同级别的信息
def api_ok(message: str) -> None:
    printk.ok(message)

def api_error(message: str) -> None:
    printk.error(message)

def api_warn(message: str) -> None:
    printk.warn(message)

def api_print(message: str) -> None:
    print(message)

# API: 执行系统命令
def api_system(command: str) -> int:
    return os.system(command)

# API: 调整 rootstate 状态
def set_rootstate(state: bool) -> bool:
    try:
        if main.bootcfg['locked']:
            printk.warn("系统已锁定，使用临时 ROOT 方法...（重启后失效）")
            main.rootstate = state
        else:
            main.rootstate = state
            bootcfg = main.bootcfg
            bootcfg['rootstate'] = state
            # NOTE: btcfg 从未提供 save_bootcfg，正确入口是 save_bootcfg_data（历史 bug 修复）。
            btcfg.save_bootcfg_data(bootcfg)
        try:
            from common.audit import audit as _audit
            import main as _main_mod
            _audit(getattr(_main_mod, 'root_dir', os.getcwd()),
                   kernel.get_system_username(), 'set_rootstate', f"state={state}")
        except Exception:
            pass
        return True
    except Exception as e:
        printk.error(f"设置 rootstate 状态时出错: {e}")
        return False

# API：返回 ROOT 状态（bcfg中）
def get_rootstate_bcfg() -> bool:
    return main.bootcfg['rootstate']

# API：返回临时 ROOT 状态
def get_rootstate() -> bool:
    return main.rootstate

def get_lockstate() -> bool:
    return main.bootcfg['locked']

def set_lockstate(state: bool) -> bool:
    try:
        bootcfg = main.bootcfg
        bootcfg['locked'] = state
        # NOTE: 同上，save_bootcfg 不存在，修正为 save_bootcfg_data。
        btcfg.save_bootcfg_data(bootcfg)
        try:
            from common.audit import audit as _audit
            import main as _main_mod
            _audit(getattr(_main_mod, 'root_dir', os.getcwd()),
                   kernel.get_system_username(), 'set_lockstate', f"state={state}")
        except Exception:
            pass
        return True
    except Exception as e:
        printk.error(f"设置 locked 状态时出错: {e}")
        return False

# API: 基本数学运算
def add(a, b):
    return a + b

def subtract(a, b):
    return a - b

def multiply(a, b):
    return a * b

def divide(a, b):
    if b == 0:
        raise ValueError("Cannot divide by zero.")
    return a / b

# unlock bootloader 专属部分
def return_token():
    return kernel.token