'''
 *
 *      hotreset_env.py
 *      Hot-restart supervisor for the shell process.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import os
import sys
import subprocess
import time

FLAG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.hotreset')
SUPERVISED_ENV = 'PYSPOS_HOTRESET_SUPERVISED'

# Record the request for a hot restart, carrying the current time as payload.
def set_flag():
    with open(FLAG_FILE, 'w') as f:
        f.write(str(time.time()))

# Drop the restart request.
def clear_flag():
    if os.path.exists(FLAG_FILE):
        os.remove(FLAG_FILE)

# True when a hot restart was asked for and not served yet.
def check_flag():
    return os.path.exists(FLAG_FILE)

# Refuse to carry on when the slot this process
# runs from is no longer the slot the boot selected.
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


# Rename the process itself too, comm being the column ps and top show, to
# PySpOS shell.
# Tools such as fastfetch mostly read the parent's comm and only some fall back to
# argv[0], so both are set. comm is capped at 15 bytes and the kernel truncates
# silently, hence the length guard.
def _set_comm(name):
    if not sys.platform.startswith('linux'):
        return
    try:
        import ctypes
        libc = ctypes.CDLL('libc.so.6', use_errno=True)
        libc.prctl(15, name.encode('utf-8')[:15], 0, 0, 0)  # PR_SET_NAME
    except Exception:
        pass


# Entry point of the hot-restart child: drop the module cache, then run
# kernel.loop() in a clean interpreter.
# This used to be inlined into the argv of a python3 -c call, so the child's
# /proc/<pid>/cmdline was a whole pile of source code and tools reading the
# parent printed that source as the shell name. The argv is now PySpOS shell -u
# hotreset_env.py --kernel, short and already meaningful.
def _boot_kernel():
    _set_comm(SHELL_ARGV0)
    keep = ('sys', 'builtins', '__builtin__', 'importlib', 'types')
    for name in list(sys.modules.keys()):
        if name.startswith('_') or name.startswith('os') or name in keep:
            continue
        del sys.modules[name]
    sys._launcher_detected = True
    import kernel
    kernel.loop()


# Supervise the shell child, restarting it for as long as a hot restart is
# requested.
def run(pinned_slot=None):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    restart_count = 0

    while True:
        _verify_boot_context(pinned_slot)
        restart_count += 1
        clear_flag()

        # argv[0] reports the shell name and executable is the real python, so keep them apart:
        # otherwise python reads argv[0] as the script name and flags like -u are lost.
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

# Ask for a hot restart: set the flag and exit 42, letting the supervisor's loop
# restart us.
# Without a supervisor there is nobody to restart us, so exiting would just close
# the shell; in that case only a message is printed and the flag is left alone.
def trigger():
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
