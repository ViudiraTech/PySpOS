#
#   recovery.py
#   简易的模拟恢复模式
#
#   2026/1/23 By GoutouStdio
#   @2022~2026 GoutouStdio. Open all rights.

import main
import kernel
import logk
import printk
import shutil
import os
import gc
import ota
import sys
import subprocess

# 获取根目录
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

# 确保在根目录下运行
def ensure_root_directory():
    for path in (os.path.join(root_dir, "src"),
                 os.path.join(root_dir, "slot_a"),
                 os.path.join(root_dir, "slot_b")):
        if os.path.isdir(path) and path not in sys.path:
            sys.path.insert(0, path)
    current_dir = os.getcwd()
    if current_dir != root_dir:
        logk.printl("recovery", f"切换到根目录: {root_dir}", main.boot_time)
        os.chdir(root_dir)
        logk.printl("recovery", f"当前目录已切换到: {os.getcwd()}", main.boot_time)


def _require_root(operation):
    try:
        main.require_root(operation)
        return True
    except PermissionError as exc:
        printk.error(str(exc))
        return False

# 查找并终止 main 进程
def check_and_terminate_main_process():
    try:
        # 使用系统命令查找可能正在运行的 main.py 进程
        if os.name == 'nt':  # Windows
            result = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq python.exe', '/FO', 'CSV'], 
                                  capture_output=True, text=True, cwd=root_dir)
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                current_pid = str(os.getpid())
                
                for line in lines[1:]:  # 跳过标题行
                    if line:
                        parts = line.split(',')
                        if len(parts) >= 2:
                            pid = parts[1].strip('"')
                            
                            # 获取进程命令行
                            cmd_result = subprocess.run(['wmic', 'process', 'where', f'ProcessId={pid}', 'get', 'CommandLine'], 
                                                      capture_output=True, text=True)
                            if cmd_result.returncode == 0 and 'main.py' in cmd_result.stdout and pid != current_pid:
                                logk.printl("recovery", f"发现正在运行的 main 进程 (PID: {pid})，正在终止...", main.boot_time)
                                subprocess.run(['taskkill', '/PID', pid, '/F'], cwd=root_dir)
                                logk.printl("recovery", f"main 进程已终止", main.boot_time)
        else:  # Linux/Unix
            result = subprocess.run(['ps', 'aux'], capture_output=True, text=True, cwd=root_dir)
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                current_pid = str(os.getpid())
                
                for line in lines[1:]:  # 跳过标题行
                    if line and 'main.py' in line and current_pid not in line:
                        parts = line.split()
                        if len(parts) >= 2:
                            pid = parts[1]
                            logk.printl("recovery", f"发现正在运行的 main 进程 (PID: {pid})，正在终止...", main.boot_time)
                            subprocess.run(['kill', '-9', pid], cwd=root_dir)
                            logk.printl("recovery", f"main 进程已终止", main.boot_time)
    except Exception as e:
        logk.printl("recovery", f"检查进程时出错: {e}", main.boot_time)

# 主程序
def recovery_main(jumpinfo) -> str:
    # 确保在根目录下运行
    ensure_root_directory()
    
    # 检查并终止可能存在的 main 进程
    check_and_terminate_main_process()
    
    kernel.screen_clear() # 清屏
    logk.printl("recovery", f"跳入到recovery, jumpinfo={jumpinfo}", main.boot_time)
    logk.printl("recovery", f"当前目录: {os.getcwd()}", main.boot_time)
    logk.printl("recovery", f"根目录: {root_dir}", main.boot_time)
    logk.printl("recovery", "欢迎使用PySpOS Recovery，输入help获取可用命令", main.boot_time)
    while 1:
        prompt = input("recovery> ")    # 我们recovery的提示符

        if prompt == "help":
            print("help     打印本帮助信息")
            print("erase    出厂重置（清配置/槽位/缓存/答题记录，下次启动进入OOBE）")
            print("optimize 调用GC垃圾回收，让性能更高（实验性的）")
            print("ota_check  检查是否有可用的更新")
            print("ota_update 下载并安装更新")
            print("ota_status 查看OTA更新状态")
            print("ota_rollback 回滚到上一个版本")
            print("ota_clean  清理更新包文件")
            print("exit     退出Recovery\n")
        elif prompt == "erase":
            if not _require_root("recovery erase"):
                continue
            # 出厂重置：与测试共用 common.reset 工厂实现，保证无残留、
            # 且下次启动必进 OOBE（etc/.oobe_done 随 etc/ 一起被删）。
            from common.reset import factory_reset
            if not printk.confirm("erase 将删除全部用户数据并回到首次开机状态，继续？"):
                print("操作已取消\n")
            else:
                report = factory_reset(root_dir)
                for _name, (ok, msg) in report.items():
                    if ok:
                        printk.ok(msg)
                    else:
                        printk.error(msg)
                gc.collect()
                logk.printl("recovery", "出厂重置完成，重启后将进入首次开机向导（OOBE）\n", main.boot_time)
        elif prompt == "exit":
            break
        elif prompt == "optimize":
            # 触发GC垃圾回收2次
            gc.collect()
            gc.collect(2)
            logk.printl("recovery", "GC垃圾回收执行完毕！\n", main.boot_time)
        elif prompt == "ota_check":
            logk.printl("recovery", "检查是否有可用的更新...", main.boot_time)
            update_info = ota.check_cloud_update()
            if update_info:
                if update_info.get('disabled'):
                    print(f"OTA 已临时禁用: {update_info.get('reason', '')}")
                    print(f"当前版本: {update_info.get('current_version', 'unknown')}")
                elif update_info['has_update']:
                    print(f"发现新版本: {update_info['remote_version']}")
                    print(f"当前版本: {update_info['current_version']}")
                    print(f"更新内容: {update_info['release_notes']}")
                else:
                    print(f"当前已是最新版本: {update_info['current_version']}")
            else:
                print("无法获取云端版本信息（网络失败或 OTA 被禁用）。")
            print()
        elif prompt == "ota_update":
            if not _require_root("recovery OTA 更新"):
                continue
            logk.printl("recovery", "下载并安装更新...", main.boot_time)
            result = ota.download_and_install_update()
            if result:
                print("更新已成功安装，重启后生效\n")
            else:
                print("更新失败\n")
        elif prompt == "ota_status":
            logk.printl("recovery", "查看OTA更新状态...", main.boot_time)
            status = ota.get_ota_status()
            if not status.get('ota_enabled', True):
                print(f"OTA 状态: 已临时禁用 ({status.get('ota_disable_reason', '')})")
            print(f"当前槽位: {status['current_slot']}")
            print(f"当前版本: {status['current_version']}")
            print(f"其他槽位: {status['other_slot']}")
            print(f"其他版本: {status['other_version']}")
            print(f"是否有更新: {'是' if status['has_update'] else '否'}")
            if status['update_version']:
                print(f"更新版本: {status['update_version']}")
            print()
        elif prompt == "ota_rollback":
            if not _require_root("recovery OTA 回滚"):
                continue
            logk.printl("recovery", "回滚到上一个版本...", main.boot_time)
            result = ota.rollback_update()
            if result:
                print("回滚成功，重启后生效\n")
            else:
                print("回滚失败\n")
        elif prompt == "ota_clean":
            if not _require_root("recovery OTA 清理"):
                continue
            logk.printl("recovery", "清理更新包文件...", main.boot_time)
            ota.clean_update_package()
            print()
        else:
            print(f"找不到 {prompt} 命令")
    
    logk.printl("recovery", "Recovery已退出", main.boot_time)
    

