'''
 *
 *      elf_cmd.py
 *      The run command: load and execute an ELF binary.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import os
import printk
import logk
import process as proc  # process management lives in process.py (PCB + EEVDF); proc.py is only a compatibility shim
import pyspos
import main
from elf_loader import ELFRunner, __version__ as ELF_LOADER_VERSION


# Load and run an ELF executable.
#
# Usage: run [-v] [-d] [-f] [--stats] [--map] [--disasm [N]] [--strace] [--engine auto|unicorn|native] <elf path>
#
# Options:
#     -v  show the ELF on Windows Space compatibility layer version
#     -d  enable debug logging, which prints much more of the execution
#     -f  force the run, skipping some safety checks
#     --stats   print statistics after the run: instructions, time, memory, segments, symbols, load time
#     --map     print the memory map before the run
#     --disasm [N] disassemble N instructions at the entry point, 10 by default
#     --strace  print the number and arguments of every syscall, for teaching
#     --engine  which engine to use: auto (the default, Unicorn first and a
#               fallback to the in-house emulator), unicorn (forced) or
#               native (forced to the in-house CPU emulator)
def cmd_run(args: str):
    import logging
    import shlex

    # parse the arguments
    show_version = False
    debug_mode = False
    force_mode = False  # legacy -f placeholder: kept for argument compatibility, there is no safety check to skip yet
    show_stats = False
    show_map = False
    disasm_n = 0
    strace = False
    engine = "auto"
    elf_path = None

    # split the arguments with shlex, which honours quotes
    try:
        tokens = shlex.split(args) if args else []
    except ValueError:
        # unbalanced quotes, fall back to a plain split
        tokens = args.split() if args else []

    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token == '-v':
            show_version = True
            i += 1
        elif token == '-d':
            debug_mode = True
            i += 1
        elif token == '-f':
            force_mode = True  # noqa: F841 — same as above, -f is kept for argument compatibility
            i += 1
        elif token == '--stats':
            show_stats = True
            i += 1
        elif token == '--map':
            show_map = True
            i += 1
        elif token == '--strace':
            strace = True
            i += 1
        elif token == '--disasm':
            # Only a real count is consumed. Swallowing the next token blindly ate
            # the file name in `run --disasm --stats file` and even the option
            # itself, so --disasm has to leave anything non-numeric alone.
            nxt = tokens[i + 1] if i + 1 < len(tokens) else None
            if nxt is not None and nxt.isdigit():
                disasm_n = int(nxt)
                i += 2
            else:
                disasm_n = 10
                i += 1
        elif token.startswith('--disasm='):
            try:
                disasm_n = int(token.split('=', 1)[1])
            except ValueError:
                disasm_n = 10
            i += 1
        elif token == '--engine':
            try:
                engine = tokens[i + 1].strip().lower()
                if engine not in ('auto', 'unicorn', 'native'):
                    printk.error(f"run: --engine 取值须为 auto|unicorn|native，got: {engine}\n")
                    return
                i += 2
            except IndexError:
                printk.error("run: --engine 缺少取值（auto|unicorn|native）\n")
                return
        elif token.startswith('--engine='):
            engine = token.split('=', 1)[1].strip().lower()
            if engine not in ('auto', 'unicorn', 'native'):
                printk.error(f"run: --engine 取值须为 auto|unicorn|native，got: {engine}\n")
                return
            i += 1
        elif token.startswith('-'):
            printk.error(f"run: 未知选项: {token}\n")
            return
        else:
            if elf_path is None:
                elf_path = token
                i += 1
            else:
                i += 1

    if elf_path == 'moo':
        print("                 (__)")
        print("                 (oo)")
        print("           /------\\/ ")
        print("          / |    ||  ")
        print("         *  /\\---/\\  ")
        print("            ~~   ~~  ")
        print('..."Have you mooed today?"...')
        print()
        print("       想要更多超级牛力吗？试试 run -v！")
        return

    if show_version:
        print(f"ELF/SPE 运行于 PySpOS (在 {pyspos.OS_NAME} {pyspos.OS_VERSION} {pyspos.OS_DEVELOP_STAGE} 中) {ELF_LOADER_VERSION}")
        print("版权所有 (C) 2022-2026 GoutouStdio。")
        print("本程序是自由软件；请参阅源代码以了解复制条件。本软件不提供任何保证，")
        print("即使是适销性或特定用途适用性的默示保证也不存在。")
        print()
        print("主页: <https://pyspos.us.ci/pyspos.html>")
        print("源代码: <https://github.com/GoutouStdio-cn/PySpOS>")
        print("问题反馈: <https://github.com/GoutouStdio-cn/PySpOS/issues>")
        print("         或 <goutoustudio@outlook.com>")
        print()
        print("     本 ELF/SPE on Windows 具有超级牛力。")
        print()
        if elf_path is None:
            return
        print("执行ELF程序...")
    
    # check the ELF path
    if elf_path is None:
        printk.error("用法: run [-v] [-d] [-f] [--stats] [--map] [--disasm [N]] [--strace] [--engine auto|unicorn|native] <elf文件路径>\n")
        return
    
    # set the log level
    if debug_mode:
        logging.basicConfig(level=logging.DEBUG, format='%(levelname)s: %(message)s')
        logk.printl("run", "调试模式已启用", main.boot_time)
        logk.printl("run", f"ELF 路径: {elf_path}", main.boot_time)
    else:
        logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    
    # check whether the file exists
    if not os.path.exists(elf_path):
        # try the elf_apps directory
        alt_path = os.path.join(os.getcwd(), "elf_apps", elf_path)
        if debug_mode:
            logk.printl("run", f"尝试查找: {alt_path}", main.boot_time)
        if not os.path.exists(alt_path):
            alt_path = os.path.join(os.getcwd(), "test_programs", elf_path)
            if debug_mode:
                logk.printl("run", f"尝试查找: {alt_path}", main.boot_time)
        if os.path.exists(alt_path):
            elf_path = alt_path
            if debug_mode:
                logk.printl("run", f"找到 ELF 文件: {elf_path}", main.boot_time)
    
    if not os.path.isfile(elf_path):
        printk.error(f"未找到 ELF 文件: {elf_path}\n")
        return
    
    if debug_mode:
        logk.printl("run", f"文件大小: {os.path.getsize(elf_path)} 字节", main.boot_time)
        logk.printl("run", "开始加载 ELF 文件...", main.boot_time)
    
    pcb = proc.spawn(f"run {elf_path}", kind="elf")
    try:
        # mute logging unless debug mode is on
        if not debug_mode:
            logging.disable(logging.CRITICAL)

        # engine choice: Unicorn by default for real machine semantics, falling back to the in-house engine on failure.
        from elf_loader import unicorn_available
        runner = None
        engine_used = "native"
        if engine in ("auto", "unicorn"):
            if unicorn_available():
                try:
                    from elf_loader.unicorn_runner import UnicornRunner
                    runner = UnicornRunner(elf_path)
                    engine_used = "unicorn"
                except Exception as e:
                    logk.printl("run", f"unicorn 引擎初始化失败: {e}", main.boot_time)
                    if engine == "unicorn":
                        # The user named unicorn explicitly, so running on the
                        # in-house engine instead has to be said out loud: silently
                        # downgrading would report an engine that never ran.
                        printk.warn("unicorn 引擎初始化失败，已降级到自研引擎执行\n")
                    runner = None
            elif engine == "unicorn":
                printk.error("unicorn 库不可用（pip install unicorn），无法强制使用 unicorn 引擎\n")
                proc.finish(pcb.pid, 1, failed=True)
                if not debug_mode:
                    logging.disable(logging.NOTSET)
                return
        if runner is None:
            # native fallback, the in-house CPU emulator
            runner = ELFRunner(elf_path)
            engine_used = "native"
        if debug_mode or show_stats:
            logk.printl("run", f"执行引擎: {engine_used}", main.boot_time)

        # load the ELF file
        if not runner.load():
            # in auto mode, if Unicorn fails to load, retry once with the native engine
            if engine == "auto" and engine_used == "unicorn":
                printk.warn("unicorn 加载失败，降级到自研引擎重试...\n")
                runner = ELFRunner(elf_path)
                engine_used = "native"
                if not runner.load():
                    printk.error("ELF 文件加载失败\n")
                    proc.finish(pcb.pid, 1, failed=True)
                    if not debug_mode:
                        logging.disable(logging.NOTSET)
                    return
            else:
                printk.error("ELF 文件加载失败\n")
                proc.finish(pcb.pid, 1, failed=True)
                if not debug_mode:
                    logging.disable(logging.NOTSET)
                return

        if show_map:
            print("内存映射 (start-size-name-perms):")
            try:
                for start, size, name, perms in runner.get_memory_map():
                    print(f"  0x{start:08x}-0x{start + size:08x} {name} {perms}")
            except Exception as e:
                printk.error(f"读取内存映射失败: {e}")
            print()

        if disasm_n:
            print(f"反汇编（入口 {disasm_n} 条）:")
            try:
                for addr, name, length, operands in runner.disassemble(count=disasm_n):
                    print(f"  0x{addr:08x}: {name} (len={length} ops={operands})")
            except Exception as e:
                printk.error(f"反汇编失败: {e}")
            print()

        if strace:
            _orig_handler = runner.syscall_emulator.handle_syscall

            # Wrapper installed on the syscall handler for --strace.
            def _traced(number, *a, **kw):
                # Named arguments are part of the call too, and a syscall that
                # takes them looks silently different without them.
                print(f"[strace] syscall nr={number} args={list(a)} kwargs={kw}")
                return _orig_handler(number, *a, **kw)

            runner.syscall_emulator.handle_syscall = _traced

        if debug_mode:
            logk.printl("run", "ELF 文件加载成功", main.boot_time)
            logk.printl("run", f"入口点: 0x{runner.parser.header.e_entry:08X}", main.boot_time)
            logk.printl("run", f"架构: {'x86_64' if runner.parser.header.e_machine == 62 else 'x86'}", main.boot_time)
            logk.printl("run", f"程序头数量: {runner.parser.header.e_phnum}", main.boot_time)
            logk.printl("run", f"节头数量: {runner.parser.header.e_shnum}", main.boot_time)
            logk.printl("run", "开始执行程序...", main.boot_time)

        # run the program
        result = runner.run()

        if debug_mode:
            logk.printl("run", "程序执行完成", main.boot_time)
            logk.printl("run", f"退出码: {result.exit_code}", main.boot_time)
            logk.printl("run", f"执行指令数: {result.instruction_count}", main.boot_time)
            logk.printl("run", f"执行时间: {result.execution_time:.3f} 秒", main.boot_time)
            logk.printl("run", f"内存使用: {result.memory_usage} 字节", main.boot_time)

        if show_stats:
            stats = getattr(runner, "stats", None)
            loader = getattr(runner, "loader", None)
            segs = getattr(stats, "segments_loaded", len(getattr(loader, "segments", []) or []))
            syms = getattr(stats, "symbols_resolved", len(getattr(loader, "symbols", {}) or {}))
            regions = getattr(stats, "memory_regions", len(getattr(loader, "memory", {}) or {}))
            load_t = getattr(stats, "load_time", 0.0)
            print("---- ELF stats ----")
            print(f"引擎: {engine_used}")
            print(f"退出码: {result.exit_code}")
            print(f"指令数: {result.instruction_count}")
            print(f"耗时: {result.execution_time:.3f}s")
            print(f"内存: {result.memory_usage} 字节")
            print(f"段: {segs}  符号: {syms}  "
                  f"内存区: {regions}  加载耗时: {load_t:.3f}s")
            if result.signal:
                print(f"信号: {result.signal}  fault_addr: 0x{result.fault_addr:x}")
            print("-------------------")

        proc.finish(pcb.pid, int(result.exit_code or 0))

        # restore logging
        if not debug_mode:
            logging.disable(logging.NOTSET)

        # print the program output
        if result.stdout:
            print(result.stdout, end='')
        if result.stderr:
            print(result.stderr, end='', file=__import__('sys').stderr)

    except Exception as e:
        proc.finish(pcb.pid, 1, failed=True)
        if not debug_mode:
            logging.disable(logging.NOTSET)
        printk.error(f"运行 ELF 文件失败: {str(e)}\n")
        if debug_mode:
            import traceback
            traceback.print_exc()

