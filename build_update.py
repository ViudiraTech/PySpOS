# PySpOS 更新包构建工具（ canonical 构建入口，2026-09-24 起统一）。
# 说明：历史上有两份构建脚本（根目录 build_update.py 与 src/calculate_zip_info.py），
# 现统一以本文件为准；src/calculate_zip_info.py 已改为弃用垫片，自动转发到本模块的 main()。
#
# 2026-09-24：新增非交互模式（命令行参数）。原版全程 input()，无法在 CI 或
# 脚本里复现构建；且更新包漏了 requirements.txt / LICENSE / README.md，
# 而 README 的快速开始恰恰让用户执行 `pip install -r requirements.txt`——
# 全新安装照做必然失败。
import argparse
import os
import zipfile
import hashlib
import json
import secure_boot
from datetime import datetime

# 排除的目录和文件
EXCLUDE_DIRS = {'docs', 'slot_a', 'slot_b', '__pycache__', 'etc', '.oldcode', '.git'}
EXCLUDE_FILES = {'.hotreset'}

# 根目录随包分发的文件。
# 2026-09-24 修正：原先只发 5 个文件，漏掉 requirements.txt（用户装依赖要用）、
# LICENSE 与 README.md（许可与上手说明），导致从 OTA 装的系统按文档跑不起来。
# 另：current_slot 是**构建机的运行期状态**，打进包里会让新装系统以为该从某个
# 槽位启动；它在 src/ 下有槽位校验所需的同名文件，故这里只排除根目录那份。
ROOT_FILES = [
    'launcher.py', 'start.bat', 'start.sh', 'build_update.py',
    'requirements.txt', 'pyproject.toml', 'LICENSE', 'README.md',
    'secure_boot.py',
]

# 站内静态页里内嵌了一份 version.json 的副本做兜底（fetch 失败时用）。
# 手工维护那份副本必然漂移——它已经落后两个版本了。改为构建时自动回填。
FALLBACK_TARGET = os.path.join('docs', 'ota', 'releases.html')
FALLBACK_START = 'const fallbackVersionData = '
FALLBACK_END = ';\n'


def sync_static_fallback(version_data=None):
    """把 version.json 的内容回填进 releases.html 的 fallbackVersionData。

    返回 True 表示已更新。这样任何一次构建都会顺带刷新静态页，
    不存在「忘了同步」这种可能。
    """
    if version_data is None:
        vj = os.path.join('docs', 'ota', 'version.json')
        if not os.path.exists(vj):
            return False
        with open(vj, 'r', encoding='utf-8') as f:
            version_data = json.load(f)
    if not os.path.exists(FALLBACK_TARGET):
        return False
    with open(FALLBACK_TARGET, 'r', encoding='utf-8') as f:
        html = f.read()
    i = html.find(FALLBACK_START)
    if i < 0:
        return False
    head = i + len(FALLBACK_START)
    # 用 json.JSONDecoder 从原文里切出完整的 JS 对象字面量
    try:
        _, end = json.JSONDecoder().raw_decode(html[head:])
    except ValueError:
        return False
    payload = json.dumps({"changelog": version_data.get("changelog", [])},
                        ensure_ascii=False, indent=4)
    new_html = html[:head] + payload + html[head + end:]
    if new_html != html:
        with open(FALLBACK_TARGET, 'w', encoding='utf-8') as f:
            f.write(new_html)
    return True


def _should_include(relative_path):
    relative_path = relative_path.replace(os.sep, "/")
    if relative_path in EXCLUDE_FILES:
        return False
    if relative_path in {"src/current_slot", "src/.hotreset",
                         "src/boot_manifest.json", "src/boot_manifest.sig",
                         "boot_manifest.json", "boot_manifest.sig"}:
        return False
    if relative_path.startswith("keys/") or "/keys/" in relative_path:
        return False
    return not relative_path.endswith(".pyc")


def _iter_payload_files():
    paths = []
    for base in ("src", "splibc"):
        if not os.path.exists(base):
            continue
        for root, dirs, files in os.walk(base):
            dirs[:] = sorted(d for d in dirs
                             if d not in EXCLUDE_DIRS
                             and not d.startswith('__pycache__'))
            for name in sorted(files):
                path = os.path.join(root, name)
                relative = path.replace(os.sep, "/")
                if _should_include(relative):
                    paths.append((path, relative))
    for name in ROOT_FILES:
        if os.path.isfile(name):
            paths.append((name, name))
    return sorted(paths, key=lambda item: item[1])


# 创建PySpOS更新包
def create_zip_file(version):
    create_date = datetime.now().strftime("%Y%m%d")
    zip_filename = f"PySpOS-{version}-{create_date}.zip"

    zip_path = os.path.join('docs', 'ota', zip_filename)
    os.makedirs(os.path.dirname(zip_path), exist_ok=True)
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for path, relative in _iter_payload_files():
            zipf.write(path, relative)
    return zip_path, zip_filename

