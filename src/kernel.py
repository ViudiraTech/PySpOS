'''
 *
 *      kernel.py
 *      Boot sequence and the main command loop.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import printk
import os
import sys
import subprocess
import bootmode
import main
import time
import shutil
from fs import current_dir
import logk
import ota

# The PySpOS ASCII logo, printed once at boot.
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

# Logical CPU count reported at boot.
cores = os.cpu_count()

# Cached host user name: the lookup below is not free.
_cached_username = None

# Host user name, cached: $USER, getlogin, whoami, then pwd or win32api.
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

# Print the two-line prompt and return the line the input call needs as its
# argument.
def print_prompt():
    import syslocale
    # Read the working directory live so that cd shows up at once.
    current_dir_name = os.path.basename(os.getcwd())
    # OOBE may set a display name; fall back to the system user (bootcfg may lack the key).
    username = main.bootcfg.get('display_name') or get_system_username()
    current_time = syslocale.now_str("%H:%M:%S")

    if main.is_root():
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

# Clear the terminal on Windows and everywhere else alike.
def screen_clear():
    if os.name == "nt":
        os.system("cls")
    else:
        os.system("clear")    


# Serve fastboot instead of the shell, then act on how the client left.
# Returns only when fastboot is done; the caller restarts or shuts down, so a
# "reboot bootloader" from the client comes straight back into this function.
def _fastboot_boot():
    import fastboot
    import hotreset_env
    logk.printl("kernel", "启动请求指向 fastboot，跳过 OOBE 与 shell", main.boot_time)
    fastboot.fastboot_main("boot")
    # fastboot_main only returns for a leave request. A plain reboot keeps no
    # pending request, so the next boot lands in the system; "reboot
    # bootloader" left the request in place and we would come back here.
    if bootmode.wants_fastboot(main.root_dir):
        logk.printl("kernel", "fastboot 请求仍在，重启后继续 fastboot", main.boot_time)
    else:
        logk.printl("kernel", "fastboot 已结束，重启进入系统", main.boot_time)
    if os.environ.get("PYSPOS_HOTRESET_SUPERVISED") == "1":
        hotreset_env.trigger()
    raise SystemExit(0)


# The main command loop: OOBE, boot commit, logo,
# OTA init, then read and run until EOF or Ctrl-C.
def loop():
    from syslocale import _
    import oobe
    import main as _main_mod

    # A pending fastboot request outranks the wizard and the shell: that is
    # the whole point of "reboot bootloader", and how a locked device is
    # reached at all.
    if bootmode.wants_fastboot(_main_mod.root_dir):
        _fastboot_boot()

    # First-boot wizard: a missing etc/.oobe_done means run it (a factory reset deletes it).
    # It lives in kernel.loop, not main.main(): the hotreset_env boot path enters
    # kernel.loop() directly, so the wrong place here would skip OOBE on a real boot.
    oobe_ok = oobe.maybe_run_oobe(_main_mod.root_dir)
    if oobe_ok and os.environ.get("PYSPOS_BOOT_VERIFIED") == "1":
        try:
            import secure_boot
            slot = os.environ.get("PYSPOS_BOOT_SLOT")
            manifest = secure_boot.verify_slot(_main_mod.root_dir, slot, locked=True)
            secure_boot.mark_boot_success(_main_mod.root_dir, slot, manifest)
        except Exception as exc:
            logk.printl("kernel", f"无法提交启动状态: {exc}", main.boot_time)
            raise

    screen_clear()
    username = main.bootcfg.get('display_name') or get_system_username()
    print(ascii_logo)

    ota.ota_init()

    logk.printl("kernel", f"你有 {cores} 个 CPU 逻辑核心", main.boot_time)
    print(_("boot.welcome", user=username))
    print()
    while 1:
        try:
            prompt = input(print_prompt())
            main.handle_command(prompt)
        except EOFError:
            return
        except KeyboardInterrupt:
            return
        except Exception as e:
            print(f"error: {e}")

# Drop the __pycache__ directories and shut the system down.
def exit():
    if os.path.isdir("__pycache__"):
        try:
            shutil.rmtree("__pycache__")
            printk.ok("已删除缓存目录 __pycache__")
        except Exception as e:
            printk.error(f"无法删除缓存目录: {e}")
    else:
        printk.warn("未找到缓存目录 __pycache__，无需删除")

    # current_dir is the function from fs, so it has to be called: formatting
    # it directly produced a path starting with "<function ...>" and this
    # branch could never match.
    apps_cache = os.path.join(current_dir(), "apps", "__pycache__")
    if os.path.isdir(apps_cache):
        try:
            shutil.rmtree(apps_cache)
            printk.ok("已删除软件缓存目录 apps/__pycache__")
        except Exception as e:
            printk.error(f"无法删除缓存目录: {e}")
    else:
        printk.warn("未找到缓存目录 apps/__pycache__，无需删除")
    printk.info("正在关闭 PySpOS 操作系统...")
    time.sleep(1)
    sys.exit(0)