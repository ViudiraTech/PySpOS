#
#   shell/dispatch.py
#   命令分发：注册表解析（builtin → PATH 外部命令）+ 重定向/管道 + 后台作业。
#
#   解析顺序（对齐 bash）：
#     含 '/' 的路径 → 外部/脚本
#     注册表 alias  → 注册表 builtin
#     apps/ 外部命令 → forkexec 真子进程
#     其余          → 127 command not found
#
#   后台/并发：`cmd &` 立即返回并注册后台作业，$! 取最近后台 PID；
#   jobs/fg/bg/wait 走 process.py 的作业表 + 僵尸回收。
#

import contextlib
import io
import os
import shlex

import commands as cmd_registry
import printk
import main

from . import sys_cmds, elf_cmd, ota_cmds, proc_cmds

# 命令历史（history 命令 + readline 持久化）
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


# --------------------------------------------------------------------------
# Tab 补全（bash programmable completion 的简化版，数据源=注册表+PATH）
# --------------------------------------------------------------------------

def _complete(text, state):
    """readline completer：命令行第一个词补命令名，其余词补路径。"""
    try:
        line = _readline.get_line_buffer() if _readline else ""
        line_buffer = _readline.get_line_buffer()[:_readline.get_endidx()] if _readline else line
    except Exception:
        line_buffer = line if isinstance(line, str) else ""
    parts = line_buffer.split()
    completing_first = len(parts) <= 1

    if completing_first:
        cmd_registry.register_discovered()
        matches = [c for c in cmd_registry.names_for_completion()
                   if c.startswith(text)]
        matches.sort(key=lambda n: (0 if n.startswith(text) else 1, n))
    else:
        matches = _path_matches(text)
    if state < len(matches):
        return matches[state]
    return None


def _path_matches(text):
    import glob as _glob
    d, _, base = text.rpartition("/")
    search_dir = d or "."
    try:
        entries = _glob.glob(search_dir + "/" + base + "*")
    except Exception:
        entries = []
    out = []
    for e in sorted(entries):
        out.append(e + "/" if os.path.isdir(e) else e)
    return out


def _install_completer():
    if _readline is None:
        return False
    try:
        _readline.set_completer(_complete)
        _readline.set_completer_delims(" \t\n")
        _readline.parse_and_bind("tab: complete")
        _readline.parse_and_bind("^I: complete")
        return True
    except Exception:
        return False


_completion_enabled = _install_completer()


