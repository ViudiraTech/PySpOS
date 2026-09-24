#
#   shell/dispatch.py
#   命令分发：注册表 + 重定向/管道 + handle_command（由 main.py 拆分而来）。
#

import os
import printk
import main
import commands as cmd_registry
from . import sys_cmds, elf_cmd, ota_cmds, proc_cmds


# 命令历史（2026-09-24 新增：history 命令 + readline 持久化）
_cmd_history = []
try:
    import readline as _readline
    _hist_file = os.path.join(os.path.expanduser("~"), ".pyspos_history")
    try:
        if os.path.exists(_hist_file):
            _readline.read_history_file(_hist_file)
    except OSError:
        pass
    import atexit as _atexit

    def _save_history():
        try:
            _readline.write_history_file(_hist_file)
        except OSError:
            pass

    _atexit.register(_save_history)
except ImportError:
    _readline = None


# 注册到命令注册表（供外部/测试查询）
for _n, _f, _h in [
    ("pwd", sys_cmds.cmd_pwd, "打印当前工作目录"),
    ("whoami", sys_cmds.cmd_whoami, "打印当前用户名"),
    ("cat", sys_cmds.cmd_cat, "打印文件内容"),
    ("grep", sys_cmds.cmd_grep, "过滤行"),
    ("mkdir", sys_cmds.cmd_mkdir, "创建目录"),
    ("touch", sys_cmds.cmd_touch, "创建空文件"),
    ("cp", sys_cmds.cmd_cp, "复制文件"),
    ("mv", sys_cmds.cmd_mv, "移动文件"),
    ("history", sys_cmds.cmd_history, "命令历史"),
    ("ps", proc_cmds.cmd_ps, "进程列表"),
    ("jobs", proc_cmds.cmd_jobs, "任务列表"),
    ("kill", proc_cmds.cmd_kill, "终止进程"),
    ("signal", proc_cmds.cmd_signal, "发信号"),
    ("sysmon", proc_cmds.cmd_sysmon, "系统总览"),
    ("spc_show", sys_cmds.cmd_spc_show, "SPC 打印"),
    ("spc_export", sys_cmds.cmd_spc_export, "SPC 导出"),
    ("spc_validate", sys_cmds.cmd_spc_validate, "SPC 校验"),
    ("spc_get", sys_cmds.cmd_spc_get, "SPC 读取"),
    ("spc_set", sys_cmds.cmd_spc_set, "SPC 写入"),
    ("spc_migrate", sys_cmds.cmd_spc_migrate, "SPC 迁移"),
]:
    cmd_registry.register(_n, _h)(_f)


