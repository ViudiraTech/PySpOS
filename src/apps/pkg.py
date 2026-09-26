'''
 *
 *      pkg.py
 *      Command line front end of the user package manager.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import os
import shlex

import api

_USAGE = "用法: pkg <list|info|verify|install|remove|build> ...\n"


# Split the argument list the shell passed in PYSPOS_APP_ARGS.
def _args():
    raw = os.environ.get("PYSPOS_APP_ARGS", "")
    try:
        return shlex.split(raw)
    except ValueError:
        return raw.split()


# Collect every command name a manifest offers: entry points plus aliases.
def _names(manifest):
    names = []
    for entry in manifest.get("entrypoints", []):
        names.append(entry["name"])
        names.extend(entry.get("aliases", []))
    return names


# Print one manifest: id, version, description and command names.
def _print_manifest(manifest):
    print(f"包: {manifest['id']}@{manifest['version']}")
    if manifest.get("description"):
        print(f"说明: {manifest['description']}")
    print("命令: " + ", ".join(_names(manifest)))
    print()


# List the installed user packages as an ID/VERSION/COMMANDS table.
def _list():
    packages = api.package_list()
    if not packages:
        print("没有已安装的用户包。\n")
        return
    print(f"{'ID':<28} {'VERSION':<12} COMMANDS")
    for manifest in packages:
        print(f"{manifest['id']:<28} {manifest['version']:<12} "
              f"{', '.join(_names(manifest))}")
    print()


# pkg info <id>: print the manifest of an installed package.
def _info(tokens):
    if len(tokens) != 1:
        api.api_error("用法: pkg info <包id>\n")
        return
    manifest = api.package_info(tokens[0])
    if manifest is None:
        api.api_error(f"包未安装: {tokens[0]}\n")
        return
    _print_manifest(manifest)


# pkg verify <dir|file>: check a package without installing it.
def _verify(tokens):
    if len(tokens) != 1:
        api.api_error("用法: pkg verify <包目录|包文件>\n")
        return
    manifest = api.package_verify(tokens[0])
    api.api_ok(f"包校验通过: {manifest['id']}@{manifest['version']}\n")
    print("入口: " + ", ".join(_names(manifest)) + "\n")


# pkg install <dir|file>: install a package (ROOT, unlocked device).
def _install(tokens):
    if len(tokens) != 1:
        api.api_error("用法: pkg install <包目录|包文件>\n")
        return
    manifest = api.package_install(tokens[0])
    api.api_ok(f"已安装: {manifest['id']}@{manifest['version']}\n")
    print("可用命令: " + ", ".join(_names(manifest)) + "\n")


# pkg remove <id>: uninstall a package (ROOT, unlocked device).
def _remove(tokens):
    if len(tokens) != 1:
        api.api_error("用法: pkg remove <包id>\n")
        return
    manifest = api.package_remove(tokens[0])
    api.api_ok(f"已删除: {manifest['id']}\n")


# pkg build <dir> [out.pyspkg]: pack a package, defaulting the output
# name to <id>.pyspkg in the working directory.
def _build(tokens):
    if len(tokens) not in (1, 2):
        api.api_error("用法: pkg build <包目录> [输出.pyspkg]\n")
        return
    source = tokens[0]
    if len(tokens) == 2:
        output = tokens[1]
    else:
        manifest = api.package_verify(source)
        output = os.path.join(os.getcwd(), manifest["id"] + ".pyspkg")
    output = api.package_build(source, output)
    api.api_ok(f"已生成包文件: {output}\n")


# Dispatch the pkg subcommand, falling back to the usage line.
def main():
    tokens = _args()
    if not tokens:
        api.api_error(_USAGE)
        return
    action = tokens[0]
    args = tokens[1:]
    if action == "list":
        _list()
    elif action == "info":
        _info(args)
    elif action == "verify":
        _verify(args)
    elif action == "install":
        _install(args)
    elif action == "remove":
        _remove(args)
    elif action == "build":
        _build(args)
    else:
        api.api_error(_USAGE)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        api.api_error(f"pkg: {exc}\n")
