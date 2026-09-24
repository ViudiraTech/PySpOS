#
#   shell/sys_cmds.py
#   系统/文件类 shell 命令（由 main.py 拆分而来，行为保持不变）。
#   跨模块共享状态一律经 main.* 读取（main.py facade 保证先初始化）。
#

import os
import platform
import printk
import fs
import kernel
import recovery
import process as proc  # 进程管理以 process.py（PCB + EEVDF）为准，proc.py 仅为兼容垫片
import spc
import pyspos
import main

if pyspos.SPF_ENABLED:
    import parse_spf
else:
    class parse_spf:
        @staticmethod
        def run_spf(spf_path):
            raise NotImplementedError("SPF support is disabled in this build. spf path: " + spf_path)


def print_sunhb():
    cores = kernel.cores
    print(f"'shb'程序将打印孙浩博是小可爱！{cores}次。\n")
    print("孙浩博是 " * cores)
    print("小可爱！ " * cores)
    print()

# 命令处理函数
def cmd_help():
    print("clear      清屏")
    print("echo       打印指定的字符串（支持 echo text > file / >> file）")
    print("osver      查看系统和Python版本")
    print("shutdown   关闭PySpOS")
    print("python     启动Python")
    print("shb        打印孙浩博是小可爱 n 次（n 指你的CPU逻辑核心数）")
    print("ls/dir     列出当前目录下的文件和文件夹")
    print("cd         切换工作目录")
    print("pwd        打印当前工作目录")
    print("whoami     打印当前用户名")
    print("cat        打印文件内容（支持 cat a | grep foo）")
    print("grep       过滤行（用法: grep <pattern> [file]）")
    print("mkdir      创建目录（mkdir -p a/b）")
    print("touch      创建空文件")
    print("cp/mv      复制/移动文件")
    print("rm         删除文件或文件夹")
    print("finfo      查看指定文件的信息")
    print("testroot   测试ROOT权限")
    print("open       运行 apps 目录下的指定应用程序")
    print("openspf    运行 spfapps 目录下的 SPF 脚本（SPF 2.0: var/set/add/input/include/sleep）")
    print("run        加载并运行 ELF 可执行文件（run --stats/--map/--disasm/--strace）")
    print("ps/jobs    列出模拟进程")
    print("kill       终止模拟进程（kill <pid>）")
    print("signal     向进程发信号（signal <pid> <SIGTERM|SIGKILL|SIGSTOP|SIGCONT|SIGUSR1>）")
    print("history    查看命令历史")
    print("sysmon     一屏总览（版本/槽位/进程/OTA）")
    print("spc_show   以 SpaceConfig 格式打印当前 bootcfg")
    print("spc_export 导出 bootcfg 为 .spc 文件（spc_export [path]）")
    print("spc_validate 校验 spc 文件（语法+Schema，带行号）")
    print("spc_get    读取配置项（spc_get <section.key> [path]）")
    print("spc_set    写入配置项（spc_set <section.key> <value> [path]）")
    print("spc_migrate json/spc 双向迁移（带校验）")
    print("ota_check  检查是否有可用的更新（OTA 维护期间会直接提示禁用）")
    print("ota_update 下载并安装更新")
    print("ota_status 查看OTA更新状态")
    print("ota_rollback 回滚到上一个版本")
    print("ota_clean  清理更新包文件")
    print("hotreset   热重启系统（重新加载代码）\n")

# 打印指定字符串
def cmd_echo(text: str):
    print(f"{text}\n")

# 显示PySpOS版本
def cmd_osver():
    print(f"PySpOS 版本: {pyspos.OS_VERSION}, 开发阶段: {pyspos.OS_DEVELOP_STAGE}")
    print(f"Python 版本: {platform.python_version()}\n")

def cmd_shutdown():
    kernel.exit()

def cmd_clear():
    if os.name == "nt":
        os.system("cls")
    else:
        os.system("clear")

def cmd_python():
    os.system("python")
    print()

def cmd_recovery():
    recovery.recovery_main("kernel_jump")

def cmd_shb():
    print_sunhb()
    char = '你'
    print(f"字符：{char}")
    print(f"十六进制编码：U+{ord(char):04X}")  # 输出 U+AFAF
    print(f"十进制编码：{ord(char)}")          # 输出 44975

    # 2. 反向：从编码找字符
    code = ord(char)
    print(f"编码0x{code:04X}对应的字符：{chr(code)}")  # 输出 你

