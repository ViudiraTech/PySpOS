'''
 *
 *      sys_cmds.py
 *      Built-in system and file shell commands.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import os
import platform
import printk
import fastboot
import fs
import kernel
import recovery
import process as proc  # process management lives in process.py (PCB + EEVDF); proc.py is only a compatibility shim
import spc
import pyspos
import main

if pyspos.SPF_ENABLED:
    import parse_spf
else:
    # Placeholder used when the build has SPF support compiled out.
    class parse_spf:
        # Always raise: SPF support is disabled in this build.
        @staticmethod
        def run_spf(spf_path):
            raise NotImplementedError("SPF support is disabled in this build. spf path: " + spf_path)


# Easter egg behind shb, printed once per CPU core.
def print_sunhb():
    cores = kernel.cores
    print(f"'shb'程序将打印孙浩博是小可爱！{cores}次。\n")
    print("孙浩博是 " * cores)
    print("小可爱！ " * cores)
    print()

# help lists the commands per group; help <command> shows the detail of one.
# The text comes from the registry metadata in commands.py, so a new command
# needs no hand-written help here.
def cmd_help(args: str = ""):
    import commands as _reg
    _reg.register_discovered()
    topic = (args or "").strip()
    if topic:
        print(_reg.render_help(topic))
        return
    print(_reg.render_help())

# echo prints its text, honouring -n for no newline and -e for escapes.
def cmd_echo(text: str = ""):
    import shlex
    try:
        tokens = shlex.split(text) if text else []
    except ValueError:
        tokens = text.split() if text else []
    newline, interpret = True, False
    while tokens and tokens[0] in ("-n", "-e", "-en", "-ne"):
        if "n" in tokens[0]:
            newline = False
        if "e" in tokens[0]:
            interpret = True
        tokens = tokens[1:]
    out = " ".join(tokens)
    if interpret:
        out = out.encode("utf-8").decode("unicode_escape")
    if newline:
        print(out)
    else:
        print(out, end="")

# Print the PySpOS version, its develop stage and the Python version.
def cmd_osver():
    print(f"PySpOS 版本: {pyspos.OS_VERSION}, 开发阶段: {pyspos.OS_DEVELOP_STAGE}")
    print(f"Python 版本: {platform.python_version()}\n")

# Shut PySpOS down through the kernel.
def cmd_shutdown():
    kernel.exit()

# Clear the screen, picking the command that fits the host OS.
def cmd_clear():
    if os.name == "nt":
        os.system("cls")
    else:
        os.system("clear")

# Start the host Python interpreter, asking for ROOT when the boot is locked.
def cmd_python():
    try:
        if main.boot_locked:
            main.require_root("python")
    except PermissionError as exc:
        printk.error(f"{exc}\n")
        return
    os.system("python")
    print()

# Enter recovery mode, asking for ROOT when the boot is locked.
def cmd_recovery():
    try:
        if main.boot_locked:
            main.require_root("recovery")
    except PermissionError as exc:
        printk.error(f"{exc}\n")
        return
    recovery.recovery_main("kernel_jump")

# Enter fastboot mode, asking for ROOT when the boot is locked. The mode has
# no local UI on purpose: it only serves the protocol, so every privileged
# action has to come from the host-side graphical client.
def cmd_fastboot(args: str = ""):
    try:
        if main.boot_locked:
            main.require_root("fastboot")
    except PermissionError as exc:
        printk.error(f"{exc}\n")
        return
    port = fastboot.DEFAULT_PORT
    text = (args or "").strip()
    if text:
        if text.startswith("--port"):
            text = text[6:].strip()
        try:
            port = int(text)
        except ValueError:
            printk.error("用法：fastboot [--port 端口号]\n")
            return
    fastboot.fastboot_main("kernel_jump", port)

# Reboot the device, or jump into fastboot with "reboot bootloader".
def cmd_reboot(args: str = ""):
    target = (args or "").strip() or "system"
    if target == "bootloader":
        fastboot.fastboot_main("reboot_bootloader")
        return
    if target not in ("system", "poweroff"):
        printk.error("用法：reboot [bootloader|system|poweroff]\n")
        return
    if target == "poweroff":
        kernel.exit()
        return
    printk.info("正在重启 PySpOS...\n")
    import hotreset_env
    hotreset_env.trigger()

# Easter egg: print the banner plus a code point and its reverse lookup.
def cmd_shb():
    print_sunhb()
    char = '你'
    print(f"字符：{char}")
    print(f"十六进制编码：U+{ord(char):04X}")  # prints U+AFAF
    print(f"十进制编码：{ord(char)}")          # prints 44975

    # 2. the reverse direction: from a code point back to the character
    code = ord(char)
    print(f"编码0x{code:04X}对应的字符：{chr(code)}")  # prints that character

# List the entries of the current directory.
def cmd_ls(args: str = ""):
    target = (args or "").strip()
    if not target:
        items = fs.list_dir()
    else:
        if not os.path.isdir(target):
            printk.error(f"ls: 无法访问 {target}: 没有那个目录\n")
            return 1
        try:
            items = sorted(os.listdir(target))
        except OSError as exc:
            printk.error(f"ls: 读取 {target} 失败: {exc}\n")
            return 1
    for item in items:
        print(item)
    return 0

# Change the working directory, keeping OLDPWD so cd - works.
def cmd_cd(path: str = None):
    # change the working directory
    if path is None or path.strip() == "":
        # with no argument, go to the home directory
        path = os.path.expanduser("~")
    
    # handle the special paths
    if path == "-":
        # go back to the previous directory
        path = os.environ.get("OLDPWD", os.getcwd())
    elif path == "~":
        path = os.path.expanduser("~")
    
    # remember the current directory
    old_cwd = os.getcwd()
    
    try:
        # try to change directory
        os.chdir(path)
        # update the OLDPWD environment variable
        os.environ["OLDPWD"] = old_cwd
        # print the current directory
        print(os.getcwd())
        return 0
    except FileNotFoundError:
        printk.error(f"cd: 没有那个文件或目录: {path}\n")
    except NotADirectoryError:
        printk.error(f"cd: 不是目录: {path}\n")
    except PermissionError:
        printk.error(f"cd: 权限拒绝: {path}\n")
    except Exception as e:
        printk.error(f"cd: 错误: {e}\n")
    return 1

# Finfo prints the size, mtime and directory flag of a path.
def cmd_finfo(filename: str):
    info = fs.get_file_info(filename) # fetch file information
    if info:    
        print(f"{filename} 的文件信息\n大小: {info['size']} 字节, 修改时间: {info['modified']}, 是否为目录: {info['is_dir']}\n")
    else:
        print(f"未找到文件或目录: {filename}\n")

# rm deletes a file, or a directory only with -r; -f skips the confirmation.
def cmd_rm(target: str, recursive: bool = False, force: bool = False):
    if not target or target.strip() == "":
        printk.error("rm: 缺少操作数\n")
        return
    
    target = target.strip()
    
    # safety check
    if not main.is_safe_filename(target):
        printk.error("错误：文件名不允许包含 ../ 或绝对路径\n")
        return
    
    # resolve the absolute path
    full_path = os.path.abspath(target)
    
    # check whether the file or directory exists
    if not os.path.exists(full_path):
        printk.error(f"rm: 无法删除 '{target}': 没有那个文件或目录\n")
        return
    
    try:
        # decide whether it is a file or a directory
        if os.path.isfile(full_path):
            # delete a file
            if not force:
                if not printk.confirm(f"确认删除文件 '{target}'?"):
                    print("操作已取消\n")
                    return
            os.remove(full_path)
            printk.ok(f"已删除文件: {target}\n")
            
        elif os.path.isdir(full_path):
            # delete the directory
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

# Report whether ROOT privileges are currently active.
def cmd_testroot():
    if main.rootstate:
        print("当前处于 ROOT 权限状态。")
        print(f"rootstate 变量值为: {main.rootstate}\n")
    else:
        print("当前未处于 ROOT 权限状态。")
        print(f"rootstate 变量值为: {main.rootstate}\n")


# Print the trust domain, signature state, slot and anti-rollback floor.
# Needs ROOT, and ROOT only affects runtime permissions, never the OEM keys or the policy signature.
def cmd_bootloader_status():
    try:
        main.require_root("查看 Bootloader 状态")
    except PermissionError as exc:
        printk.error(f"{exc}\n")
        return
    try:
        import ota
        import secure_boot
        root_dir = main.root_dir
        policy = secure_boot.read_policy(root_dir)
        locked = secure_boot.read_locked(root_dir)
        state = secure_boot.load_state(root_dir)
        current = ota.get_current_slot()
        floor = max(state["rollback_index"],
                    secure_boot.policy_rollback_index(root_dir))
        manifest = secure_boot.verify_slot(
            root_dir, current, locked=locked, floor=floor)
        print("Bootloader 状态")
        print(f"  信任域: {'LOCKED' if locked else 'UNLOCKED'}")
        print(f"  policy: {'已签名' if policy else '缺失（按锁定处理）'}")
        print(f"  当前槽位: {current}")
        print(f"  镜像: {'签名有效' if manifest else '未签名/开发镜像'}")
        if manifest:
            print(f"  签名 key_id: {manifest['key_id']}")
            print(f"  security_version: {manifest['security_version']}")
        print(f"  防回滚下限: {floor}")
        developer_key_fn = getattr(secure_boot, "developer_key_id", None)
        developer_key = (developer_key_fn(root_dir)
                         if callable(developer_key_fn) else None)
        print(f"  开发签名 key_id: {developer_key or '未生成/不可用'}")
        root_fn = getattr(main, "is_root", None)
        root_active = root_fn() if callable(root_fn) else bool(main.rootstate)
        print(f"  ROOT: {'持久/临时权限已启用' if root_active else '未启用'}")
        print("  结论: ROOT 只影响运行时权限，不能修改 OEM 公钥或 policy 签名。")
    except Exception as exc:
        printk.error(f"Bootloader 状态不可用: {exc}\n")


# Run an app from apps/ as a forked child and wait for it.
def cmd_open(app_name: str):

    if not app_name.endswith(".py"):
        app_name += ".py"
    if not main.is_safe_filename(app_name):
        printk.error("错误：文件名不允许包含 ../ 或绝对路径\n")
        return
    app_path = main.get_app_path(app_name)
    if not os.path.isfile(app_path):
        printk.error(f"未找到可执行文件: {app_name}\n")
        return
    import forkexec
    pcb = forkexec.fork_exec(
        f"app:{app_name}", kind="app", src_dir=main.script_dir,
        apps_dir=os.path.join(main.script_dir, "apps"))
    forkexec.wait(pcb.pid, timeout=None)
    proc.reap_children(pcb.ppid)


# Run an spf script from spfapps/ as a forked child and wait for it.
def cmd_openspf(app_name: str):
    if not app_name.endswith(".spf"):
        app_name += ".spf"
    if not main.is_safe_filename(app_name):
        printk.error("错误：文件名不允许包含 ../ 或绝对路径\n")
        return
    app_path = main.get_spf_path(app_name)
    if not os.path.isfile(app_path):
        printk.error(f"未找到可执行文件: {app_name}\n")
        return
    import forkexec
    pcb = forkexec.fork_exec(
        f"spf:{app_path}", kind="spf", src_dir=main.script_dir,
        apps_dir=os.path.join(main.script_dir, "apps"))
    forkexec.wait(pcb.pid, timeout=None)
    proc.reap_children(pcb.ppid)


# Print the current working directory.
def cmd_pwd():
    print(os.getcwd() + "\n")


# Print the system user name.
def cmd_whoami():
    try:
        print(kernel.get_system_username() + "\n")
    except Exception as e:
        printk.error(f"whoami: {e}\n")


# Cat prints files, or the piped input when given no argument and stdin is not a terminal.
def cmd_cat(args: str = ""):
    import shlex
    try:
        tokens = shlex.split(args) if args else []
    except ValueError:
        tokens = args.split() if args else []
    if not tokens:
        import stdinctx
        if not stdinctx.is_tty():
            print(stdinctx.read_text(), end="")
            return
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


# Grep [-ivncq] filters lines by substring; without a file it reads piped input.
# With -q it stops at the first match, which is what makes grep -q close a pipe early.
def cmd_grep(args: str = ""):
    import shlex
    try:
        tokens = shlex.split(args) if args else []
    except ValueError:
        tokens = args.split() if args else []
    flags = set()
    while tokens and tokens[0].startswith("-") and len(tokens[0]) > 1 \
            and set(tokens[0][1:]) <= set("ivncq"):
        flags.update(tokens[0][1:])
        tokens = tokens[1:]
    if not tokens:
        printk.error("用法: grep [-ivncq] <模式> [文件]\n")
        return 1
    pattern = tokens[0]
    if "i" in flags:
        lowered = pattern.lower()
        match = lambda line: lowered in line.lower()
    else:
        match = lambda line: pattern in line
    if len(tokens) > 1:
        texts = []
        for name in tokens[1:]:
            text = fs.cat_file(name)
            if text is None:
                printk.error(f"grep: 未找到文件: {name}\n")
                continue
            texts.append((name, text))
    elif "q" in flags:
        import stdinctx
        for line in stdinctx.iter_lines():
            ok = match(line)
            if "v" in flags:
                ok = not ok
            if ok:
                return 0
        return 1
    else:
        import stdinctx
        texts = [(None, stdinctx.read_text())]
    hits = 0
    multi = len(texts) > 1
    for name, text in texts:
        for number, line in enumerate(text.splitlines(), 1):
            ok = match(line)
            if "v" in flags:
                ok = not ok
            if not ok:
                continue
            hits += 1
            if "q" in flags:
                return 0
            if "c" in flags:
                continue
            prefix = ""
            if multi and name:
                prefix += f"{name}:"
            if "n" in flags:
                prefix += f"{number}:"
            print(prefix + line if prefix else line)
    if "c" in flags and "q" not in flags:
        print(hits)
    return 0 if hits else 1


# Create directories; -p is accepted and ignored since parents are always made.
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


# Create an empty file, making the parent directory if needed.
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


# Shared body of cp and mv: exactly two arguments, and cp copies a tree when the source is a directory.
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


# Copy the source to the destination, copying a tree when the source is a directory.
def cmd_cp(args: str):
    _copy_move(args, "cp")


# Move the source to the destination.
def cmd_mv(args: str):
    _copy_move(args, "mv")


# List the recorded command history, most recent last.
def cmd_history():
    for i, c in enumerate(main._cmd_history, 1):
        print(f"{i:4d}  {c}")
    print()



# Print the live boot configuration in SpaceConfig form.
def cmd_spc_show():
    try:
        data = spc.bootcfg_to_spc(main.bootcfg)
        print(spc.dumps(data))
    except Exception as e:
        printk.error(f"spc_show: {e}\n")


# Write the live boot configuration to an .spc file.
def cmd_spc_export(args: str):
    path = (args or "").strip() or os.path.join("etc", "bootcfg.spc")
    try:
        spc.dump(spc.bootcfg_to_spc(main.bootcfg), path)
        printk.ok(f"已导出 SpaceConfig: {path}\n")
    except Exception as e:
        printk.error(f"spc_export: {e}\n")


# Return the default .spc path, etc/bootcfg.spc under the boot root.
def _default_spc_path() -> str:
    return os.path.join(main.root_dir, "etc", "bootcfg.spc")


# Usage: spc_validate [path] - parse and check the .spc against BOOTCFG_SCHEMA, with line numbers.
def cmd_spc_validate(args: str):
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


# Usage: spc_get <section.key> [path] - read a key, falling back to the live boot
# configuration when the default .spc file is missing.
def cmd_spc_get(args: str):
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


# Usage: spc_set <section.key> <value> [path] - parse the value with spc syntax and
# write it back to the file. A value with spaces can be written directly; the last token
# is treated as a path only when it is an existing file or looks like one, otherwise it
# joins the value and the default path is used.
def cmd_spc_set(args: str):
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


# Usage: spc_migrate [json2spc|spc2json] [src] [dst]
# The default json2spc turns etc/bootcfg.json into etc/bootcfg.spc with a validation
# report; spc2json goes the other way and recomputes the checksum. Only files change,
# never the running configuration.
def cmd_spc_migrate(args: str):
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


# Trigger a hot restart of the system.
def cmd_hotreset():
    import hotreset_env
    hotreset_env.trigger()


# Re-run the first-boot wizard by hand; at boot it only runs automatically while
# etc/.oobe_done is missing.
def cmd_oobe():
    import oobe
    ok = oobe.run_wizard(oobe._live_ctx(main.root_dir))
    if ok:
        printk.ok("OOBE 已完成并写入\n")
    else:
        printk.warn("OOBE 已中止，未写入标记\n")
    print()


# Show or switch the language, timezone and display name.
# Changes take effect at once and are persisted to the boot configuration.
def cmd_locale(args: str = ""):
    import syslocale
    from syslocale import _
    import btcfg
    parts = (args or "").strip().split(None, 1)
    if not parts:
        user = main.bootcfg.get("display_name") or kernel.get_system_username()
        print(_("locale.current", lang=syslocale.get_language(),
               tz=syslocale.get_timezone(), user=user) + "\n")
        return
    if len(parts) != 2:
        printk.error(_("locale.usage") + "\n")
        return
    field, value = parts[0].lower(), parts[1].strip()
    if field == "lang":
        if syslocale.set_language(value):
            btcfg.set_bootcfg_value("lang", value)
            printk.ok(_("locale.lang_ok", lang=value) + "\n")
        else:
            printk.error(_("locale.lang_bad", langs=",".join(syslocale.SUPPORTED_LANGS)) + "\n")
    elif field in ("tz", "timezone"):
        if syslocale.set_timezone(value):
            btcfg.set_bootcfg_value("timezone", value)
            printk.ok(_("locale.tz_ok", tz=value, now=syslocale.now_str("%H:%M:%S")) + "\n")
        else:
            printk.error(_("locale.tz_bad", tz=value) + "\n")
    elif field == "user":
        btcfg.set_bootcfg_value("display_name", value)
        printk.ok(_("locale.user_ok", user=value) + "\n")
    else:
        printk.error(_("locale.usage") + "\n")
