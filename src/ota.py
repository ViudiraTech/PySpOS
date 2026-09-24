#   
#   ota.py
#   PySpOS OTA更新以及槽位模块
#
#   By GoutouStdio
#   @2022~2026 GoutouStdio. Open all rights.

import os
import shutil
import zipfile
import time
import printk
import logk
from pathlib import Path
import json
import urllib.request
import urllib.error
import hashlib
import platform
import re

# 获取启动时间
boot_time = logk.get_boot_time()

# 获取根目录（ota.py所在目录的父目录）
# 统一走 common.paths，失败时回退到历史逻辑。
script_dir = os.path.dirname(os.path.abspath(__file__))
try:
    from common.paths import get_root_dir as _get_root_dir
    root_dir = _get_root_dir(script_dir)
except Exception:
    if os.path.basename(script_dir) == 'src':
        # 在src目录中，根目录是src的父目录
        root_dir = os.path.dirname(script_dir)
    elif os.path.basename(script_dir) in ['slot_a', 'slot_b']:
        # 在槽位目录中，根目录是槽位的父目录
        root_dir = os.path.dirname(script_dir)
    else:
        # 其他情况，使用当前目录作为根目录
        root_dir = script_dir

# 槽位定义
SLOT_A = "slot_a"                           # 槽位A
SLOT_B = "slot_b"                           # 槽位B
CURRENT_SLOT_FILE = os.path.join(root_dir, "current_slot")          # 当前槽位记录文件

# 更新包相关配置
OTA_PACKAGE_DIR = os.path.join(root_dir, "ota")                     # 更新包存放目录
OTA_PACKAGE_NAME = "update.zip"             # 更新包文件名
VERSION_FILE = "version.txt"                # 版本信息文件名
UPDATE_LOG = "update_log.json"              # 更新日志文件名

# 云端更新服务器配置
OTA_SERVER_URL = "https://pyspos.us.ci/ota/" # 更新服务器域名
REMOTE_VERSION_FILE = "version.json"        # 云端版本信息文件名
REMOTE_UPDATE_FILE = "PySpOS.zip"           # 云端更新包文件名

# OTA 总开关（服务器故障时临时禁用云端更新，本地安装/回滚不受影响）。
# 开关定义在 pyspos.py，恢复服务时改回 True 即可。ota.py 文件本身保留。
def _ota_enabled() -> bool:
    try:
        import pyspos as _pyspos
        return bool(getattr(_pyspos, "OTA_ENABLED", True))
    except Exception:
        return True

def _ota_disable_reason() -> str:
    try:
        import pyspos as _pyspos
        return str(getattr(_pyspos, "OTA_DISABLE_REASON", "OTA 已临时禁用"))
    except Exception:
        return "OTA 已临时禁用"

def is_ota_enabled() -> bool:
    """对外查询：云端 OTA 是否可用（供 main/recovery 打印友好提示）。"""
    return _ota_enabled()

# 必要的文件
REQUIRED_CORE_FILES = [
    "kernel.py", "main.py", "fs.py", "printk.py", "logk.py", 
    "recovery.py", "ota.py", "btcfg.py", "pyspos.py", "parse_spf.py",
    "version.txt", "current_slot", "launcher.py"
]

# 必要的文件夹
REQUIRED_DIRS = ["apps", "spfapps"]

# 版本比较函数
def compare_versions(v1: str, v2: str) -> int:
    try:
        # 分离版本号和后缀
        def parse_version(version: str):
            # 处理版本后缀（这些格式都放到pyspos.py中）
            suffix_map = {
                'pre': -3,
                'alpha': -2,
                'beta': -1,
                'rc': 0,
            }
            
            # 移除版本号中的额外文本（如"(重构建)"）
            clean_version = version.split('(')[0].strip()
            
            # 检查是否有后缀
            for suffix, weight in suffix_map.items():
                if suffix in clean_version.lower():
                    # 提取基础版本号
                    base_version = clean_version.lower().split(suffix)[0].rstrip('-')
                    # 转换为数字列表
                    parts = list(map(int, base_version.split('.')))
                    # 添加后缀权重作为最后一位
                    parts.append(weight)
                    return parts
            
            # 没有后缀，视为正式版，权重为1
            parts = list(map(int, clean_version.split('.')))
            parts.append(1)
            return parts
        
        parts1 = parse_version(v1)
        parts2 = parse_version(v2)
        
        # 确保长度一致
        max_len = max(len(parts1), len(parts2))
        parts1.extend([0] * (max_len - len(parts1)))
        parts2.extend([0] * (max_len - len(parts2)))
        
        # 逐位比较
        for p1, p2 in zip(parts1, parts2):
            if p1 > p2:
                return 1
            elif p1 < p2:
                return -1
        return 0
    except Exception as e:
        logk.printl("ota", f"版本比较失败: {e}", boot_time)
        return 0

