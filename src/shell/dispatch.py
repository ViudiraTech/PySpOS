'''
 *
 *      dispatch.py
 *      Command dispatch: registry lookup, tab completion and background jobs.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import os

import commands as cmd_registry
import printk
import main

from . import sys_cmds, elf_cmd, ota_cmds, proc_cmds, pkg_cmds
from . import filter_cmds, hostexec, shexec

# command history, used by the history command and by readline persistence
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

    # Flush the readline history file at exit, ignoring a read-only home.
    def _save_history():
        try:
            _readline.write_history_file(_hist_file)
        except OSError:
            pass

    _atexit.register(_save_history)
except ImportError:
    _readline = None


# --------------------------------------------------------------------------
# tab completion, a simplified bash programmable completion whose data source is the registry plus PATH
# --------------------------------------------------------------------------

# Readline completer: complete command names on the first word, paths on the rest.
def _complete(text, state):
    try:
        line = _readline.get_line_buffer() if _readline else ""
        line_buffer = _readline.get_line_buffer()[:_readline.get_endidx()] if _readline else line
    except Exception:
        line_buffer = line if isinstance(line, str) else ""
    parts = line_buffer.split()
    completing_first = len(parts) <= 1

    if completing_first:
        cmd_registry.register_discovered()
        seen = set()
        matches = []
        for cand in list(cmd_registry.names_for_completion()) + hostexec.path_commands():
            if cand.startswith(text) and cand not in seen:
                seen.add(cand)
                matches.append(cand)
        matches.sort(key=lambda n: (0 if n.startswith(text) else 1, n))
    else:
        matches = _path_matches(text)
    if state < len(matches):
        return matches[state]
    return None


# List path completions for a partial word, marking directories with a trailing slash.
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


# Install the readline completer and key bindings; False when readline is absent.
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
# the command registry, carrying group and summary metadata
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
    ("grep", sys_cmds.cmd_grep, "过滤文本", "grep [-ivncq] <模式> [文件]", "file", [], True),
    # text
    ("wc", filter_cmds.cmd_wc, "统计行/词/字节", "wc [-lwc] [文件...]", "text", [], True),
    ("head", filter_cmds.cmd_head, "取前 N 行", "head [-n 行数] [文件]", "text", [], True),
    ("tail", filter_cmds.cmd_tail, "取后 N 行", "tail [-n 行数] [文件]", "text", [], True),
    ("sort", filter_cmds.cmd_sort, "排序", "sort [-r] [-n] [-u] [文件]", "text", [], True),
    ("uniq", filter_cmds.cmd_uniq, "相邻去重", "uniq [-c] [文件]", "text", [], True),
    ("tr", filter_cmds.cmd_tr, "字符替换/删除", "tr [-d] 字符集1 [字符集2]", "text", [], True),
    ("cut", filter_cmds.cmd_cut, "按列切分", "cut -d 分隔符 -f 字段 [文件]", "text", [], True),
    ("rev", filter_cmds.cmd_rev, "每行反转", "rev [文件]", "text", [], True),
    ("tac", filter_cmds.cmd_tac, "倒序输出行", "tac [文件]", "text", [], True),
    ("nl", filter_cmds.cmd_nl, "行号", "nl [文件]", "text", [], True),
    ("seq", filter_cmds.cmd_seq, "生成数列", "seq 起点 [步长] 终点", "text", [], True),
    ("tee", filter_cmds.cmd_tee, "管道分流落盘", "tee [-a] 文件...", "text", [], True),
    ("sed", filter_cmds.cmd_sed, "流替换（s///）", "sed 's/查找/替换/[g]' [文件]", "text", [], True),
    ("date", filter_cmds.cmd_date, "当前时间", "date [+格式]", "text", [], False),
    ("test", filter_cmds.cmd_test, "条件判断（供 &&/||）", "test 表达式", "text", [], True),
    ("[", filter_cmds.cmd_lbracket, "条件判断（[ 表达式 ]）", "[ 表达式 ]", "text", [], True),
    ("true", filter_cmds.cmd_true, "恒真（供 &&/||）", "true", "text", [], False),
    ("false", filter_cmds.cmd_false, "恒假（供 &&/||）", "false", "text", [], False),
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
     "run [--stats] [--map] [--strace] [--disasm [N]] [--engine auto|unicorn|native] <elf>", "run", [], True),
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

# legacy compatibility: a usage table for calls without arguments; the kernel still exposes COMMANDS
COMMANDS = {}
for _name, _fn, _summary, _usage, _group, _aliases, _arg in _REG:
    if _arg:
        COMMANDS[_name] = (lambda u=_usage: printk.error(f"用法: {u}\n"))
    else:
        COMMANDS[_name] = _fn
    for _a in _aliases:
        COMMANDS[_a] = COMMANDS[_name]


# --------------------------------------------------------------------------
# external commands, with apps/ acting as PATH
# --------------------------------------------------------------------------

# Run an apps/ command as a real child, waiting or registering a background job.
def _fork_external(name: str, args: str, background: bool):
    import forkexec
    rel = name + ".py"
    if background:
        log_path = os.path.join("/tmp", f"pyspos_bg_{name}_{os.getpid()}.log")
    pcb = forkexec.fork_exec(
        f"app:{rel}", kind="app", background=background,
        src_dir=main.script_dir,
        env={"PYSPOS_APP_ARGS": args, "PYSPOS_COMMAND_ARGS": args},
        log_path=(log_path if background else None))
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


# Run an installed package entry point, reporting a launch failure itself.
def _fork_package(target: dict, args: str, background: bool):
    try:
        return pkg_cmds.run_entrypoint(target, args, background=background)
    except Exception as exc:
        printk.error(f"运行包命令 {target.get('name', '')} 失败: {exc}\n")
        return None


# --------------------------------------------------------------------------
# main dispatch
# --------------------------------------------------------------------------

# Call a builtin according to its signature and return its exit code.
# Only an exact int counts as a status. A TypeError is deliberately not used to detect a
# missing argument, because that would report a real bug inside the command as a usage error.
def _invoke_builtin(meta, args: str):
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
        ret = fn()
        return ret if type(ret) is int else 0
    if required:
        if not args:
            printk.error(f"用法: {meta.usage or meta.name}\n")
            return 1
        ret = fn(args)
        return ret if type(ret) is int else 0
    ret = fn(args) if args else fn()
    return ret if type(ret) is int else 0


# Record the line in the history and run it; an empty line is ignored.
# It is called for what it does, not for a result: every path returns None.
def handle_command(prompt) -> None:
    prompt = (prompt or "").strip()
    if not prompt:
        return
    _cmd_history.append(prompt)
    shexec.run_line(prompt)
