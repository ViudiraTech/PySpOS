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
import stat
import tempfile
import uuid
import secure_boot

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
OTA_SERVER_URL = "https://goutoustdio.rainyland.top/ota/"  # 更新服务器域名
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
    "version.txt", "launcher.py"
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
            'Referer': 'https://goutoustdio.rainyland.top/',
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
        'Referer': 'https://goutoustdio.rainyland.top/',
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
            '-H', 'Referer: https://goutoustdio.rainyland.top/',
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
            'Referer': 'https://goutoustdio.rainyland.top/',
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

def _boot_is_locked():
    try:
        return secure_boot.read_locked(root_dir)
    except secure_boot.BootVerificationError:
        return True


def _rollback_floor():
    try:
        state_floor = secure_boot.load_state(root_dir)["rollback_index"]
    except secure_boot.BootVerificationError:
        state_floor = 0
    try:
        policy_floor = secure_boot.policy_rollback_index(root_dir)
    except secure_boot.BootVerificationError:
        policy_floor = 0
    return max(state_floor, policy_floor)


# 验证更新包完整性
def verify_update_package(package_path: str, expected_hash: str = None) -> bool:
    locked = _boot_is_locked()
    try:
        if expected_hash:
            logk.printl("ota", "验证更新包 SHA-256", boot_time)
            sha256_hash = hashlib.sha256()
            with open(package_path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    sha256_hash.update(chunk)
            calculated_hash = sha256_hash.hexdigest()
            if calculated_hash.lower() != str(expected_hash).lower():
                logk.printl("ota", "校验和不匹配", boot_time)
                return False
        manifest = secure_boot.verify_package(
            package_path, floor=_rollback_floor(), locked=locked)
        if locked and manifest is None:
            return False
        if manifest is not None:
            logk.printl("ota", f"签名验证通过，security_version={manifest['security_version']}", boot_time)
        else:
            logk.printl("ota", "未签名开发包，仅允许未锁定模式安装", boot_time)
        return True
    except Exception as e:
        logk.printl("ota", f"验证失败: {e}", boot_time)
        return False

def get_current_slot() -> str:
    try:
        state = secure_boot.load_state(root_dir)
        if state.get("active_slot") in (SLOT_A, SLOT_B):
            return state["active_slot"]
    except secure_boot.BootVerificationError:
        pass
    if os.path.exists(CURRENT_SLOT_FILE):
        with open(CURRENT_SLOT_FILE, 'r', encoding='utf-8') as f:
            slot = f.read().strip()
            if slot in [SLOT_A, SLOT_B]:
                return slot
    set_current_slot(SLOT_A)
    return SLOT_A


def set_current_slot(slot: str) -> None:
    if slot not in [SLOT_A, SLOT_B]:
        raise ValueError("无效槽位")
    parent = os.path.dirname(CURRENT_SLOT_FILE)
    os.makedirs(parent, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".current-slot-", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(slot)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, CURRENT_SLOT_FILE)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    logk.printl("ota", f"已设置当前槽位为: {slot}", boot_time)

# 获取其他槽位
def get_other_slot() -> str:
    return SLOT_B if get_current_slot() == SLOT_A else SLOT_A

# 验证更新包
def verify_update_compatibility(package_path=None) -> bool:
    current_ver = get_current_version()
    update_ver = get_update_version(package_path)
    
    comparison = compare_versions(update_ver, current_ver)
    if comparison > 0:
        return True
    elif comparison == 0:
        logk.printl("ota", "更新包版本与当前版本相同", boot_time)
        return False
    else:
        logk.printl("ota", "更新包版本低于当前版本", boot_time)
        return False

def resolve_download_url(download_url: str) -> str:
    """把 version.json 里的 download_url 归一化成绝对 URL。

    相对路径按 OTA_SERVER_URL 拼接；重构版文件名
    （PySpOS-版本-日期.zip）直接可用，由调用方取 basename。
    """
    if not download_url:
        return OTA_SERVER_URL + REMOTE_UPDATE_FILE
    if not download_url.startswith('http://') and not download_url.startswith('https://'):
        return OTA_SERVER_URL + download_url
    return download_url


def list_cloud_versions() -> list:
    """列出云端 version.json 里 changelog 的全部版本（新到旧）。

    每项：version / date / type / download_url（绝对）/
    sha256 / file_size / notes。无 changelog 时退化为顶层单版本。
    开关关闭或网络失败返回 []，不抛异常（调用方直接判空）。
    """
    if not _ota_enabled():
        logk.printl("ota", f"云端更新已禁用: {_ota_disable_reason()}", boot_time)
        return []
    try:
        data = fetch_remote_version()
    except Exception as e:
        logk.printl("ota", f"获取云端版本列表失败: {e}", boot_time)
        return []
    if not data:
        return []
    entries = []
    changelog = data.get('changelog') or []
    if changelog:
        for rel in changelog:
            try:
                entries.append({
                    'version': str(rel.get('version', 'unknown')),
                    'date': str(rel.get('date', '')),
                    'type': str(rel.get('type', '')),
                    'download_url': resolve_download_url(rel.get('download_url', '')),
                    'sha256': rel.get('sha256'),
                    'file_size': rel.get('file_size', 0) or 0,
                    'notes': rel.get('changes') or rel.get('release_notes', ''),
                })
            except Exception as e:
                logk.printl("ota", f"跳过一条损坏的版本记录: {e}", boot_time)
    else:
        entries.append({
            'version': str(data.get('version', 'unknown')),
            'date': str(data.get('release_date', '')),
            'type': str(data.get('develop_stage', '')),
            'download_url': resolve_download_url(data.get('download_url', '')),
            'sha256': data.get('sha256'),
            'file_size': data.get('file_size', 0) or 0,
            'notes': data.get('release_notes', ''),
        })
    return entries


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
        raw_url = remote_info.get('download_url', '')

        # 判断是否是重构版（文件名格式为PySpOS-版本-日期.zip）
        is_rebuild = raw_url and re.match(r'PySpOS-[\d.]+-[\d]+\.zip', raw_url)

        download_url = resolve_download_url(raw_url)
        
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

    other_path = os.path.join(root_dir, other)
    manifest = None
    if _boot_is_locked():
        try:
            manifest = secure_boot.verify_slot(
                root_dir, other, locked=True, floor=_rollback_floor())
        except secure_boot.BootVerificationError as exc:
            logk.printl("ota", f"回滚目标验签或防回滚检查失败: {exc}", boot_time)
            return False
    if not _slot_is_ready(other_path):
        logk.printl("ota", "回滚目标不是完整系统镜像", boot_time)
        return False

    staging = os.path.join(root_dir, f".rollback-{uuid.uuid4().hex[:12]}")
    try:
        shutil.copytree(other_path, staging, symlinks=False)
        if manifest is not None:
            secure_boot.verify_tree(staging, manifest, floor=_rollback_floor())
        log_data = {
            "from_version": get_version(current),
            "to_version": get_version(other),
            "install_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "action": "rollback"
        }
        with open(os.path.join(staging, UPDATE_LOG), "w", encoding="utf-8") as stream:
            json.dump(log_data, stream, indent=2)
        secure_boot.stage_directory_replace(root_dir, current, staging)
        staging = None
    except Exception as exc:
        logk.printl("ota", f"回滚失败: {exc}", boot_time)
        if staging and os.path.isdir(staging):
            shutil.rmtree(staging, ignore_errors=True)
        return False
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
def get_update_version(package_path=None) -> str:
    package_path = package_path or _find_update_package()
    if not package_path:
        return "未知版本"
    try:
        with zipfile.ZipFile(package_path, 'r') as zip_ref:
            names = set(zip_ref.namelist())
            for path in (VERSION_FILE, f'src/{VERSION_FILE}'):
                if path in names:
                    with zip_ref.open(path) as stream:
                        return stream.read().decode().strip()
        logk.printl("ota", "更新包中未找到版本文件", boot_time)
    except Exception as e:
        logk.printl("ota", f"读取更新包版本失败: {str(e)}", boot_time)
    return "未知版本"

def _safe_extract_package(package_path, target_path):
    target_real = os.path.realpath(target_path)
    if not os.path.isdir(target_real) or os.path.islink(target_path):
        raise ValueError("更新暂存目录无效")
    seen = set()
    total_size = 0
    with zipfile.ZipFile(package_path, "r") as archive:
        infos = archive.infolist()
        if len(infos) > 20000:
            raise ValueError("更新包成员过多")
        for info in infos:
            if info.is_dir():
                continue
            if secure_boot._is_boot_state_member(info.filename):
                # 构建机启动状态：验签已跳过，这里也不落地
                continue
            if info.filename in (secure_boot.MANIFEST_NAME, secure_boot.SIGNATURE_NAME,
                                 "src/" + secure_boot.MANIFEST_NAME,
                                 "src/" + secure_boot.SIGNATURE_NAME):
                rel = (secure_boot.MANIFEST_NAME
                       if info.filename.endswith(secure_boot.MANIFEST_NAME)
                       else secure_boot.SIGNATURE_NAME)
            else:
                rel = secure_boot._normalized_member(info.filename)
                if rel is None:
                    continue
            if rel == "etc" or rel.startswith("etc/"):
                raise ValueError("更新包不能携带 etc 数据")
            if rel in seen:
                raise ValueError(f"更新包成员重复: {rel}")
            seen.add(rel)
            if info.file_size < 0 or info.file_size > 128 * 1024 * 1024:
                raise ValueError("更新包单文件过大")
            total_size += info.file_size
            if total_size > 512 * 1024 * 1024:
                raise ValueError("更新包解压体积过大")
            mode = (info.external_attr >> 16) & 0xffff
            if stat.S_ISLNK(mode):
                raise ValueError("更新包不能包含符号链接")
            destination = os.path.realpath(os.path.join(target_real, rel))
            if os.path.commonpath((target_real, destination)) != target_real:
                raise ValueError("更新包路径越界")
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            with archive.open(info, "r") as source, open(destination, "wb") as target:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    target.write(chunk)
    return True


def _find_update_package():
    package_path = os.path.join(OTA_PACKAGE_DIR, OTA_PACKAGE_NAME)
    if os.path.isfile(package_path):
        return package_path
    if not os.path.isdir(OTA_PACKAGE_DIR):
        return None
    for filename in sorted(os.listdir(OTA_PACKAGE_DIR)):
        if filename.endswith(".zip"):
            return os.path.join(OTA_PACKAGE_DIR, filename)
    return None


# 将更新包安装到另一槽位
def install_package_to_slot(package_path: str, slot: str,
                            allow_downgrade: bool = False) -> bool:
    """把已下载的更新包安装到指定槽位（不切换当前槽位）。

    签名验签与防回滚 floor 始终执行；allow_downgrade 只放行
    「版本不高于当前」的新旧比较，且必须由用户显式确认后传入。
    """
    if slot not in (SLOT_A, SLOT_B):
        raise ValueError("无效槽位")
    if not package_path or not os.path.isfile(package_path):
        logk.printl("ota", "未找到更新包", boot_time)
        return False
    if not verify_update_package(package_path):
        return False

    locked = _boot_is_locked()
    try:
        manifest = secure_boot.verify_package(
            package_path, floor=_rollback_floor(), locked=locked)
    except secure_boot.BootVerificationError as exc:
        logk.printl("ota", f"更新包验证失败: {exc}", boot_time)
        return False
    if allow_downgrade:
        logk.printl("ota", "已显式允许同级/降级安装，跳过新旧版本比较", boot_time)
    elif not verify_update_compatibility(package_path):
        logk.printl("ota", "版本不兼容", boot_time)
        return False

    target_slot = os.path.join(root_dir, slot)
    staging = os.path.join(root_dir, f".{slot}.staging-{uuid.uuid4().hex[:12]}")
    current_ver = get_current_version()
    update_ver = get_update_version(package_path)
    logk.printl("ota", f"安装更新: {current_ver} -> {update_ver}", boot_time)
    logk.printl("ota", f"目标槽位: {target_slot}", boot_time)
    start_time = time.time()

    try:
        os.makedirs(staging, exist_ok=False)
        _safe_extract_package(package_path, staging)
        etc_source = os.path.join(root_dir, "etc")
        etc_target = os.path.join(staging, "etc")
        if os.path.isdir(etc_source):
            shutil.copytree(etc_source, etc_target, symlinks=True)
        log_data = {
            "from_version": current_ver,
            "to_version": update_ver,
            "install_time": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        with open(os.path.join(staging, UPDATE_LOG), "w", encoding="utf-8") as stream:
            json.dump(log_data, stream, indent=2)
        if not _slot_is_ready(staging):
            raise ValueError("更新包核心文件不完整")
        if manifest is not None:
            secure_boot.verify_tree(staging, manifest, floor=_rollback_floor())
        secure_boot.stage_directory_replace(root_dir, slot, staging)
        staging = None
        secure_boot.stage_slot(root_dir, slot, manifest)
    except Exception as exc:
        logk.printl("ota", f"安装失败: {exc}", boot_time)
        if staging and os.path.isdir(staging):
            shutil.rmtree(staging, ignore_errors=True)
        return False

    end_time = time.time()
    logk.printl("ota", f"安装完成: {end_time - start_time:.2f}秒", boot_time)
    try:
        if os.path.exists(package_path):
            os.remove(package_path)
            logk.printl("ota", "已删除更新包文件", boot_time)
    except Exception as e:
        logk.printl("ota", f"删除更新包失败: {str(e)}", boot_time)
    return True


def install_update() -> bool:
    """本地安装/默认升级：把更新包目录里的包袱装到另一槽位并切换过去。"""
    package_path = _find_update_package()
    if package_path is None:
        logk.printl("ota", "未找到更新包", boot_time)
        return False
    target_name = get_other_slot()
    if not install_package_to_slot(package_path, target_name):
        return False
    set_current_slot(target_name)
    return True


def download_and_install_version(entry: dict, slot: str,
                                 allow_downgrade: bool = False) -> bool:
    """下载云端指定版本并安装到指定槽位（不自动切换当前槽位）。

    entry 取自 list_cloud_versions() 的条目。调用方负责在降级/
    同级时先拿到用户明确确认，再传 allow_downgrade=True。
    """
    if not _ota_enabled():
        logk.printl("ota", f"云端更新已禁用: {_ota_disable_reason()}", boot_time)
        return False
    if slot not in (SLOT_A, SLOT_B):
        logk.printl("ota", f"无效槽位: {slot}", boot_time)
        return False
    url = (entry or {}).get('download_url', '')
    if not url:
        logk.printl("ota", "版本条目缺少下载地址", boot_time)
        return False
    os.makedirs(OTA_PACKAGE_DIR, exist_ok=True)
    package_name = url.split('/')[-1].split('?')[0] or OTA_PACKAGE_NAME
    package_path = os.path.join(OTA_PACKAGE_DIR, package_name)
    file_size = (entry or {}).get('file_size', 0) or 0

    if not download_update_package(url, package_path, file_size):
        return False
    if not verify_update_package(package_path, (entry or {}).get('sha256')):
        return False
    return install_package_to_slot(package_path, slot, allow_downgrade)

# 切换槽位
def switch_slot() -> bool:
    target = get_other_slot()
    target_path = os.path.join(root_dir, target)

    missing_items = []
    for file in REQUIRED_CORE_FILES:
        if not os.path.exists(os.path.join(target_path, file)):
            missing_items.append(file)
    for directory in REQUIRED_DIRS:
        if not os.path.isdir(os.path.join(target_path, directory)):
            missing_items.append(directory)
    if missing_items:
        logk.printl("ota", f"槽位切换失败：目标槽位 {target} 缺少: {', '.join(missing_items)}", boot_time)
        return False

    manifest = None
    if _boot_is_locked():
        try:
            manifest = secure_boot.verify_slot(
                root_dir, target, locked=True, floor=_rollback_floor())
        except secure_boot.BootVerificationError as exc:
            logk.printl("ota", f"目标槽位验签失败: {exc}", boot_time)
            return False
    try:
        secure_boot.stage_slot(root_dir, target, manifest)
    except secure_boot.BootVerificationError as exc:
        logk.printl("ota", f"无法设置待启动槽位: {exc}", boot_time)
        return False
    set_current_slot(target)
    logk.printl("ota", f"槽位已标记为待启动: {target}", boot_time)
    logk.printl("ota", "请重启系统以加载新槽位的系统文件", boot_time)
    return True

# 获取OTA更新状态
def get_ota_status() -> dict:
    current = get_current_slot()
    other = get_other_slot()
    return {
        "ota_enabled": _ota_enabled(),
        "ota_disable_reason": (None if _ota_enabled() else _ota_disable_reason()),
        "boot_locked": _boot_is_locked(),
        "rollback_index": _rollback_floor(),
        "current_slot": current,
        "current_version": get_current_version(),
        "current_slot_verified": secure_boot.secure_slot_present(
            root_dir, current, floor=_rollback_floor()),
        "other_slot": other,
        "other_version": get_version(other),
        "other_slot_verified": secure_boot.secure_slot_present(
            root_dir, other, floor=_rollback_floor()),
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
    if _boot_is_locked():
        logk.printl("ota", "锁定模式禁止从 src 自动修复或复制系统文件", boot_time)
        return True
    
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
    
    # 槽位完整性只做检查、不做合并复制：开机自动把 src 合并进槽位，
    # 会把新 main.py 盖到旧槽位上、而新依赖又没跟上，造出无法启动的
    # 半成品槽位（3.2.0 的 process.py 等就是这么漏掉的）。槽位是不可
    # 变的安装产物，只允许经由更新/回滚/force_sync 流程写入。
    current_slot = get_current_slot()
    current_slot_path = os.path.join(root_dir, current_slot)
    if not _slot_is_ready(current_slot_path):
        logk.printl("ota", f"槽位 {current_slot} 不完整，本次启动不会自动复制",
                    boot_time)
        logk.printl("ota", "UNLOCKED 模式可用 force_sync.py --slot "
                    f"{current_slot} 手动同步，或进 Recovery 重装该槽位",
                    boot_time)
    else:
        logk.printl("ota", f"槽位 {current_slot} 已就绪", boot_time)
    logk.printl("ota", "OTA槽位结构初始化完成", boot_time)
    return True