# 从云端获取最新版本信息
def fetch_remote_version() -> dict:
    if not _ota_enabled():
        logk.printl("ota", f"云端更新已禁用: {_ota_disable_reason()}（未发起网络请求）", boot_time)
        return None
    max_retries = 3
    retry_interval = 1
    
    logk.printl("ota", "检查更新...", boot_time)
    
    methods = [
        ("requests", _fetch_with_requests),
        ("urllib", _fetch_with_urllib),
        ("curl", _fetch_with_curl),
    ]
    
    for method_name, method_func in methods:
        logk.printl("ota", f"使用 {method_name} 获取版本", boot_time)
        for attempt in range(max_retries):
            try:
                url = OTA_SERVER_URL + REMOTE_VERSION_FILE
                logk.printl("ota", f"连接服务器 ({attempt + 1}/{max_retries})", boot_time)
                
                start_time = time.time()
                data = method_func(url)
                end_time = time.time()
                
                response_size = len(str(data))
                logk.printl("ota", f"获取版本耗时: {end_time - start_time:.2f}秒, 大小: {response_size} bytes", boot_time)
                
                if data:
                    logk.printl("ota", f"{method_name} 获取成功", boot_time)
                    return data
            except Exception as e:
                logk.printl("ota", f"{method_name} 错误: {e}", boot_time)
                if attempt < max_retries - 1:
                    logk.printl("ota", f"{retry_interval}秒后重试", boot_time)
                    time.sleep(retry_interval)
                else:
                    logk.printl("ota", f"{method_name} 重试失败", boot_time)
                    break
    
    logk.printl("ota", "网络失败，使用本地版本", boot_time)
    local_version_file = os.path.join("docs", "ota", "version.json")
    if os.path.exists(local_version_file):
        try:
            with open(local_version_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            logk.printl("ota", "加载本地版本成功", boot_time)
            return data
        except Exception as e:
            logk.printl("ota", f"加载本地版本失败: {e}", boot_time)
            return None
    else:
        logk.printl("ota", "本地版本文件不存在", boot_time)
        return None

# 使用requests库获取云端文件
def _fetch_with_requests(url: str) -> dict:
    try:
        import requests as _requests
        logk.printl("ota", f"requests 版本: {_requests.__version__}", boot_time)
        session = _requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Referer': 'https://pyspos.us.ci/',
            'Cache-Control': 'max-age=0'
        })
        response = session.get(url, timeout=15, allow_redirects=True)
        response.raise_for_status()
        return response.json()
    except ImportError as e:
        import sys
        logk.printl("ota", f"Python 路径: {sys.executable}", boot_time)
        logk.printl("ota", f"sys.path: {sys.path[:3]}...", boot_time)
        raise Exception(f"requests库未安装: {e}")
    except Exception as e:
        raise

# 使用urllib获取云端文件
def _fetch_with_urllib(url: str) -> dict:
    import urllib.request
    import gzip
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Connection': 'keep-alive',
        'Referer': 'https://pyspos.us.ci/',
        'Cache-Control': 'max-age=0'
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as response:
        raw_data = response.read()
        # 检查是否是 gzip 压缩
        if raw_data[:2] == b'\x1f\x8b':
            raw_data = gzip.decompress(raw_data)
        data = json.loads(raw_data.decode('utf-8'))
        return data

# 使用curl命令获取云端文件
def _fetch_with_curl(url: str) -> dict:
    import subprocess
    import json
    result = subprocess.run(
        [
            'curl', '-s', '-L',
            '-H', 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            '-H', 'Accept: application/json, text/plain, */*',
            '-H', 'Accept-Language: zh-CN,zh;q=0.9,en;q=0.8',
            '-H', 'Connection: keep-alive',
            '-H', 'Referer: https://pyspos.us.ci/',
            '-H', 'Cache-Control: max-age=0',
            '--compressed',
            url
        ],
        capture_output=True,
        timeout=15
    )
    if result.returncode == 0:
        return json.loads(result.stdout.decode('utf-8'))
    else:
        raise Exception(f"curl命令失败: {result.stderr.decode('utf-8', errors='ignore')}")