# 计算文件的SHA256哈希值
def calculate_sha256(file_path):
    sha256_hash = hashlib.sha256()
    with open(file_path, 'rb') as f:
        # 分块读取文件以处理大文件
        for byte_block in iter(lambda: f.read(4096), b''):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

# 获取文件大小
def get_file_size(file_path):
    return os.path.getsize(file_path)

# 读取当前版本号
def get_current_version():
    version_path = os.path.join('src', 'version.txt')
    if os.path.exists(version_path):
        with open(version_path, 'r', encoding='utf-8') as f:
            return f.read().strip()
    return None

# 读取现有的version.json
def load_version_json():
    version_json_path = os.path.join('docs', 'ota', 'version.json')
    if os.path.exists(version_json_path):
        with open(version_json_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None

# 更新version.json文件
def update_version_json(zip_filename, file_size, sha256, version, release_notes,
                        stage=None, release_type=None, changes=None,
                        min_version=None, date=None, non_interactive=False,
                        security_version=None, signature_key_id=None):
    version_json_path = os.path.join('docs', 'ota', 'version.json')
    today = date or datetime.now().strftime("%Y-%m-%d")

    # 读取现有数据或创建新数据
    if os.path.exists(version_json_path):
        with open(version_json_path, 'r', encoding='utf-8') as f:
            version_data = json.load(f)
    else:
        version_data = {
            "version": version,
            "release_date": today,
            "develop_stage": stage or "beta",
            "release_notes": "",
            "download_url": "PySpOS.zip",
            "sha256": sha256,
            "min_version": "3.0.0",
            "file_size": file_size,
            "security_version": security_version,
            "signature_key_id": signature_key_id,
            "changelog": []
        }

    # 更新顶级信息
    version_data['version'] = version
    version_data['release_date'] = today
    version_data['release_notes'] = release_notes
    version_data['download_url'] = zip_filename
    version_data['sha256'] = sha256
    version_data['file_size'] = file_size
    if security_version is not None:
        version_data['security_version'] = security_version
    if signature_key_id is not None:
        version_data['signature_key_id'] = signature_key_id
    if stage:
        version_data['develop_stage'] = stage
    if min_version:
        version_data['min_version'] = min_version

    # 检查当前版本是否已在changelog中
    version_exists = False
    for entry in version_data['changelog']:
        if entry['version'] == version:
            version_exists = True
            # 重新构建时同步日期、类型与更新说明，否则网页上会留旧元数据
            entry['sha256'] = sha256
            entry['file_size'] = file_size
            entry['download_url'] = zip_filename
            entry['security_version'] = security_version
            entry['signature_key_id'] = signature_key_id
            entry['date'] = today
            if release_notes:
                entry['changes'] = (changes if changes
                                    else release_notes.split("\n"))
            if release_type:
                entry['type'] = release_type
            break

    # 如果版本不存在，添加新条目
    if not version_exists:
        if not changes:
            if non_interactive:
                print(f"\n当前版本 {version} 不在changelog中且未提供更新说明，"
                      "使用默认内容")
                changes = ["Bug 修复和性能优化"]
            else:
                print(f"\n当前版本 {version} 不在changelog中")
                print("请输入更新内容（每行一条，输入空行结束，或输入 'done' 结束）:")
                changes = []
                while True:
                    change = _ask("> ")
                    if not change or change.lower() == 'done':
                        break
                    changes.append(change)
                if not changes:
                    print("未输入更新内容，使用默认内容")
                    changes = ["Bug修复和性能优化"]

        if not release_type:
            if non_interactive:
                release_type = "beta"
            else:
                print("\n请选择版本类型:")
                print("1. beta (测试版)")
                print("2. release (正式版)")
                type_choice = _ask("> ")
                release_type = "beta" if type_choice != "2" else "release"

        # 创建新的changelog条目
        new_entry = {
            "version": version,
            "date": today,
            "type": release_type,
            "download_url": zip_filename,
            "sha256": sha256,
            "file_size": file_size,
            "security_version": security_version,
            "signature_key_id": signature_key_id,
            "changes": changes
        }

        # 添加到changelog开头
        version_data['changelog'].insert(0, new_entry)
        print(f"\n✓ 已将版本 {version} 添加到changelog")
    else:
        print(f"\n✓ 版本 {version} 已存在于changelog中，已更新SHA256和文件大小")

    # 写回文件
    with open(version_json_path, 'w', encoding='utf-8') as f:
        json.dump(version_data, f, ensure_ascii=False, indent=2)

    print(f"✓ 已更新 {version_json_path}")
    # 同步静态页里内嵌的兜底副本，避免 releases.html 长期停留在旧版本
    if sync_static_fallback(version_data):
        print(f"✓ 已同步 {FALLBACK_TARGET} 的静态兜底数据")
    else:
        print(f"- 跳过静态兜底同步（{FALLBACK_TARGET} 无 fallbackVersionData）")

# 主函数
def _ask(prompt, default=""):
    """交互读取；stdio 非 tty（CI / 管道）时直接返回默认值，绝不阻塞。"""
    import sys
    try:
        if not sys.stdin.isatty():
            print(f"{prompt}{default}  [非交互，使用默认值]")
            return default
    except Exception:
        return default
    try:
        v = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return default
    return v or default


def _parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="PySpOS 更新包构建工具（非交互模式供 CI/脚本使用）")
    p.add_argument("--version", help="构建指定版本号，缺省读 src/version.txt")
    p.add_argument("--stage", default="rc",
                   help="develop_stage 字段（beta/rc/release），缺省 rc")
    p.add_argument("--type", dest="release_type", default="beta",
                   help="changelog 条目 type（beta/rc/release），缺省 beta")
    p.add_argument("--note", action="append", default=[],
                   help="更新说明，可重复传入（每条一行）")
    p.add_argument("--min-version", default=None,
                   help="最低可升级版本，缺省沿用现有值或 3.0.0")
    p.add_argument("--date", help="发布日期 YYYY-MM-DD，缺省取今天（便于复现构建）")
    p.add_argument("--private-key", help="Ed25519 私钥 PEM；提供后生成签名 manifest")
    p.add_argument("--security-version", type=int, default=1,
                   help="manifest 的防回滚版本，缺省 1")
    p.add_argument("--quiet", action="store_true", help="只输出关键信息")
    return p.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
    non_interactive = bool(args.version or args.note or args.quiet
                           or args.date or args.min_version or args.stage
                           or args.private_key)

    def say(*a):
        if not args.quiet:
            print(*a)

    try:
        say("PySpOS 更新包构建工具")
        say("=" * 50)

        # 获取当前版本
        current_version = get_current_version()
        if not current_version:
            print("✗ 错误: 无法读取 src/version.txt")
            return 1

        say(f"当前版本: {current_version}")

        if args.version:
            build_version = args.version
            say(f"✓ 非交互模式，指定版本: {build_version}")
        else:
            # 询问是否是新版本更新
            say("\n这是新版本更新吗？")
            say("1. 是，我要发布新版本")
            say("2. 否，只是重新构建当前版本")
            is_new_version = _ask("> ")
            build_version = current_version
            if is_new_version in ("1", "yes", "y"):
                new_version = _ask("> ", build_version)
                build_version = new_version or current_version
            say(f"✓ 将构建版本: {build_version}")

        # 创建zip文件
        zip_path, zip_filename = create_zip_file(build_version)
        signed_manifest = None
        if args.private_key:
            signed_manifest = secure_boot.sign_package(
                zip_path, build_version, args.security_version, args.private_key)
            say(f"✓ 已生成 Ed25519 签名 manifest，security_version={args.security_version}")
        else:
            say("⚠ 未提供私钥：生成的是未签名开发包，锁定设备会拒绝启动")
        say(f"✓ 成功创建更新包: {zip_path}")

        # 获取文件大小
        file_size = get_file_size(zip_path)
        say(f"✓ 文件大小: {file_size} 字节")

        # 计算SHA256哈希值
        sha256 = calculate_sha256(zip_path)
        say(f"✓ SHA256: {sha256}")

        say("\n--- 更新包信息 ---\n")
        say(f"文件大小: {file_size} 字节")
        say(f"SHA256哈希: {sha256}")
        say(f"下载路径: {zip_filename}")

        # 获取更新说明
        if args.note:
            release_notes_list = list(args.note)
        else:
            say("\n请输入更新说明（可选，输入空行跳过）:")
            release_notes_list = []
            while True:
                line = _ask("> ")
                if not line:
                    break
                release_notes_list.append(line)
        release_notes_text = "\n".join(release_notes_list) if release_notes_list \
            else "PySpOS 更新包"

        # 更新version.json文件
        update_version_json(zip_filename, file_size, sha256, build_version,
                            release_notes_text,
                            stage=args.stage, release_type=args.release_type,
                            changes=release_notes_list,
                            min_version=args.min_version, date=args.date,
                            non_interactive=non_interactive,
                            security_version=(signed_manifest["security_version"]
                                               if signed_manifest else None),
                            signature_key_id=(signed_manifest["key_id"]
                                              if signed_manifest else None))

        say("\n✓ 构建完成\n")
        say("现在可以通过以下方式访问:")
        say(f"1. 本地测试: http://localhost:8000/ota/{zip_filename}")
        say(f"2. 直接下载: ota/{zip_filename}")
        say("\n在PySpOS中执行 'ota_update' 命令来安装更新")
        return 0

    except Exception as e:
        print(f"✗ 错误: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())