# 命令映射表
COMMANDS = {
    'help': sys_cmds.cmd_help,
    'osver': sys_cmds.cmd_osver,
    'shutdown': sys_cmds.cmd_shutdown,
    'clear': sys_cmds.cmd_clear,
    'python': sys_cmds.cmd_python,
    'recovery': sys_cmds.cmd_recovery,
    'shb': sys_cmds.cmd_shb,
    'ls': sys_cmds.cmd_ls,
    'dir': sys_cmds.cmd_ls,
    'cd': lambda: sys_cmds.cmd_cd(),
    'pwd': sys_cmds.cmd_pwd,
    'whoami': sys_cmds.cmd_whoami,
    'mkdir': lambda: printk.error("用法: mkdir [-p] <目录>\n"),
    'touch': lambda: printk.error("用法: touch <文件>\n"),
    'cp': lambda: printk.error("用法: cp <源> <目标>\n"),
    'mv': lambda: printk.error("用法: mv <源> <目标>\n"),
    'cat': lambda: printk.error("用法: cat <文件>\n"),
    'grep': lambda: printk.error("用法: grep <pattern> [file]\n"),
    'history': sys_cmds.cmd_history,
    'ps': proc_cmds.cmd_ps,
    'jobs': proc_cmds.cmd_jobs,
    'kill': lambda: printk.error("用法: kill <pid>\n"),
    'signal': lambda: printk.error("用法: signal <pid> <信号>\n"),
    'sysmon': proc_cmds.cmd_sysmon,
    'spc_show': sys_cmds.cmd_spc_show,
    'spc_export': sys_cmds.cmd_spc_export,
    'spc_validate': lambda: printk.error("用法: spc_validate [path]\n"),
    'spc_get': lambda: printk.error("用法: spc_get <section.key> [path]\n"),
    'spc_set': lambda: printk.error("用法: spc_set <section.key> <value> [path]\n"),
    'spc_migrate': lambda: printk.error("用法: spc_migrate [json2spc|spc2json] [src] [dst]\n"),
    'rm': lambda: printk.error("用法: rm [-r] [-f] <文件或目录>\n"),
    'testroot': sys_cmds.cmd_testroot,
    'echo': lambda: print("用法: echo 指定的字符串\n"),
    'run': lambda: print("用法: run [-v] [-d] [-f] [--stats] [--map] [--disasm [N]] [--strace] [--engine auto|unicorn|native] <elf文件路径>\n"),
    'ota_check': ota_cmds.cmd_ota_check,
    'ota_update': ota_cmds.cmd_ota_update,
    'ota_status': ota_cmds.cmd_ota_status,
    'ota_rollback': ota_cmds.cmd_ota_rollback,
    'ota_clean': ota_cmds.cmd_ota_clean,
    'hotreset': sys_cmds.cmd_hotreset,
}

# 输出重定向：支持 `cmd > file`（覆盖）与 `cmd >> file`（追加）。
def _run_with_redirect(prompt: str) -> bool:
    import io
    import contextlib
    op = None
    if " >> " in prompt:
        op = " >> "
    elif " > " in prompt:
        op = " > "
    if not op:
        return False
    left, _, target = prompt.partition(op)
    left, target = left.strip(), target.strip()
    if not left or not target:
        return False
    if not main.is_safe_filename(target):
        printk.error("错误：文件名不允许包含 ../ 或绝对路径\n")
        return True
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            handle_command(left)
    except Exception as e:
        printk.error(f"重定向执行失败: {e}\n")
        return True
    mode = "a" if op == " >> " else "w"
    try:
        with open(target, mode, encoding="utf-8") as f:
            f.write(buf.getvalue())
        printk.ok(f"已重定向输出到: {target}\n")
    except Exception as e:
        printk.error(f"写入 {target} 失败: {e}\n")
    return True



# 单级管道：仅支持 `cat <file> | grep <pattern>` 形态（教学用最小实现）。
def _run_with_pipe(prompt: str) -> bool:
    if "|" not in prompt or "||" in prompt:
        return False
    left, _, right = prompt.partition("|")
    left, right = left.strip(), right.strip()
    if not left or not right:
        return False
    import io
    import contextlib
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            handle_command(left)
    except Exception as e:
        printk.error(f"管道左端执行失败: {e}\n")
        return True
    lines = buf.getvalue().splitlines()
    r_tokens = right.split()
    if r_tokens[0] == "grep" and len(r_tokens) >= 2:
        pattern = r_tokens[1]
        for line in lines:
            if pattern in line:
                print(line)
        print()
        return True
    printk.error(f"管道右端仅支持 grep <pattern>，got: {right}\n")
    return True