# 下载更新包
def download_update_package(remote_url: str, local_path: str, expected_size: int = 0) -> bool:
    if not _ota_enabled():
        logk.printl("ota", f"云端更新已禁用: {_ota_disable_reason()}（跳过下载 {remote_url}）", boot_time)
        return False
    try:
        if os.path.exists(local_path):
            local_size = os.path.getsize(local_path)
            if expected_size > 0 and local_size == expected_size:
                logk.printl("ota", f"本地已存在相同大小的更新包，跳过下载", boot_time)
                return True
            elif local_size > 0:
                logk.printl("ota", f"本地已存在更新包 ({local_size} bytes)", boot_time)
        
        logk.printl("ota", f"下载更新包: {remote_url}", boot_time)
        
        start_time = time.time()
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': '*/*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Connection': 'keep-alive',
            'Referer': 'https://pyspos.us.ci/',
            'Cache-Control': 'max-age=0'
        }
        req = urllib.request.Request(remote_url, headers=headers)
        
        with urllib.request.urlopen(req, timeout=60) as response:
            total_size = int(response.headers.get('Content-Length', 0))
            downloaded = 0
            chunk_size = 8192
            
            with open(local_path, 'wb') as f:
                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    
                    if total_size > 0:
                        percent = min(100, (downloaded / total_size) * 100)
                        if int(percent) % 5 == 0:
                            print(f"\r下载进度: {percent:.1f}% ({downloaded}/{total_size} bytes)", end='', flush=True)
                    else:
                        print(f"\r已下载: {downloaded} bytes", end='', flush=True)
        
        print()
        end_time = time.time()
        
        if os.path.exists(local_path):
            file_size = os.path.getsize(local_path)
            logk.printl("ota", f"下载完成,耗时: {end_time - start_time:.2f}秒, 大小: {file_size} bytes", boot_time)
        else:
            logk.printl("ota", f"下载完成,耗时: {end_time - start_time:.2f}秒", boot_time)
        
        return True
    except urllib.error.URLError as e:
        logk.printl("ota", f"下载失败: {e}", boot_time)
        return False
    except Exception as e:
        logk.printl("ota", f"下载错误: {e}", boot_time)
        return False

# 验证更新包完整性
def verify_update_package(package_path: str, expected_hash: str = None) -> bool:
    try:
        if expected_hash:
            logk.printl("ota", "验证更新包", boot_time)
            sha256_hash = hashlib.sha256()
            
            start_time = time.time()
            with open(package_path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    sha256_hash.update(chunk)
            calculated_hash = sha256_hash.hexdigest()
            end_time = time.time()
            
            logk.printl("ota", f"验证耗时: {end_time - start_time:.2f}秒", boot_time)
            
            if calculated_hash == expected_hash:
                logk.printl("ota", "验证通过", boot_time)
                return True
            else:
                logk.printl("ota", "校验和不匹配", boot_time)
                return False
        else:
            logk.printl("ota", "跳过验证", boot_time)
            return True
    except Exception as e:
        logk.printl("ota", f"验证失败: {e}", boot_time)
        return False

# 获取当前的槽位
def get_current_slot() -> str:
    if os.path.exists(CURRENT_SLOT_FILE):
        with open(CURRENT_SLOT_FILE, 'r') as f:
            slot = f.read().strip()
            if slot in [SLOT_A, SLOT_B]:
                return slot
    # 如果没有，默认使用槽位_A
    set_current_slot(SLOT_A)
    return SLOT_A

# 设置激活的槽位
def set_current_slot(slot: str) -> None:
    if slot in [SLOT_A, SLOT_B]:
        with open(CURRENT_SLOT_FILE, 'w') as f:
            f.write(slot)
        logk.printl("ota", f"已设置当前槽位为: {slot}", boot_time)

# 获取其他槽位
def get_other_slot() -> str:
    return SLOT_B if get_current_slot() == SLOT_A else SLOT_A

# 验证更新包
def verify_update_compatibility() -> bool:
    current_ver = get_current_version()
    update_ver = get_update_version()
    
    comparison = compare_versions(update_ver, current_ver)
    if comparison > 0:
        return True
    elif comparison == 0:
        logk.printl("ota", "更新包版本与当前版本相同", boot_time)
        return False
    else:
        logk.printl("ota", "更新包版本低于当前版本", boot_time)
        return False

# 从云端检查更新
def check_cloud_update() -> dict:
    if not _ota_enabled():
        logk.printl("ota", f"云端更新已禁用: {_ota_disable_reason()}", boot_time)
        try:
            current_ver = get_current_version()
        except Exception:
            current_ver = "unknown"
        return {
            'has_update': False,
            'disabled': True,
            'reason': _ota_disable_reason(),
            'current_version': current_ver,
            'remote_version': current_ver,
        }
    logk.printl("ota", "检查云端更新", boot_time)
    remote_info = fetch_remote_version()
    if not remote_info:
        logk.printl("ota", "获取云端版本失败", boot_time)
        return None
    
    current_ver = get_current_version()
    remote_ver = remote_info.get('version', '0.0.0')
    
    logk.printl("ota", f"当前: {current_ver}, 云端: {remote_ver}", boot_time)
    comparison = compare_versions(remote_ver, current_ver)
    
    if comparison > 0:
        logk.printl("ota", f"发现新版本: {remote_ver}", boot_time)
        # 处理下载URL，确保是完整的URL
        download_url = remote_info.get('download_url', OTA_SERVER_URL + REMOTE_UPDATE_FILE)
        
        # 判断是否是重构版（文件名格式为PySpOS-版本-日期.zip）
        is_rebuild = download_url and re.match(r'PySpOS-[\d.]+-[\d]+\.zip', download_url)
        
        # 如果是相对路径，转换为完整URL
        if not download_url.startswith('http://') and not download_url.startswith('https://'):
            download_url = OTA_SERVER_URL + download_url
        
        return {
            'has_update': True,
            'current_version': current_ver,
            'remote_version': remote_ver,
            'download_url': download_url,
            'is_rebuild': bool(is_rebuild),
            'sha256': remote_info.get('sha256'),
            'file_size': remote_info.get('file_size', 0),
            'release_notes': remote_info.get('release_notes', '')
        }
    else:
        logk.printl("ota", "已是最新版本", boot_time)
        return {
            'has_update': False,
            'current_version': current_ver,
            'remote_version': remote_ver
        }

# 从云端下载并安装更新
def download_and_install_update() -> bool:
    if not _ota_enabled():
        logk.printl("ota", f"云端更新已禁用: {_ota_disable_reason()}", boot_time)
        printk.error(f"OTA 已临时禁用: {_ota_disable_reason()}\n本地安装/回滚不受影响。\n")
        return False
    update_info = check_cloud_update()
    if not update_info or not update_info['has_update']:
        logk.printl("ota", "无可用更新", boot_time)
        return False
    
    if not printk.confirm(f"是否下载并安装版本 {update_info['remote_version']}？"):
        return False
    
    os.makedirs(OTA_PACKAGE_DIR, exist_ok=True)
    
    # 判断是否是重构版，使用对应的文件名
    is_rebuild = update_info.get('is_rebuild', False)
    if is_rebuild:
        # 如果是重构版，使用version.json中的文件名
        package_name = update_info['download_url'].split('/')[-1]
        logk.printl("ota", f"检测到重构版/新版格式，使用文件名: {package_name}", boot_time)
    else:
        # 否则使用默认的update.zip
        package_name = OTA_PACKAGE_NAME
    
    package_path = os.path.join(OTA_PACKAGE_DIR, package_name)
    
    if not download_update_package(update_info['download_url'], package_path, update_info.get('file_size', 0)):
        return False
    
    if not verify_update_package(package_path, update_info.get('sha256')):
        return False
    
    if not install_update():
        return False
    
    # 安装成功后，切换到新槽位
    if not switch_slot():
        logk.printl("ota", "切换槽位失败", boot_time)
        return False
    
    # 清除更新包
    if cleanup_update_package():
        logk.printl("ota", "更新包已清除", boot_time)
    else:
        logk.printl("ota", "更新包清除失败", boot_time)
    
    logk.printl("ota", "更新已安装，正在重启系统...", boot_time)
    
    # 重启系统
    restart_system()
    return True

# 重启系统
def restart_system() -> None:
    import subprocess
    import sys
    
    try:
        python_exe = sys.executable
        
        launcher_py = os.path.join(root_dir, "launcher.py")
        
        if os.path.exists(launcher_py):
            subprocess.Popen([python_exe, launcher_py], cwd=root_dir)
        else:
            slot = get_current_slot()
            slot_main = os.path.join(root_dir, slot, "main.py")
            subprocess.Popen([python_exe, slot_main], cwd=os.path.join(root_dir, slot))
        
        import time
        time.sleep(0.5)
        
        sys.exit(0)
    except Exception as e:
        logk.printl("ota", f"重启失败: {str(e)}", boot_time)
        printk.error("重启失败，请手动重新启动系统\n")

# 清空槽位目录（Windows 先 move 到临时目录再后台删除，避免文件占用；类 Unix 直接删除）。
# 抽取自 install_update / rollback_update 的重复实现（2026-09-24 去重）。
def _reset_slot_dir(slot_path: str, purpose: str) -> bool:
    import tempfile
    import uuid
    if not os.path.exists(slot_path):
        return True
    try:
        if platform.system() == 'Windows':
            temp_dir = os.path.join(tempfile.gettempdir(), f"pyspos_{purpose}_{uuid.uuid4().hex[:8]}")
            try:
                logk.printl("ota", f"移动槽位到临时目录: {temp_dir}", boot_time)
                shutil.move(slot_path, temp_dir)
                os.makedirs(slot_path, exist_ok=True)

                def _delete_temp_dir():
                    try:
                        time.sleep(2)  # 等待文件释放
                        if os.path.exists(temp_dir):
                            shutil.rmtree(temp_dir, ignore_errors=True)
                    except Exception:
                        pass

                import threading
                threading.Thread(target=_delete_temp_dir, daemon=True).start()
            except Exception as e:
                logk.printl("ota", f"移动槽位失败: {str(e)}", boot_time)
                try:
                    shutil.rmtree(slot_path, ignore_errors=True)
                    os.makedirs(slot_path, exist_ok=True)
                except Exception as e2:
                    logk.printl("ota", f"删除槽位也失败: {str(e2)}", boot_time)
                    return False
        else:
            shutil.rmtree(slot_path)
            os.makedirs(slot_path, exist_ok=True)
            logk.printl("ota", f"已清空槽位 {slot_path}", boot_time)
        return True
    except Exception as e:
        logk.printl("ota", f"清空槽位失败: {str(e)}", boot_time)
        return False


def _slot_is_ready(slot_path: str) -> bool:
    """槽位是否已包含运行所需的核心文件/目录（用于 ota_init 惰性同步）。"""
    for file in REQUIRED_CORE_FILES:
        if not os.path.exists(os.path.join(slot_path, file)):
            return False
    for directory in REQUIRED_DIRS:
        if not os.path.exists(os.path.join(slot_path, directory)):
            return False
    return True


# 回滚到上一个版本
def rollback_update() -> bool:
    current = get_current_slot()
    other = get_other_slot()
    
    logk.printl("ota", f"当前槽位: {current} ({get_version(current)})", boot_time)
    logk.printl("ota", f"目标槽位: {other} ({get_version(other)})", boot_time)
    
    if not printk.confirm("是否回滚到上一个版本？"):
        return False
    
    # 获取旧版本信息
    old_version = get_version(other)
    
    # 舍弃新版本的槽位：删除当前槽位的内容
    current_slot_path = os.path.join(root_dir, current)
    if os.path.exists(current_slot_path):
        if not _reset_slot_dir(current_slot_path, "rollback"):
            logk.printl("ota", "删除新版本槽位失败", boot_time)
            return False
    
    # 从旧版本槽位复制核心文件到新创建的空槽位
    other_slot_path = os.path.join(root_dir, other)
    
    try:
        # 复制核心文件
        for file in REQUIRED_CORE_FILES:
            source_file = os.path.join(other_slot_path, file)
            if os.path.exists(source_file):
                dest_file = os.path.join(current_slot_path, file)
                shutil.copy2(source_file, dest_file)
        
        # 复制必要的文件夹
        for directory in REQUIRED_DIRS:
            source_dir = os.path.join(other_slot_path, directory)
            dest_dir = os.path.join(current_slot_path, directory)
            if os.path.exists(source_dir):
                if os.path.exists(dest_dir):
                    shutil.rmtree(dest_dir)
                shutil.copytree(source_dir, dest_dir)
        
        logk.printl("ota", f"已从旧版本槽位复制文件到: {current}", boot_time)
    except Exception as e:
        logk.printl("ota", f"复制旧版本文件失败: {str(e)}", boot_time)
        return False
    
    # 更新更新日志
    try:
        log_path = os.path.join(current_slot_path, UPDATE_LOG)
        log_data = {
            "from_version": get_version(other),
            "to_version": old_version,
            "install_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "action": "rollback"
        }
        with open(log_path, 'w') as f:
            json.dump(log_data, f, indent=2)
        logk.printl("ota", "回滚日志已记录", boot_time)
    except Exception as e:
        logk.printl("ota", f"记录回滚日志失败: {str(e)}", boot_time)
    
    logk.printl("ota", "回滚成功，重启后生效", boot_time)
    return True

# 查看更新历史
def view_update_history() -> None:
    for slot in [SLOT_A, SLOT_B]:
        log_path = os.path.join(slot, UPDATE_LOG)
        if os.path.exists(log_path):
            try:
                with open(log_path, 'r') as f:
                    log_data = json.load(f)
                print(f"\n{slot} 更新历史:")
                print(f"  从版本: {log_data.get('from_version', '未知')}")
                print(f"  到版本: {log_data.get('to_version', '未知')}")
                print(f"  安装时间: {log_data.get('install_time', '未知')}")
            except Exception as e:
                logk.printl("ota", f"读取更新历史失败: {e}", boot_time)
        else:
            print(f"\n{slot} 无更新历史")

# 检查是否有更新（这个以后可以抓取云端内容检查）
def check_for_update() -> bool:
    # 首先检查默认的更新包
    package_path = os.path.join(OTA_PACKAGE_DIR, OTA_PACKAGE_NAME)
    if os.path.exists(package_path) and os.path.isfile(package_path):
        return True
    
    # 如果默认更新包不存在，检查是否有其他zip文件（如重构版）
    if os.path.exists(OTA_PACKAGE_DIR):
        try:
            for filename in os.listdir(OTA_PACKAGE_DIR):
                if filename.endswith('.zip'):
                    return True
        except Exception as e:
            logk.printl("ota", f"检查更新包失败: {str(e)}", boot_time)
    
    return False

# 清除更新包
def cleanup_update_package() -> bool:
    # 首先尝试删除默认的更新包
    package_path = os.path.join(OTA_PACKAGE_DIR, OTA_PACKAGE_NAME)
    deleted = False
    
    try:
        if os.path.exists(package_path):
            os.remove(package_path)
            logk.printl("ota", f"已删除更新包: {package_path}", boot_time)
            deleted = True
    except Exception as e:
        logk.printl("ota", f"删除更新包失败: {str(e)}", boot_time)
    
    # 如果默认更新包不存在，尝试删除其他zip文件（如重构版）
    if not deleted and os.path.exists(OTA_PACKAGE_DIR):
        try:
            for filename in os.listdir(OTA_PACKAGE_DIR):
                if filename.endswith('.zip'):
                    package_path = os.path.join(OTA_PACKAGE_DIR, filename)
                    os.remove(package_path)
                    logk.printl("ota", f"已删除更新包: {package_path}", boot_time)
                    deleted = True
                    break
        except Exception as e:
            logk.printl("ota", f"删除更新包失败: {str(e)}", boot_time)
    
    # 尝试删除整个ota目录（如果为空）
    try:
        if os.path.exists(OTA_PACKAGE_DIR) and not os.listdir(OTA_PACKAGE_DIR):
            os.rmdir(OTA_PACKAGE_DIR)
            logk.printl("ota", "已删除空的ota目录", boot_time)
    except Exception:
        pass  # 忽略删除目录的错误
    
    return deleted

# 获取指定槽位里的PySpOS版本
def get_version(slot: str) -> str:
    slot_path = os.path.join(root_dir, slot)
    version_path = os.path.join(slot_path, VERSION_FILE)
    if os.path.exists(version_path):
        with open(version_path, 'r') as f:
            return f.read().strip()
    return "未知版本"

# 获取当前槽位里PySpOS版本
def get_current_version() -> str:
    # 首先尝试从当前槽位的version.txt文件中读取版本信息
    current_slot = get_current_slot()
    slot_path = os.path.join(root_dir, current_slot)
    slot_version_path = os.path.join(slot_path, VERSION_FILE)
    
    if os.path.exists(slot_version_path):
        try:
            with open(slot_version_path, 'r') as f:
                return f.read().strip()
        except Exception as e:
            logk.printl("ota", f"读取槽位版本文件失败: {e}", boot_time)
    
    # 如果槽位版本文件不存在，尝试从根目录读取
    root_version_file = os.path.join(root_dir, "version.txt")
    if os.path.exists(root_version_file):
        try:
            with open(root_version_file, 'r') as f:
                return f.read().strip()
        except Exception as e:
            logk.printl("ota", f"读取根目录版本文件失败: {e}", boot_time)
    
    # 如果都失败了，返回一个默认版本
    return "3.0.0"

# 获取更新包版本
def get_update_version() -> str:
    package_path = os.path.join(OTA_PACKAGE_DIR, OTA_PACKAGE_NAME)
    
    if not os.path.exists(package_path):
        try:
            for filename in os.listdir(OTA_PACKAGE_DIR):
                if filename.endswith('.zip'):
                    package_path = os.path.join(OTA_PACKAGE_DIR, filename)
                    break
        except Exception as e:
            logk.printl("ota", f"查找更新包失败: {str(e)}", boot_time)
    
    try:
        with zipfile.ZipFile(package_path, 'r') as zip_ref:
            possible_paths = [VERSION_FILE, f'src/{VERSION_FILE}']
            for path in possible_paths:
                if path in zip_ref.namelist():
                    with zip_ref.open(path) as f:
                        return f.read().decode().strip()
            logk.printl("ota", f"更新包中未找到版本文件", boot_time)
    except Exception as e:
        logk.printl("ota", f"读取更新包版本失败: {str(e)}", boot_time)
    return "未知版本"

# 将更新包安装到另一槽位
def install_update() -> bool:
    if not check_for_update():
        logk.printl("ota", "未找到更新包", boot_time)
        return False
    
    if not verify_update_compatibility():
        logk.printl("ota", "版本不兼容", boot_time)
        return False
    
    # 查找更新包（support do重构版）
    package_path = os.path.join(OTA_PACKAGE_DIR, OTA_PACKAGE_NAME)
    if not os.path.exists(package_path):
        # 查找OTA_PACKAGE_DIR中的所有zip文件
        try:
            for filename in os.listdir(OTA_PACKAGE_DIR):
                if filename.endswith('.zip'):
                    package_path = os.path.join(OTA_PACKAGE_DIR, filename)
                    logk.printl("ota", f"找到更新包: {filename}", boot_time)
                    break
        except Exception as e:
            logk.printl("ota", f"查找更新包失败: {str(e)}", boot_time)
    
    target_slot = os.path.join(root_dir, get_other_slot())
    current_ver = get_current_version()
    update_ver = get_update_version()
    
    logk.printl("ota", f"安装更新: {current_ver} -> {update_ver}", boot_time)
    logk.printl("ota", f"目标槽位: {target_slot}", boot_time)
    
    start_time = time.time()
    
    # 清空目标槽位（Windows 先 move 再后台删除，见 _reset_slot_dir）
    if os.path.exists(target_slot):
        if not _reset_slot_dir(target_slot, "install"):
            return False
    
    os.makedirs(target_slot, exist_ok=True)
    
    try:
        with zipfile.ZipFile(package_path, 'r') as zip_ref:
            namelist = zip_ref.namelist()
            has_src_prefix = any(n.startswith('src/') for n in namelist)
            
            for member in namelist:
                if member.endswith('/'):
                    continue
                
                if has_src_prefix and member.startswith('src/'):
                    target_path = os.path.join(target_slot, member[4:])
                else:
                    target_path = os.path.join(target_slot, member)
                
                os.makedirs(os.path.dirname(target_path), exist_ok=True)
                with zip_ref.open(member) as src, open(target_path, 'wb') as dst:
                    dst.write(src.read())
        
        logk.printl("ota", "解压完成", boot_time)
    except Exception as e:
        logk.printl("ota", f"解压失败: {str(e)}", boot_time)
        return False
    
    # 从根目录复制etc到目标槽位（这个用于保留数据）
    etc_source = os.path.join(root_dir, "etc")
    etc_target = os.path.join(target_slot, "etc")
    if os.path.exists(etc_source):
        try:
            if os.path.exists(etc_target):
                shutil.rmtree(etc_target)
            shutil.copytree(etc_source, etc_target)
            logk.printl("ota", "已复制 etc 目录", boot_time)
        except Exception as e:
            logk.printl("ota", f"复制 etc 目录失败: {str(e)}", boot_time)
            return False
    
    try:
        log_path = os.path.join(target_slot, UPDATE_LOG)
        log_data = {
            "from_version": current_ver,
            "to_version": update_ver,
            "install_time": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        with open(log_path, 'w') as f:
            json.dump(log_data, f, indent=2)
        logk.printl("ota", "日志已记录", boot_time)
    except Exception as e:
        logk.printl("ota", f"记录日志失败: {str(e)}", boot_time)
    
    # 确保version.txt文件存在
    version_path = os.path.join(target_slot, VERSION_FILE)
    if not os.path.exists(version_path):
        try:
            with open(version_path, 'w') as f:
                f.write(update_ver)
            logk.printl("ota", f"已创建版本文件: {version_path}", boot_time)
        except Exception as e:
            logk.printl("ota", f"创建版本文件失败: {str(e)}", boot_time)
    
    end_time = time.time()
    logk.printl("ota", f"安装完成: {end_time - start_time:.2f}秒", boot_time)
    
    # 清除更新包
    try:
        if os.path.exists(package_path):
            os.remove(package_path)
            logk.printl("ota", "已删除更新包文件", boot_time)
    except Exception as e:
        logk.printl("ota", f"删除更新包失败: {str(e)}", boot_time)
    
    return True

# 切换槽位
def switch_slot() -> bool:
    current = get_current_slot()
    target = get_other_slot()
    target_path = os.path.join(root_dir, target)
    
    # 检查目标槽位是否有效
    valid = True
    missing_items = []
    
    # 检查核心文件
    for file in REQUIRED_CORE_FILES:
        if not os.path.exists(os.path.join(target_path, file)):
            missing_items.append(file)
            valid = False
    
    # 检查必要的文件夹
    for directory in REQUIRED_DIRS:
        if not os.path.exists(os.path.join(target_path, directory)):
            missing_items.append(directory)
            valid = False
    
    if not valid:
        logk.printl("ota", f"槽位切换失败：目标槽位 {target} 缺少: {', '.join(missing_items)}", boot_time)
        return False
    
    set_current_slot(target)
    logk.printl("ota", f"槽位已切换至 {target}", boot_time)
    logk.printl("ota", "请重启系统以加载新槽位的系统文件", boot_time)
    logk.printl("ota", "使用 start.bat (Windows) 或 start.sh (Linux/Mac) 启动系统", boot_time)
    return True

# 获取OTA更新状态
def get_ota_status() -> dict:
    return {
        "ota_enabled": _ota_enabled(),
        "ota_disable_reason": (None if _ota_enabled() else _ota_disable_reason()),
        "current_slot": get_current_slot(),
        "current_version": get_current_version(),
        "other_slot": get_other_slot(),
        "other_version": get_version(get_other_slot()),
        "has_update": check_for_update(),
        "update_version": get_update_version() if check_for_update() else None
    }

# 清理更新包文件
def clean_update_package() -> None:
    package_path = os.path.join(OTA_PACKAGE_DIR, OTA_PACKAGE_NAME)
    if os.path.exists(package_path):
        try:
            os.remove(package_path)
            logk.printl("ota", "已删除更新包文件", boot_time)
        except Exception as e:
            logk.printl("ota", f"删除更新包失败: {str(e)}", boot_time)
    else:
        logk.printl("ota", "无更新包可清理", boot_time)

# 初始化OTA
def ota_init() -> bool:
    logk.printl("ota", "正在初始化OTA槽位结构...", boot_time)
    
    # 创建槽位文件夹（在根目录）
    slots = [SLOT_A, SLOT_B]
    for slot in slots:
        slot_path = os.path.join(root_dir, slot)
        if not os.path.exists(slot_path):
            try:
                os.makedirs(slot_path)
                logk.printl("ota", f"创建槽位文件夹 {slot} 成功", boot_time)
            except Exception as e:
                logk.printl("ota", f"创建槽位文件夹 {slot} 失败: {str(e)}", boot_time)
                return False
        else:
            logk.printl("ota", f"槽位文件夹 {slot} 已存在", boot_time)
    
    # 确保当前槽位文件存在
    if not os.path.exists(CURRENT_SLOT_FILE):
        try:
            set_current_slot(SLOT_A)
            logk.printl("ota", "设置默认当前槽位为 SLOT_A", boot_time)
        except Exception as e:
            logk.printl("ota", f"设置当前槽位失败: {str(e)}", boot_time)
            return False
    else:
        current_slot = get_current_slot()
        logk.printl("ota", f"当前槽位已设置为: {current_slot}", boot_time)
    
    # 确保版本文件存在（在src目录）
    src_version_file = os.path.join(script_dir, "version.txt")
    if not os.path.exists(src_version_file):
        try:
            with open(src_version_file, "w") as f:
                f.write("3.0.0")
            logk.printl("ota", "创建版本文件 version.txt 成功", boot_time)
        except Exception as e:
            logk.printl("ota", f"创建版本文件失败: {str(e)}", boot_time)
            return False
    else:
        logk.printl("ota", "版本文件 version.txt 已存在", boot_time)
    
    # 复制src目录文件到当前槽位（惰性同步：槽位已就绪则跳过，避免每次启动全量复制）
    current_slot = get_current_slot()
    current_slot_path = os.path.join(root_dir, current_slot)

    # 确保槽位目录存在
    if not os.path.exists(current_slot_path):
        try:
            os.makedirs(current_slot_path, exist_ok=True)
            logk.printl("ota", f"创建槽位目录 {current_slot_path} 成功", boot_time)
        except Exception as e:
            logk.printl("ota", f"创建槽位目录失败: {str(e)}", boot_time)
            return False

    if _slot_is_ready(current_slot_path) and os.environ.get("PYSPOS_FORCE_SLOT_SYNC") != "1":
        logk.printl("ota", f"槽位 {current_slot} 已就绪，跳过全量复制（如需强制同步请置 PYSPOS_FORCE_SLOT_SYNC=1）", boot_time)
        logk.printl("ota", "OTA槽位结构初始化完成", boot_time)
        return True

    logk.printl("ota", f"正在将src目录文件复制到 {current_slot} 槽位...", boot_time)
    
    try:
        # 获取src目录所有文件和文件夹（排除不必要的文件）
        src_items = [item for item in os.listdir(script_dir) if item not in ['__pycache__', '.git', 'slot_a', 'slot_b']]
        
        for item in src_items:
            src_path = os.path.join(script_dir, item)
            dest_path = os.path.join(current_slot_path, item)
            
            # 确保目标父目录存在
            dest_parent = os.path.dirname(dest_path)
            if not os.path.exists(dest_parent):
                os.makedirs(dest_parent, exist_ok=True)
            
            if os.path.isfile(src_path):
                shutil.copy2(src_path, dest_path)
            elif os.path.isdir(src_path):
                if os.path.exists(dest_path):
                    shutil.rmtree(dest_path)
                shutil.copytree(src_path, dest_path)
        
        logk.printl("ota", f"src目录文件复制到 {current_slot} 槽位成功", boot_time)
    except Exception as e:
        logk.printl("ota", f"复制文件到槽位失败: {str(e)}", boot_time)
        return False
    
    logk.printl("ota", "OTA槽位结构初始化完成", boot_time)
    return True