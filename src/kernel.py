#   
#   kernel.py
#   PySpOS 主程序
#
#   By GoutouStdio
#   @ 2022~2026 GoutouStdio. Open all rights.

import printk
import os
import sys
import subprocess
import main
import time
import shutil
from fs import current_dir
import uuid
import hashlib
import random
import logk
import ota

# PySpOS ASCII 艺术 Logo   
ascii_logo = r'''
 ____            ____             ___    ____      _____
|  _ \   _   _  / ___|   _ __    / _ \  / ___|    |___ / 
| |_) | | | | | \___ \  | '_ \  | | | | \___ \      |_ \ 
|  __/  | |_| |  ___) | | |_) | | |_| |  ___) |    ___) |
|_|      \__, | |____/  | .__/   \___/  |____/    |____/ 
         |___/          |_|           

PySpOS 模拟操作系统 版本 3
@ 2022~2026 GoutouStdio（或狗头工作室）保留所有权利。                   
'''

# 逻辑核心计数
cores = os.cpu_count()

# 获取系统用户名（带缓存）
_cached_username = None

def get_system_username() -> str:
    global _cached_username
    if _cached_username is not None:
        return _cached_username

    username = os.getenv("USER") or os.getenv("USERNAME")
    if username and username.strip():
        _cached_username = username.strip()
        return _cached_username

    try:
        username = os.getlogin()
        if username.strip():
            _cached_username = username.strip()
            return _cached_username
    except OSError:
        pass

    try:
        result = subprocess.check_output(
            ["whoami"],
            encoding="utf-8",
            stderr=subprocess.DEVNULL
        ).strip()
        if sys.platform == "win32":
            username = result.split("\\")[-1]
        else:
            username = result
        if username.strip():
            _cached_username = username.strip()
            return _cached_username
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        pass

    if sys.platform.startswith("linux") or sys.platform == "darwin":
        try:
            import pwd
            username = pwd.getpwuid(os.getuid()).pw_name
            _cached_username = username.strip()
            return _cached_username
        except (ImportError, ModuleNotFoundError):
            pass
    elif sys.platform == "win32":
        try:
            import win32api
            username = win32api.GetUserName()
            _cached_username = username.strip()
            return _cached_username
        except (ImportError, ModuleNotFoundError):
            pass

    raise RuntimeError("无法获取用户名")

# 生成Unlock Token
def generate_token():
    base_info = f"{uuid.getnode()}-{random.randint(1000,9999)}-unlock_token-{get_system_username()}"
    token = hashlib.sha256(base_info.encode('utf-8')).hexdigest()
    return token

# unlock token
token = generate_token()

# 打印提示符
def print_prompt():
    # 实时获取当前工作目录
    current_dir_name = os.path.basename(os.getcwd())
    username = get_system_username()
    current_time = time.strftime("%H:%M:%S")

    if main.rootstate or main.bootcfg.get('rootstate', False):
        prompt_header = (
            f"┌──\033[91m({username}@PySPOS)─[ROOT]─[\033[93m{current_time}\033[91m]─(\033[94m/%s\033[91m)\033[0m"
            % current_dir_name
        )
        prompt_line = f"└─\033[91m\033[94m#\033[0m "
    else:
        prompt_header = (
            f"┌──\033[92m({username}@PySPOS)─[\033[93m{current_time}\033[92m]─(\033[94m/%s\033[92m)\033[0m"
            % current_dir_name
        )
        prompt_line = f"└─\033[92m\033[94m$\033[0m "

    print(prompt_header)
    return prompt_line

# 清屏
def screen_clear():
    if os.name == "nt":
        os.system("cls")
    else:
        os.system("clear")    

# 内核主循环
def loop():
    screen_clear()
    username = get_system_username()
    print(ascii_logo)

    ota.ota_init()

    # 2026-09-24 安全加固：启动日志不再明文打印完整 Token（历史行为直接泄露），
    # 仅显示前 6 位 + 获取方式；完整 Token 仍可通过官方 gettoken 答题流程获取。
    logk.printl("kernel", f"你有 {cores} 个 CPU 逻辑核心，Token = {token[:6]}****（完整 Token 请用 open gettoken 获取）", main.boot_time)
    print(f"欢迎使用 PySpOS 操作系统，{username}！")
    print()
    while 1:
        try:
            prompt = input(print_prompt())
            main.handle_command(prompt)
        except Exception as e:
            print(f"error: {e}")

# 退出PySpOS
def exit():
    if os.path.isdir("__pycache__"):
        try:
            shutil.rmtree("__pycache__")
            shutil.rmtree("apps/__pycache__")
            printk.ok("已删除缓存目录 __pycache__")
        except Exception as e:
            printk.error(f"无法删除缓存目录: {e}")
    else:
        printk.warn("未找到缓存目录 __pycache__，无需删除")
    
    if os.path.isdir("%s/apps/__pycache__" % current_dir):
        try:
            shutil.rmtree("%s/apps/__pycache__" % current_dir)
            printk.ok("已删除软件缓存目录 apps/__pycache__")
        except Exception as e:
            printk.error(f"无法删除缓存目录: {e}")
    else:
        printk.warn("pass...")
    printk.info("正在关闭 PySpOS 操作系统...")
    time.sleep(1)
    sys.exit(0)