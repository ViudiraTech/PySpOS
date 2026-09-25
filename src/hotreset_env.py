#
#   hotreset_env.py
#   PySpOS 热重启环境
#
#   By GoutouStdio
#   @ 2022~2026 GoutouStdio. Open all rights.

import os
import sys
import subprocess
import time

FLAG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.hotreset')

def set_flag():
    with open(FLAG_FILE, 'w') as f:
        f.write(str(time.time()))

def clear_flag():
    if os.path.exists(FLAG_FILE):
        os.remove(FLAG_FILE)

def check_flag():
    return os.path.exists(FLAG_FILE)

def _verify_boot_context():
    root_dir = os.environ.get("PYSPOS_BOOT_ROOT")
    if not root_dir:
        return
    import secure_boot
    locked = os.environ.get("PYSPOS_BOOT_LOCKED") == "1"
    current_slot = os.environ.get("PYSPOS_BOOT_SLOT") or None
    selection = secure_boot.prepare_boot(root_dir, locked, legacy_slot=current_slot)
    if locked and selection is None:
        raise RuntimeError("热重启前 Bootloader 验证失败")
    if selection and os.path.realpath(os.path.join(root_dir, selection["slot"])) \
            != os.path.realpath(os.path.dirname(os.path.abspath(__file__))):
        raise RuntimeError("热重启期间活动槽位发生变化")


def _boot_kernel():
    """热重启子进程入口：清掉模块缓存后在干净解释器里进 kernel.loop()。

    以前这段逻辑是内联在 `python3 -c` 的 argv 里，结果子进程在
    /proc/<pid>/cmdline 里就是一整坨源码：ps、top、fastfetch 这类
    工具读父进程命令行时会直接把这坨源码当成 shell 名打出来
    （fastfetch 的 Shell 栏）。改走 `hotreset_env.py --kernel`
    这个短 argv 后，命令行是可读的。
    """
    keep = ('sys', 'builtins', '__builtin__', 'importlib', 'types')
    for name in list(sys.modules.keys()):
        if name.startswith('_') or name.startswith('os') or name in keep:
            continue
        del sys.modules[name]
    sys._launcher_detected = True
    import kernel
    kernel.loop()


def run():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    restart_count = 0

    while True:
        _verify_boot_context()
        restart_count += 1
        clear_flag()

        cmd = [sys.executable, '-u', os.path.abspath(__file__), '--kernel']
        
        try:
            child_env = os.environ.copy()
            root_dir = os.path.dirname(script_dir)
            python_paths = [p for p in (root_dir, script_dir)
                            if p and os.path.isdir(p)]
            old_pythonpath = child_env.get("PYTHONPATH")
            if old_pythonpath:
                python_paths.append(old_pythonpath)
            child_env["PYTHONPATH"] = os.pathsep.join(python_paths)
            process = subprocess.Popen(
                cmd,
                cwd=script_dir,
                stdin=sys.stdin,
                stdout=sys.stdout,
                stderr=sys.stderr,
                env=child_env
            )
            
            return_code = process.wait()
            
            if check_flag():
                continue
            else:
                break
                
        except KeyboardInterrupt:
            if process.poll() is None:
                process.terminate()
                process.wait()
            break
        except Exception as e:
            print(f"Error: {e}")
            break

def trigger():
    import printk
    printk.info("Hot resetting...")
    set_flag()
    sys.exit(42)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == '--kernel':
        _boot_kernel()
    else:
        run()
