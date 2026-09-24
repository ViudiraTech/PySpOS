#!/usr/bin/env python3
#  
#   launcher.py
#   PySpOS 启动器
#
#   By GoutouStdio
#   @ 2022~2026 GoutouStdio. Open all rights.

import os
import sys
import time

def get_boot_time():
    return time.time()

def main():
    boot_time = get_boot_time()
    
    try:
        import logk
    except ImportError:
        class logk:
            @staticmethod
            def printl(module, message, boot_time):
                elapsed = time.time() - boot_time
                print(f"[{elapsed:10.6f}] {module}: {message}")
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = script_dir

    # 防御：上一次 curses 会话若异常退出，tty 会留在坏状态（回车变 ^M）。
    # 启动器是所有输入的入口，先恢复 sane，之后所有 input() 才可靠。
    # ttyutil 导入失败时回退为裸 input，保证启动器永不因此崩溃。
    sys.path.insert(0, os.path.join(root_dir, "src"))
    try:
        import ttyutil
        ttyutil.ensure_sane_tty()
    except Exception:
        import types as _types
        ttyutil = _types.SimpleNamespace(
            ensure_sane_tty=lambda: False,
            read_line=lambda prompt="": input(prompt).strip(),
            read_choice=lambda prompt="", valid=("y", "n"), default="n",
                                max_retries=0: (
                (lambda s: s if s in [v.lower() for v in valid]
                 else default)(input(prompt).strip().lower()) or default),
        )

    logk.printl("launcher", "PySpOS launcher", boot_time)
    logk.printl("launcher", f"根目录: {root_dir}", boot_time)
    
    current_slot_file = os.path.join(root_dir, "current_slot")
    current_slot = None
    slot_path = None
    use_slot = False
    
    if os.path.exists(current_slot_file):
        try:
            with open(current_slot_file, 'r') as f:
                current_slot = f.read().strip()
                slot_path = os.path.join(root_dir, current_slot)
                logk.printl("launcher", f"当前槽位: {current_slot}", boot_time)
                
                main_py = os.path.join(slot_path, "main.py")
                if os.path.exists(main_py):
                    # 循环读到合法值为止：空输入=默认 n；坏终端下 read_choice
                    # 有重试上限兜底，不会像裸 input 那样被 ^M 卡死。
                    try:
                        user_input = ttyutil.read_choice(
                            f"\n[launcher] 检测到槽位 {current_slot}，"
                            f"是否从槽位启动？(y/n)[n]: ",
                            valid=("y", "n"), default="n", max_retries=5)
                        if user_input == 'y':
                            use_slot = True
                            logk.printl("launcher", "用户选择从槽位加载系统文件", boot_time)
                        else:
                            logk.printl("launcher", "用户选择从src目录加载系统文件", boot_time)
                    except (EOFError, KeyboardInterrupt):
                        print("n")
                        logk.printl("launcher", "非交互式环境，默认从src目录加载系统文件", boot_time)
                else:
                    logk.printl("launcher", "槽位无效，将从src目录加载系统文件", boot_time)
        except Exception as e:
            logk.printl("launcher", f"读取槽位文件失败: {e}，将从src目录加载系统文件", boot_time)
    else:
        logk.printl("launcher", "未找到槽位文件，将从src目录加载系统文件", boot_time)
    
    if use_slot:
        system_path = slot_path
        logk.printl("launcher", f"从槽位加载系统文件: {system_path}", boot_time)
    else:
        system_path = os.path.join(root_dir, "src")
        logk.printl("launcher", f"从src目录加载系统文件: {system_path}", boot_time)
    
    main_py = os.path.join(system_path, "main.py")
    if not os.path.exists(main_py):
        logk.printl("launcher", f"错误: 找不到 main.py: {main_py}", boot_time)
        logk.printl("launcher", "系统文件不完整，无法启动", boot_time)
        sys.exit(1)
    
    if system_path not in sys.path:
        sys.path.insert(0, system_path)
    
    apps_path = os.path.join(system_path, "apps")
    if os.path.exists(apps_path) and apps_path not in sys.path:
        sys.path.insert(0, apps_path)
    
    os.chdir(system_path)
    logk.printl("launcher", f"工作目录: {os.getcwd()}", boot_time)
    
    sys._launcher_detected = True
    
    try:
        logk.printl("launcher", "启动热重启环境...", boot_time)
        import hotreset_env
        hotreset_env.run()
    except Exception as e:
        logk.printl("launcher", f"启动失败: {e}", boot_time)
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()