# --------------------------------------------------------------------------
# 注册表（带分组/摘要元数据）
# --------------------------------------------------------------------------
_REG = [
    # system
    ("help", sys_cmds.cmd_help, "显示帮助（help <命令> 看详情）", "help [命令]", "system", [], True),
    ("clear", sys_cmds.cmd_clear, "清屏", "clear", "system", [], False),
    ("echo", sys_cmds.cmd_echo, "打印字符串（支持 > 与 >>）", "echo <文本> [> 文件]", "system", [], True),
    ("osver", sys_cmds.cmd_osver, "查看系统与 Python 版本", "osver", "system", [], False),
    ("whoami", sys_cmds.cmd_whoami, "打印当前用户", "whoami", "system", [], False),
    ("pwd", sys_cmds.cmd_pwd, "打印当前目录", "pwd", "file", [], False),
    ("shb", sys_cmds.cmd_shb, "彩蛋命令", "shb", "system", [], False),
    ("python", sys_cmds.cmd_python, "进入 Python 解释器", "python", "system", [], False),
    ("shutdown", sys_cmds.cmd_shutdown, "关闭 PySpOS", "shutdown", "system", [], False),
    ("history", sys_cmds.cmd_history, "查看命令历史", "history", "system", [], False),
    ("sysmon", proc_cmds.cmd_sysmon, "系统总览（版本/槽位/进程/OTA）", "sysmon", "system", [], False),
    # file
    ("ls", sys_cmds.cmd_ls, "列出目录内容", "ls", "file", ["dir"], False),
    ("cd", sys_cmds.cmd_cd, "切换目录", "cd [路径]", "file", [], True),
    ("cat", sys_cmds.cmd_cat, "打印文件", "cat <文件>", "file", [], True),
    ("grep", sys_cmds.cmd_grep, "过滤文本", "grep <模式> [文件]", "file", [], True),
    ("mkdir", sys_cmds.cmd_mkdir, "创建目录", "mkdir [-p] <目录>", "file", [], True),
    ("touch", sys_cmds.cmd_touch, "创建空文件", "touch <文件>", "file", [], True),
    ("cp", sys_cmds.cmd_cp, "复制文件", "cp <源> <目标>", "file", [], True),
    ("mv", sys_cmds.cmd_mv, "移动文件", "mv <源> <目标>", "file", [], True),
    ("rm", sys_cmds.cmd_rm, "删除文件或目录", "rm [-r] [-f] <目标>", "file", [], True),
    ("finfo", sys_cmds.cmd_finfo, "查看文件信息", "finfo <文件>", "file", [], True),
    # process
    ("ps", proc_cmds.cmd_ps, "列出进程", "ps [-a]", "process", [], True),
    ("jobs", proc_cmds.cmd_jobs, "列出后台作业", "jobs", "process", [], False),
    ("fg", proc_cmds.cmd_fg, "前台恢复作业", "fg %作业号", "process", [], True),
    ("bg", proc_cmds.cmd_bg, "后台继续作业", "bg %作业号", "process", [], True),
    ("wait", proc_cmds.cmd_wait, "等待作业结束", "wait [%作业号]", "process", [], True),
    ("kill", proc_cmds.cmd_kill, "终止进程", "kill <pid>", "process", [], True),
    ("signal", proc_cmds.cmd_signal, "向进程发信号", "signal <pid> <信号名>", "process", [], True),
    # run
    ("open", sys_cmds.cmd_open, "以 fork 子进程运行 app", "open <app名>", "run", [], True),
    ("openspf", sys_cmds.cmd_openspf, "运行 SPF 脚本", "openspf <脚本名>", "run", [], True),
    ("run", elf_cmd.cmd_run, "运行 ELF（unicorn/native）",
     "run [--stats] [--map] [--strace] <elf>", "run", [], True),
    ("hotreset", sys_cmds.cmd_hotreset, "热重启系统", "hotreset", "run", [], False),
    ("recovery", sys_cmds.cmd_recovery, "进入恢复模式", "recovery", "ota", [], False),
    # config
    ("spc_show", sys_cmds.cmd_spc_show, "打印 SpaceConfig", "spc_show", "config", [], False),
    ("spc_export", sys_cmds.cmd_spc_export, "导出 bootcfg 为 .spc", "spc_export [路径]", "config", [], True),
    ("spc_validate", sys_cmds.cmd_spc_validate, "校验 .spc 文件", "spc_validate [路径]", "config", [], True),
    ("spc_get", sys_cmds.cmd_spc_get, "读取配置项", "spc_get <节.键> [路径]", "config", [], True),
    ("spc_set", sys_cmds.cmd_spc_set, "写入配置项", "spc_set <节.键> <值> [路径]", "config", [], True),
    ("spc_migrate", sys_cmds.cmd_spc_migrate, "json/spc 双向迁移", "spc_migrate [json2spc|spc2json] [源] [目标]", "config", [], True),
    ("locale", sys_cmds.cmd_locale, "语言/时区/显示名", "locale [lang <码>|tz <时区>|user <名>]", "config", [], True),
    # ota
    ("ota_check", ota_cmds.cmd_ota_check, "检查云端更新", "ota_check", "ota", [], False),
    ("ota_update", ota_cmds.cmd_ota_update, "下载并安装更新", "ota_update", "ota", [], False),
    ("ota_status", ota_cmds.cmd_ota_status, "查看 OTA 状态", "ota_status", "ota", [], False),
    ("ota_rollback", ota_cmds.cmd_ota_rollback, "回滚到上一版本", "ota_rollback", "ota", [], False),
    ("ota_clean", ota_cmds.cmd_ota_clean, "清理更新包", "ota_clean", "ota", [], False),
    # setup
    ("oobe", sys_cmds.cmd_oobe, "重跑首次开机向导", "oobe", "setup", [], False),
    ("testroot", sys_cmds.cmd_testroot, "查看 ROOT 状态", "testroot", "setup", [], False),
    ("bootloader_status", sys_cmds.cmd_bootloader_status, "查看 Bootloader 验签/信任状态（需 ROOT）", "bootloader_status", "setup", ["bl_status"], False),
]

for _name, _fn, _summary, _usage, _group, _aliases, _arg in _REG:
    cmd_registry.register(_name, _fn, summary=_summary, usage=_usage,
                          group=_group, aliases=_aliases, takes_arg=_arg)