def cmd_ls():
    items = fs.list_dir()
    for item in items:
        print(item)
    print()

def cmd_cd(path: str = None):
    #切换工作目录
    if path is None or path.strip() == "":
        # 如果没有参数，切换到用户主目录
        path = os.path.expanduser("~")
    
    # 处理特殊路径
    if path == "-":
        # 切换到上一个目录
        path = os.environ.get("OLDPWD", os.getcwd())
    elif path == "~":
        path = os.path.expanduser("~")
    
    # 保存当前目录
    old_cwd = os.getcwd()
    
    try:
        # 尝试切换目录
        os.chdir(path)
        # 更新 OLDPWD 环境变量
        os.environ["OLDPWD"] = old_cwd
        # 打印当前目录
        print(os.getcwd())
    except FileNotFoundError:
        printk.error(f"cd: 没有那个文件或目录: {path}\n")
    except NotADirectoryError:
        printk.error(f"cd: 不是目录: {path}\n")
    except PermissionError:
        printk.error(f"cd: 权限拒绝: {path}\n")
    except Exception as e:
        printk.error(f"cd: 错误: {e}\n")

def cmd_finfo(filename: str):
    info = fs.get_file_info(filename) # 获取文件信息
    if info:    
        print(f"{filename} 的文件信息\n大小: {info['size']} 字节, 修改时间: {info['modified']}, 是否为目录: {info['is_dir']}\n")
    else:
        print(f"未找到文件或目录: {filename}\n")

# 删除文件或文件夹
def cmd_rm(target: str, recursive: bool = False, force: bool = False):
    if not target or target.strip() == "":
        printk.error("rm: 缺少操作数\n")
        return
    
    target = target.strip()
    
    # 安全检查
    if not main.is_safe_filename(target):
        printk.error("错误：文件名不允许包含 ../ 或绝对路径\n")
        return
    
    # 获取完整路径
    full_path = os.path.abspath(target)
    
    # 检查文件/文件夹是否存在
    if not os.path.exists(full_path):
        printk.error(f"rm: 无法删除 '{target}': 没有那个文件或目录\n")
        return
    
    try:
        # 判断是文件还是目录
        if os.path.isfile(full_path):
            # 删除文件
            if not force:
                if not printk.confirm(f"确认删除文件 '{target}'?"):
                    print("操作已取消\n")
                    return
            os.remove(full_path)
            printk.ok(f"已删除文件: {target}\n")
            
        elif os.path.isdir(full_path):
            # 删除目录
            if not recursive:
                printk.error(f"rm: 无法删除 '{target}': 是一个目录\n")
                print("提示: 使用 'rm -r <目录>' 递归删除目录及其内容\n")
                return
            
            if not force:
                if not printk.confirm(f"确认递归删除目录 '{target}' 及其所有内容?"):
                    print("操作已取消\n")
                    return
            
            import shutil
            shutil.rmtree(full_path)
            printk.ok(f"已删除目录: {target}\n")
            
    except PermissionError:
        printk.error(f"rm: 无法删除 '{target}': 权限拒绝\n")
    except Exception as e:
        printk.error(f"rm: 无法删除 '{target}': {str(e)}\n")

def cmd_testroot():
    if main.rootstate:
        print("当前处于 ROOT 权限状态。")
        print(f"rootstate 变量值为: {main.rootstate}\n")
    else:
        print("当前未处于 ROOT 权限状态。")
        print(f"rootstate 变量值为: {main.rootstate}\n")

def cmd_open(app_name: str):
    if not app_name.endswith(".py"):
        app_name += ".py"

    if not main.is_safe_filename(app_name):
        printk.error("错误：文件名不允许包含 ../ 或绝对路径\n")
        return

    app_path = main.get_app_path(app_name)

    if not os.path.exists(app_path) or not os.path.isfile(app_path):
        printk.error(f"未找到可执行文件: {app_name}\n")
        return

    pcb = proc.spawn(f"open {app_name}", kind="app")
    try:
        with open(app_path, 'r', encoding='utf-8') as f:
            code = f.read()

        # 2026-09-24 修复：此前这里只放行了十几个 builtins，导致 apps 里
        # 正常的 open()/input()/FileNotFoundError/json/os 等全部 NameError
        #（如 open gettoken 直接崩）。apps 与 shell 同属本地可信代码，
        # 历史上的“受限 builtins”并未提供真正的隔离（__import__ 本就放行），
        # 现改为完整 builtins + 独立命名空间，保证 apps 正常运行。
        exec_namespace = {
            '__name__': '__exec__',
            '__builtins__': __builtins__,
        }

        exec(code, exec_namespace)
        proc.finish(pcb.pid, 0)

    except Exception as e:
        proc.finish(pcb.pid, 1, failed=True)
        printk.error(f"执行 {app_name} 失败: {str(e)}\n")

