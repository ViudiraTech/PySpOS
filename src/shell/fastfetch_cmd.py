'''
 *
 *      fastfetch_cmd.py
 *      The fastfetch wrapper: runs the real host binary with PySpOS branding.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import json
import os
import shlex
import shutil
import tempfile

LOGO = "\n".join([
    " ____       ____  ",
    "|  _ \\ _   / ___| ",
    "| |_) | | | \\___ \\ ",
    "|  __/| |_| |___) |",
    "|_|    \\__, |___/  ",
    "       |___/       ",
])

CONFIG_NAME = "pyspos-fastfetch.jsonc"


# Return the real host binary, bypassing our own registry entry.
def real_binary():
    return shutil.which("fastfetch")


# Our identity overrides, spliced into the default structure at runtime.
# Everything else keeps fastfetch's own detection, so a fastfetch upgrade
# can add modules without us having to track its module list.
def brand_modules(version, arch):
    return {
        "os": {"type": "os", "format": f"PySpOS {version} {arch}"},
        "host": {"type": "host", "format": "PySpOS Virtual Machine"},
        "kernel": {"type": "kernel", "format": f"PySpKernel {version}"},
        "shell": {"type": "shell", "format": f"PySpOS shell {version}"},
        "terminal": {"type": "terminal", "format": "PySpOS terminal"},
    }


# Ask the real binary for its default structure, then splice our branded
# modules in place. Falls back to branding only when that fails.
def default_structure(binary):
    import subprocess
    try:
        proc = subprocess.run(
            [binary, "--print-structure"], capture_output=True, text=True,
            timeout=10)
        names = proc.stdout.strip().split(":")
        return [name for name in names if name]
    except Exception:
        return []


# Write the branding config idempotently and return its path.
# A stable cache file instead of --config - so piped stdin is never stolen.
def config_path(version, arch, binary):
    path = os.path.join(tempfile.gettempdir(), CONFIG_NAME)
    branded = brand_modules(version, arch)
    modules = []
    for name in default_structure(binary):
        key = name.lower()
        if key in branded:
            modules.append(branded[key])
        else:
            modules.append(name)
    if not modules:
        modules = list(branded.values())
    config = {"modules": modules}
    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(config, handle)
    except OSError:
        return None
    return path


# Split user args into (tokens, has_logo, has_config, has_structure).
def scan_args(tokens):
    has_logo = has_config = has_structure = False
    skip_next = False
    for token in tokens:
        if skip_next:
            skip_next = False
            continue
        if token in ("-l", "--logo", "--logo-type", "-c", "--config",
                     "-s", "--structure"):
            if token in ("-l", "--logo", "--logo-type"):
                has_logo = True
            elif token in ("-c", "--config"):
                has_config = True
            else:
                has_structure = True
            skip_next = True
            continue
        if token.startswith("--logo=") or token.startswith("--config=") \
                or token.startswith("--structure="):
            if "logo" in token:
                has_logo = True
            elif "config" in token:
                has_config = True
            else:
                has_structure = True
    return has_logo, has_config, has_structure


# Run fastfetch with PySpOS branding. Anything the user spelled out wins:
# their --logo/--config/--structure disables our injection for that axis.
def cmd_fastfetch(args=""):
    import printk
    binary = real_binary()
    if binary is None:
        printk.error("fastfetch: 宿主没有安装 fastfetch\n")
        return 127
    try:
        import pyspos
        version = pyspos.OS_VERSION
    except Exception:
        version = ""
    try:
        import platform
        arch = platform.machine() or "x86_64"
    except Exception:
        arch = "x86_64"
    try:
        tokens = shlex.split(args) if args else []
    except ValueError:
        tokens = args.split() if args else []
    has_logo, has_config, has_structure = scan_args(tokens)
    final = [binary]
    if not has_config and not has_structure:
        path = config_path(version, arch, binary)
        if path is not None:
            final += ["--config", path]
    if not has_logo:
        final += ["--logo-type", "data-raw", "--logo", LOGO]
    final += tokens
    from . import hostexec
    try:
        handled, status = hostexec.run_status(final, False)
    except Exception as exc:
        printk.error(f"fastfetch: 启动失败: {exc}\n")
        return 1
    if not handled:
        printk.error("fastfetch: 找到但无法执行\n")
        return 126
    return status