# 历史兼容：无参调用时的用法提示表（内核仍对外暴露 COMMANDS）
COMMANDS = {}
for _name, _fn, _summary, _usage, _group, _aliases, _arg in _REG:
    if _arg:
        COMMANDS[_name] = (lambda u=_usage: printk.error(f"用法: {u}\n"))
    else:
        COMMANDS[_name] = _fn
    for _a in _aliases:
        COMMANDS[_a] = COMMANDS[_name]


# --------------------------------------------------------------------------
# 外部命令（apps/ 作为 PATH）
# --------------------------------------------------------------------------

def _fork_external(name: str, args: str, background: bool):
    import forkexec
    rel = name + ".py"
    if background:
        log_path = os.path.join("/tmp", f"pyspos_bg_{name}_{os.getpid()}.log")
    pcb = forkexec.fork_exec(f"app:{rel}", kind="app", background=background,
                              src_dir=main.script_dir, log_path=(
                                  log_path if background else None))
    if background:
        import process
        job = process.new_job(f"{name} {args}".strip(), pids=[pcb.pid])
        process._table().mark_last_bg(pcb.pid)
        printk.ok(f"[{job.job_id}] {pcb.pid}  {name} {args}\n")
    else:
        forkexec.wait(pcb.pid, timeout=None)
        import process
        process.reap_children(pcb.ppid)
    return pcb


# --------------------------------------------------------------------------
# 重定向 / 管道
# --------------------------------------------------------------------------

def _run_with_redirect(prompt: str) -> bool:
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


def _run_with_pipe(prompt: str) -> bool:
    if "|" not in prompt or "||" in prompt:
        return False
    left, _, right = prompt.partition("|")
    left, right = left.strip(), right.strip()
    if not left or not right:
        return False
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            handle_command(left)
    except Exception as e:
        printk.error(f"管道左端执行失败: {e}\n")
        return True
    r_tokens = right.split()
    if r_tokens[0] == "grep" and len(r_tokens) >= 2:
        pattern = r_tokens[1]
        for line in buf.getvalue().splitlines():
            if pattern in line:
                print(line)
        print()
        return True
    printk.error(f"管道右端仅支持 grep <pattern>，got: {right}\n")
    return True


# --------------------------------------------------------------------------
# 主分发
# --------------------------------------------------------------------------

def _invoke_builtin(meta, args: str):
    """按签名决定是否传参。

    不用 try/except TypeError 判断——那会把命令内部真正的 TypeError
    误报成“缺参数”，掩盖真实 bug。
    """
    import inspect
    fn = meta.fn
    try:
        sig = inspect.signature(fn)
        required = [p for p in sig.parameters.values()
                    if p.default is inspect.Parameter.empty
                    and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
        accepts_one = len(sig.parameters) >= 1
    except (TypeError, ValueError):
        required, accepts_one = [], False
    if not accepts_one:
        fn()
        return
    if required:
        if not args:
            printk.error(f"用法: {meta.usage or meta.name}\n")
            return
        fn(args)
        return
    if args:
        fn(args)
    else:
        fn()


def handle_command(prompt) -> str:
    prompt = (prompt or "").strip()
    if not prompt:
        return
    _cmd_history.append(prompt)

    if _run_with_redirect(prompt):
        return
    if _run_with_pipe(prompt):
        return

    # 后台符号：cmd &
    background = False
    if prompt.endswith("&") and not prompt.endswith("&&"):
        prompt = prompt[:-1].strip()
        background = True
        if not prompt:
            return

    try:
        tokens = shlex.split(prompt)
    except ValueError:
        tokens = prompt.split()
    if not tokens:
        return
    name, args = tokens[0], " ".join(tokens[1:])

    # help 支持带参数
    real = cmd_registry._ALIASES.get(name, name)

    # 1) builtin
    meta = cmd_registry.get_meta(real)
    if meta is not None and meta.fn is not None:
        _invoke_builtin(meta, args)
        return

    # 2) 外部命令（apps/）
    if cmd_registry.resolve_external(real):
        try:
            _fork_external(real, args, background)
        except Exception as e:
            printk.error(f"运行 {name} 失败: {e}\n")
        return

    # 3) 未知
    print(f"{name}: 未找到命令（输入 help 查看可用命令）\n")