def cmd_openspf(app_name: str):
    if not app_name.endswith(".spf"):
        app_name += ".spf"

    if not main.is_safe_filename(app_name):
        printk.error("错误：文件名不允许包含 ../ 或绝对路径\n")
        return

    app_path = main.get_spf_path(app_name)

    if not os.path.exists(app_path) or not os.path.isfile(app_path):
        printk.error(f"未找到可执行文件: {app_name}\n")
        return

    pcb = proc.spawn(f"openspf {app_name}", kind="spf")
    try:
        parse_spf.run_spf(app_path)
        proc.finish(pcb.pid, 0)
    except Exception as e:
        proc.finish(pcb.pid, 1, failed=True)
        printk.error(f"执行 {app_name} 失败: {str(e)}\n")


def cmd_pwd():
    print(os.getcwd() + "\n")


def cmd_whoami():
    try:
        print(kernel.get_system_username() + "\n")
    except Exception as e:
        printk.error(f"whoami: {e}\n")


def cmd_cat(args: str):
    import shlex
    try:
        tokens = shlex.split(args) if args else []
    except ValueError:
        tokens = args.split() if args else []
    if not tokens:
        printk.error("用法: cat <文件>\n")
        return
    for name in tokens:
        if not main.is_safe_filename(name):
            printk.error("错误：文件名不允许包含 ../ 或绝对路径\n")
            continue
        text = fs.cat_file(name)
        if text is None:
            printk.error(f"cat: 未找到文件: {name}\n")
        else:
            print(text, end='' if text.endswith('\n') else '\n')
    print()


def cmd_grep(args: str):
    import shlex
    try:
        tokens = shlex.split(args) if args else []
    except ValueError:
        tokens = args.split() if args else []
    if not tokens:
        printk.error("用法: grep <pattern> [file]\n")
        return
    pattern = tokens[0]
    if len(tokens) > 1:
        for name in tokens[1:]:
            text = fs.cat_file(name)
            if text is None:
                printk.error(f"grep: 未找到文件: {name}\n")
                continue
            for line in text.splitlines():
                if pattern in line:
                    print(line)
    else:
        # 无文件时从 stdin 读（主要服务于管道）
        import sys as _sys
        data = _sys.stdin.read() if not _sys.stdin.isatty() else ""
        for line in data.splitlines():
            if pattern in line:
                print(line)
    print()


def cmd_mkdir(args: str):
    import shlex
    try:
        tokens = shlex.split(args) if args else []
    except ValueError:
        tokens = args.split() if args else []
    names = [t for t in tokens if t != "-p"]
    if not names:
        printk.error("用法: mkdir [-p] <目录>\n")
        return
    for name in names:
        if not main.is_safe_filename(name):
            printk.error("错误：文件名不允许包含 ../ 或绝对路径\n")
            continue
        try:
            fs.mkdir_p(name)
            printk.ok(f"已创建目录: {name}")
        except Exception as e:
            printk.error(f"mkdir: {e}\n")


def cmd_touch(args: str):
    name = (args or "").strip()
    if not name:
        printk.error("用法: touch <文件>\n")
        return
    if not main.is_safe_filename(name):
        printk.error("错误：文件名不允许包含 ../ 或绝对路径\n")
        return
    try:
        fs.touch(name)
        printk.ok(f"已创建文件: {name}")
    except Exception as e:
        printk.error(f"touch: {e}\n")