# 处理命令
def handle_command(prompt) -> str:
    prompt = (prompt or "").strip()
    if not prompt:
        return
    _cmd_history.append(prompt)
    if _run_with_redirect(prompt):
        return
    if _run_with_pipe(prompt):
        return
    # 注册表命令（含新增的 pwd/cat/ps 等无参形态）
    fn = cmd_registry.get(prompt)
    if fn is not None:
        try:
            fn()
        except TypeError:
            # 需要参数的命令（如 cat/cp）无参调用时走下方带参分支
            pass
        else:
            return
    if prompt in COMMANDS:
        COMMANDS[prompt]()
    elif prompt.startswith("echo "):
        sys_cmds.cmd_echo(prompt[5:].strip())
    elif prompt.startswith("open "):
        sys_cmds.cmd_open(prompt[5:].strip())
    elif prompt.startswith("openspf "):
        sys_cmds.cmd_openspf(prompt[8:].strip())
    elif prompt.startswith("finfo "):
        sys_cmds.cmd_finfo(prompt[6:].strip())
    elif prompt.startswith("run "):
        elf_cmd.cmd_run(prompt[4:].strip())
    elif prompt.startswith("cd "):
        sys_cmds.cmd_cd(prompt[3:].strip())
    elif prompt == "pwd":
        sys_cmds.cmd_pwd()
    elif prompt == "whoami":
        sys_cmds.cmd_whoami()
    elif prompt.startswith("cat "):
        sys_cmds.cmd_cat(prompt[4:].strip())
    elif prompt.startswith("grep "):
        sys_cmds.cmd_grep(prompt[5:].strip())
    elif prompt.startswith("mkdir "):
        sys_cmds.cmd_mkdir(prompt[6:].strip())
    elif prompt.startswith("touch "):
        sys_cmds.cmd_touch(prompt[6:].strip())
    elif prompt.startswith("cp "):
        sys_cmds.cmd_cp(prompt[3:].strip())
    elif prompt.startswith("mv "):
        sys_cmds.cmd_mv(prompt[3:].strip())
    elif prompt == "history":
        sys_cmds.cmd_history()
    elif prompt.startswith("ps"):
        proc_cmds.cmd_ps(prompt[2:].strip())
    elif prompt == "jobs":
        proc_cmds.cmd_jobs()
    elif prompt.startswith("kill "):
        proc_cmds.cmd_kill(prompt[5:].strip())
    elif prompt.startswith("signal "):
        proc_cmds.cmd_signal(prompt[7:].strip())
    elif prompt == "sysmon":
        proc_cmds.cmd_sysmon()
    elif prompt == "spc_show":
        sys_cmds.cmd_spc_show()
    elif prompt.startswith("spc_export"):
        sys_cmds.cmd_spc_export(prompt[len("spc_export"):].strip())
    elif prompt.startswith("spc_validate"):
        sys_cmds.cmd_spc_validate(prompt[len("spc_validate"):].strip())
    elif prompt.startswith("spc_get"):
        sys_cmds.cmd_spc_get(prompt[len("spc_get"):].strip())
    elif prompt.startswith("spc_set"):
        sys_cmds.cmd_spc_set(prompt[len("spc_set"):].strip())
    elif prompt.startswith("spc_migrate"):
        sys_cmds.cmd_spc_migrate(prompt[len("spc_migrate"):].strip())
    elif prompt.startswith("rm "):
        # 解析 rm 命令参数
        args = prompt[3:].strip()
        import shlex
        try:
            tokens = shlex.split(args) if args else []
        except ValueError:
            tokens = args.split() if args else []
        
        recursive = False
        force = False
        target = None
        
        i = 0
        while i < len(tokens):
            token = tokens[i]
            if token == '-r' or token == '-R' or token == '--recursive':
                recursive = True
                i += 1
            elif token == '-f' or token == '--force':
                force = True
                i += 1
            elif token == '-rf' or token == '-fr':
                recursive = True
                force = True
                i += 1
            elif token.startswith('-'):
                printk.error(f"rm: 未知选项: {token}\n")
                return
            else:
                if target is None:
                    target = token
                    i += 1
                else:
                    # 多个目标，处理完第一个后提示
                    break
        
        if target:
            sys_cmds.cmd_rm(target, recursive, force)
        else:
            printk.error("rm: 缺少操作数\n")
    else:
        print(f"'{prompt}' 不是内部或外部命令，也不是可运行的程序或批处理文件。\n")
