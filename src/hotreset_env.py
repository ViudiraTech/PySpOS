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
SUPERVISED_ENV = 'PYSPOS_HOTRESET_SUPERVISED'

def set_flag():
    with open(FLAG_FILE, 'w') as f:
        f.write(str(time.time()))

def clear_flag():
    if os.path.exists(FLAG_FILE):
        os.remove(FLAG_FILE)

def check_flag():
    return os.path.exists(FLAG_FILE)

def _verify_boot_context(pinned_slot=None):
    root_dir = os.environ.get("PYSPOS_BOOT_ROOT")
    if not root_dir:
        return
    here = os.path.realpath(os.path.dirname(os.path.abspath(__file__)))
    if pinned_slot:
        target = os.path.realpath(os.path.join(root_dir, pinned_slot))
        if here != target:
            raise RuntimeError("热重启期间指定槽位发生变化")
        return
    import secure_boot
    locked = os.environ.get("PYSPOS_BOOT_LOCKED") == "1"
    current_slot = os.environ.get("PYSPOS_BOOT_SLOT") or None
    selection = secure_boot.prepare_boot(root_dir, locked, legacy_slot=current_slot)
    if locked and selection is None:
        raise RuntimeError("热重启前 Bootloader 验证失败")
    if selection and os.path.realpath(os.path.join(root_dir, selection["slot"])) != here:
        raise RuntimeError("热重启期间活动槽位发生变化")


SHELL_ARGV0 = 'PySpOS shell'


def _set_comm(name):
    """把进程名（comm，ps/top/htop 那一栏）也改成 PySpOS shell。

    fastfetch 之类的工具读父进程时多数看 comm，只有部分（如某些
    fastfetch 版本）回退到 argv[0]；两边都设上才稳。comm 上限 15 字节，
    超了内核静默截断，这里做个长度保护。
    """
    if not sys.platform.startswith('linux'):
        return
    try:
        import ctypes
        libc = ctypes.CDLL('libc.so.6', use_errno=True)
        libc.prctl(15, name.encode('utf-8')[:15], 0, 0, 0)  # PR_SET_NAME
    except Exception:
        pass


def _boot_kernel():
    """热重启子进程入口：清掉模块缓存后在干净解释器里进 kernel.loop()。

    这段逻辑以前是内联在 `python3 -c` 的 argv 里，于是子进程在
    /proc/<pid>/cmdline 里就是一整坨源码：ps、top、fastfetch 这类读
    父进程的工具会把源码当 shell 名打出来。现在改成
    `PySpOS shell -u hotreset_env.py --kernel` 这个既有名字又短的
    argv，工具看到的 shell 名就是 PySpOS shell。
    """
    _set_comm(SHELL_ARGV0)
    keep = ('sys', 'builtins', '__builtin__', 'importlib', 'types')
    for name in list(sys.modules.keys()):
        if name.startswith('_') or name.startswith('os') or name in keep:
            continue
        del sys.modules[name]
    sys._launcher_detected = True
    import kernel
    kernel.loop()


def run(pinned_slot=None):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    restart_count = 0

    while True:
        _verify_boot_context(pinned_slot)
        restart_count += 1
        clear_flag()

        # argv[0] 报 shell 名，executable 才是真的 python —— 两者要分开，
        # 否则 python 会把 argv[0] 当脚本名去解释，-u 之类的开关就废了。
        cmd = [SHELL_ARGV0, '-u', os.path.abspath(__file__), '--kernel']
        
        try:
            child_env = os.environ.copy()
            root_dir = os.path.dirname(script_dir)
            python_paths = [p for p in (root_dir, script_dir)
                            if p and os.path.isdir(p)]
            old_pythonpath = child_env.get("PYTHONPATH")
            if old_pythonpath:
                python_paths.append(old_pythonpath)
            child_env["PYTHONPATH"] = os.pathsep.join(python_paths)
            child_env[SUPERVISED_ENV] = "1"
            process = subprocess.Popen(
                cmd,
                executable=sys.executable,
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
    """请求热重启：置 flag 后以 42 退出，由 run() 的监督循环重启。

    没有监督进程时不能退——退出去就没谁来重启，等于把 shell 关了。
    这时只提示，不动 flag。
    """
    import printk
    if os.environ.get(SUPERVISED_ENV) != "1":
        printk.warn("当前启动方式没有热重启监督进程，hotreset 不可用"
                    "（请用 launcher.py 启动）")
        return
    printk.info("Hot resetting...")
    set_flag()
    sys.exit(42)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == '--kernel':
        _boot_kernel()
    else:
        run()