def _copy_move(args: str, op: str):
    import shlex
    import shutil
    try:
        tokens = shlex.split(args) if args else []
    except ValueError:
        tokens = args.split() if args else []
    if len(tokens) != 2:
        printk.error(f"用法: {op} <源> <目标>\n")
        return
    src, dst = tokens
    for p in (src, dst):
        if not main.is_safe_filename(p):
            printk.error("错误：文件名不允许包含 ../ 或绝对路径\n")
            return
    try:
        if op == "cp":
            if os.path.isdir(src):
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
        else:
            shutil.move(src, dst)
        printk.ok(f"{op}: {src} -> {dst}")
    except Exception as e:
        printk.error(f"{op}: {e}\n")


def cmd_cp(args: str):
    _copy_move(args, "cp")


def cmd_mv(args: str):
    _copy_move(args, "mv")


def cmd_history():
    for i, c in enumerate(main._cmd_history, 1):
        print(f"{i:4d}  {c}")
    print()



def cmd_spc_show():
    try:
        data = spc.bootcfg_to_spc(main.bootcfg)
        print(spc.dumps(data))
    except Exception as e:
        printk.error(f"spc_show: {e}\n")


def cmd_spc_export(args: str):
    path = (args or "").strip() or os.path.join("etc", "bootcfg.spc")
    try:
        spc.dump(spc.bootcfg_to_spc(main.bootcfg), path)
        printk.ok(f"已导出 SpaceConfig: {path}\n")
    except Exception as e:
        printk.error(f"spc_export: {e}\n")


def _default_spc_path() -> str:
    return os.path.join(main.root_dir, "etc", "bootcfg.spc")


def cmd_spc_validate(args: str):
    """用法: spc_validate [path] —— 语法解析 + BOOTCFG_SCHEMA 校验，带行号。"""
    path = (args or "").strip() or _default_spc_path()
    if not os.path.isfile(path):
        printk.error(f"spc_validate: 找不到文件: {path}（可先用 spc_migrate 生成）\n")
        return
    try:
        data, meta = spc.load(path, with_meta=True)
    except SyntaxError as e:
        printk.error(f"spc_validate: 语法错误: {e}\n")
        return
    except OSError as e:
        printk.error(f"spc_validate: 读取失败: {e}\n")
        return
    issues = spc.validate(data, spc.BOOTCFG_SCHEMA, meta)
    errs = [i for i in issues if i.level == "error"]
    warns = [i for i in issues if i.level == "warning"]
    for i in issues:
        tag = printk.RED_COLOR if i.level == "error" else printk.YELLOW_COLOR
        loc = f"@{i.lineno}" if i.lineno else ""
        print(f"{tag}[{i.level}]{printk.RESET_COLOR} [{i.section}.{i.key}{loc}] {i.message}")
    if not issues:
        printk.ok(f"{path}: 校验通过，无问题\n")
    else:
        print(f"校验完成：{len(errs)} 个错误，{len(warns)} 个警告\n")


def cmd_spc_get(args: str):
    """用法: spc_get <section.key> [path] —— 无 path 时读默认 spc，缺文件则回退实时 bootcfg。"""
    import shlex
    try:
        tokens = shlex.split(args) if args else []
    except ValueError:
        tokens = (args or "").split()
    if not tokens:
        printk.error("用法: spc_get <section.key> [path]\n")
        return
    dotted = tokens[0]
    path = tokens[1] if len(tokens) > 1 else _default_spc_path()
    if "." not in dotted:
        printk.error("用法: spc_get <section.key> [path]\n")
        return
    sec, key = dotted.split(".", 1)
    if os.path.isfile(path):
        try:
            data = spc.load(path)
        except Exception as e:
            printk.error(f"spc_get: 解析 {path} 失败: {e}\n")
            return
        src = path
    else:
        if len(tokens) > 1:
            printk.error(f"spc_get: 找不到文件: {path}\n")
            return
        data = spc.bootcfg_to_spc(main.bootcfg)
        src = "实时 bootcfg（默认 spc 文件不存在，已回退）"
    if sec not in data or key not in data[sec]:
        printk.error(f"spc_get: {sec}.{key} 不存在（来源：{src}）\n")
        return
    print(f"{sec}.{key} = {spc.format_value(data[sec][key])}  # 来源：{src}\n")


