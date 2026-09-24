# PySpOS 更新包构建工具（ canonical 构建入口，2026-09-24 起统一）。
# 说明：历史上有两份构建脚本（根目录 build_update.py 与 src/calculate_zip_info.py），
# 现统一以本文件为准；src/calculate_zip_info.py 已改为弃用垫片，自动转发到本模块的 main()。
import os
import zipfile
import hashlib
import json
from datetime import datetime

# 排除的目录和文件
EXCLUDE_DIRS = {'docs', 'slot_a', 'slot_b', '__pycache__', 'etc', '.oldcode', '.git'}
EXCLUDE_FILES = {'.hotreset'}

# 创建PySpOS更新包
def create_zip_file(version):
    create_date = datetime.now().strftime("%Y%m%d")
    zip_filename = f"PySpOS-{version}-{create_date}.zip"
    
    zip_path = os.path.join('docs', 'ota', zip_filename)
    os.makedirs(os.path.dirname(zip_path), exist_ok=True)
    
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # 复制 src 目录
        for root, dirs, files in os.walk('src'):
            # 排除特定目录
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not d.startswith('__pycache__')]
            
            for file in files:
                if file in EXCLUDE_FILES or file.endswith('.pyc'):
                    continue
                file_path = os.path.join(root, file)
                arcname = file_path
                zipf.write(file_path, arcname)
        
        # 复制 splibc 目录
        if os.path.exists('splibc'):
            for root, dirs, files in os.walk('splibc'):
                dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not d.startswith('__pycache__')]
                for file in files:
                    if file in EXCLUDE_FILES or file.endswith('.pyc'):
                        continue
                    file_path = os.path.join(root, file)
                    arcname = file_path
                    zipf.write(file_path, arcname)
        
        # 复制根目录文件
        root_files = ['launcher.py', 'start.bat', 'start.sh', 'current_slot', 'build_update.py']
        for file in root_files:
            if os.path.exists(file):
                zipf.write(file, file)
    
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
def update_version_json(zip_filename, file_size, sha256, version, release_notes):
    version_json_path = os.path.join('docs', 'ota', 'version.json')
    
    # 读取现有数据或创建新数据
    if os.path.exists(version_json_path):
        with open(version_json_path, 'r', encoding='utf-8') as f:
            version_data = json.load(f)
    else:
        version_data = {
            "version": version,
            "release_date": datetime.now().strftime("%Y-%m-%d"),
            "develop_stage": "beta",
            "release_notes": "",
            "download_url": "PySpOS.zip",
            "sha256": sha256,
            "min_version": "3.0.0",
            "file_size": file_size,
            "changelog": []
        }
    
    # 更新顶级信息
    version_data['version'] = version
    version_data['release_date'] = datetime.now().strftime("%Y-%m-%d")
    version_data['release_notes'] = release_notes
    version_data['download_url'] = zip_filename
    version_data['sha256'] = sha256
    version_data['file_size'] = file_size
    
    # 检查当前版本是否已在changelog中
    version_exists = False
    for entry in version_data['changelog']:
        if entry['version'] == version:
            version_exists = True
            # 更新现有版本的SHA256和文件大小
            entry['sha256'] = sha256
            entry['file_size'] = file_size
            entry['download_url'] = zip_filename
            break
    
    # 如果版本不存在，添加新条目
    if not version_exists:
        print(f"\n当前版本 {version} 不在changelog中")
        print("请输入更新内容（每行一条，输入空行结束，或输入 'done' 结束）:")
        
        changes = []
        while True:
            change = input("> ").strip()
            if not change or change.lower() == 'done':
                break
            changes.append(change)
        
        if not changes:
            print("未输入更新内容，使用默认内容")
            changes = ["Bug修复和性能优化"]
        
        # 确定版本类型
        print("\n请选择版本类型:")
        print("1. beta (测试版)")
        print("2. release (正式版)")
        type_choice = input("> ").strip()
        version_type = "beta" if type_choice != "2" else "release"
        
        # 创建新的changelog条目
        new_entry = {
            "version": version,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "type": version_type,
            "download_url": zip_filename,
            "sha256": sha256,
            "file_size": file_size,
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

# 主函数
def main():
    try:
        print("PySpOS 更新包构建工具")
        print("=" * 50)
        
        # 获取当前版本
        current_version = get_current_version()
        if not current_version:
            print("✗ 错误: 无法读取 src/version.txt")
            return
        
        print(f"当前版本: {current_version}")
        
        # 询问是否是新版本更新
        print("\n这是新版本更新吗？")
        print("1. 是，我要发布新版本")
        print("2. 否，只是重新构建当前版本")
        is_new_version = input("> ").strip()
        
        build_version = current_version
        if is_new_version in("1","yes","y"):
            print("\n请输入新版本号（例如: 3.0.2 或 3.1.0）:")
            new_version = input("> ").strip()
            if new_version:
                build_version = new_version
                print(f"✓ 将构建新版本: {build_version}")
            else:
                print("✗ 未输入版本号，使用当前版本")
        else:
            print(f"✓ 将重新构建当前版本: {build_version}")
        
        # 创建zip文件
        zip_path, zip_filename = create_zip_file(build_version)
        print(f"✓ 成功创建更新包: {zip_path}")
        
        # 获取文件大小
        file_size = get_file_size(zip_path)
        print(f"✓ 文件大小: {file_size} 字节")
        
        # 计算SHA256哈希值
        sha256 = calculate_sha256(zip_path)
        print(f"✓ SHA256: {sha256}")
        
        # 输出结果，方便复制
        print("\n--- 更新包信息 ---\n")
        print(f'文件大小: {file_size} 字节')
        print(f'SHA256哈希: {sha256}')
        print(f'下载路径: {zip_filename}')
        
        # 获取更新说明
        print("\n请输入更新说明（可选，输入空行跳过）:")
        release_notes = []
        while True:
            line = input("> ").strip()
            if not line:
                break
            release_notes.append(line)
        
        release_notes_text = "\n".join(release_notes) if release_notes else "PySpOS 更新包"
        
        # 更新version.json文件
        update_version_json(zip_filename, file_size, sha256, build_version, release_notes_text)
        
        print("\n✓ 构建完成\n")
        print("现在可以通过以下方式访问:")
        print(f"1. 本地测试: http://localhost:8000/ota/{zip_filename}")
        print(f"2. 直接下载: ota/{zip_filename}")
        print("\n在PySpOS中执行 'ota_update' 命令来安装更新")
        
    except Exception as e:
        print(f"✗ 错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()