def cmd_spc_set(args: str):
    """用法: spc_set <section.key> <value> [path] —— value 按 spc 语法解析后写回文件。
    value 含空格可直接写（spc_set nums.list [1, 2]）；末 token 仅在“已存在文件、
    或像路径（.spc 后缀/含 /）”时才被当作 path，否则并入 value 用默认路径。"""
    import shlex
    try:
        tokens = shlex.split(args) if args else []
    except ValueError:
        tokens = (args or "").split()
    if len(tokens) < 2:
        printk.error("用法: spc_set <section.key> <value> [path]\n")
        return
    dotted = tokens[0]
    last = tokens[-1]
    if len(tokens) > 2 and (os.path.isfile(last) or last.endswith(".spc")
                            or "/" in last or "\\" in last):
        path, raw_val = last, " ".join(tokens[1:-1])
    else:
        path, raw_val = _default_spc_path(), " ".join(tokens[1:])
    if not raw_val:
        printk.error("用法: spc_set <section.key> <value> [path]\n")
        return
    if "." not in dotted:
        printk.error("用法: spc_set <section.key> <value> [path]\n")
        return
    sec, key = dotted.split(".", 1)
    try:
        data = spc.load(path) if os.path.isfile(path) else {}
    except Exception as e:
        printk.error(f"spc_set: 解析 {path} 失败: {e}\n")
        return
    try:
        val = spc.parse_value(raw_val)
    except Exception as e:
        printk.error(f"spc_set: 解析值失败: {e}\n")
        return
    data.setdefault(sec, {})[key] = val
    try:
        spc.dump(data, path)
        printk.ok(f"已写入 {sec}.{key} = {spc.format_value(val)} → {path}\n")
    except Exception as e:
        printk.error(f"spc_set: 写回失败: {e}\n")


def cmd_spc_migrate(args: str):
    """用法: spc_migrate [json2spc|spc2json] [src] [dst]
    默认 json2spc：etc/bootcfg.json → etc/bootcfg.spc（带校验报告）；
    spc2json 反向写回（含 checksum 重算）。只动文件，不动运行中配置。"""
    import json as _json
    tokens = (args or "").strip().split()
    direction = tokens[0] if tokens else "json2spc"
    if direction not in ("json2spc", "spc2json"):
        printk.error("用法: spc_migrate [json2spc|spc2json] [src] [dst]\n")
        return
    etc = os.path.join(main.root_dir, "etc")
    if direction == "json2spc":
        src = tokens[1] if len(tokens) > 1 else os.path.join(etc, "bootcfg.json")
        dst = tokens[2] if len(tokens) > 2 else os.path.join(etc, "bootcfg.spc")
        try:
            with open(src, "r", encoding="utf-8") as f:
                bootcfg = _json.load(f)
        except Exception as e:
            printk.error(f"spc_migrate: 读取 {src} 失败: {e}\n")
            return
        data = spc.bootcfg_to_spc(bootcfg)
        issues = spc.validate(data, spc.BOOTCFG_SCHEMA)
        errs = [i for i in issues if i.level == "error"]
        if errs:
            printk.error(f"spc_migrate: 校验不通过，中止写入（首错：{errs[0].message}）\n")
            return
        try:
            spc.dump(data, dst)
            printk.ok(f"已迁移 {src} → {dst}（附带校验通过）\n")
        except Exception as e:
            printk.error(f"spc_migrate: 写回失败: {e}\n")
    else:
        src = tokens[1] if len(tokens) > 1 else os.path.join(etc, "bootcfg.spc")
        dst = tokens[2] if len(tokens) > 2 else os.path.join(etc, "bootcfg.json")
        try:
            data = spc.load(src)
        except Exception as e:
            printk.error(f"spc_migrate: 解析 {src} 失败: {e}\n")
            return
        issues = spc.validate(data, spc.BOOTCFG_SCHEMA)
        errs = [i for i in issues if i.level == "error"]
        if errs:
            printk.error(f"spc_migrate: 校验不通过，中止写入（首错：{errs[0].message}）\n")
            return
        try:
            import btcfg as _btcfg
            bootcfg = spc.spc_to_bootcfg(data)
            bootcfg["checksum"] = _btcfg.calculate_checksum(bootcfg)
            os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
            with open(dst, "w", encoding="utf-8") as f:
                _json.dump(bootcfg, f)
            printk.ok(f"已迁移 {src} → {dst}（checksum 已重算）\n")
        except Exception as e:
            printk.error(f"spc_migrate: 写回失败: {e}\n")


def cmd_hotreset():
    import hotreset_env
    hotreset_env.trigger()
