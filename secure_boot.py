import base64
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import uuid
import zipfile

ALGORITHM = "ed25519"
MANIFEST_NAME = "boot_manifest.json"
SIGNATURE_NAME = "boot_manifest.sig"
POLICY_NAME = "boot_policy.json"
POLICY_SIGNATURE_NAME = "boot_policy.sig"
PROTECTED_DIR = ".pyspos_boot"
STATE_RELATIVE_PATH = os.path.join(PROTECTED_DIR, "boot_state.json")
POLICY_RELATIVE_PATH = os.path.join(PROTECTED_DIR, POLICY_NAME)
POLICY_SIGNATURE_RELATIVE_PATH = os.path.join(PROTECTED_DIR, POLICY_SIGNATURE_NAME)
DEVICE_PRIVATE_KEY_NAME = "device_signing_key.pem"
DEVICE_PUBLIC_KEY_NAME = "device_signing_key.pub"
SLOTS = ("slot_a", "slot_b")
_RUNTIME_TRUSTED_KEYS = {}
TRUSTED_PUBLIC_KEYS = {
    "6ebb03d113dcce85213d81c44d81bcaf": "E14Rw1ot7/pBbVWgVQlNTx+3yLpQtEaQ3TEYQ8MM8Ek=",
}
MUTABLE_TOP_LEVEL = {"etc", "update_log.json", ".hotreset"}
_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
_KEY_ID = re.compile(r"^[0-9a-fA-F]{16,64}$")


class BootVerificationError(Exception):
    pass


def canonical_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha256_bytes(value):
    return hashlib.sha256(value).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def public_key_id(public_bytes):
    if not isinstance(public_bytes, (bytes, bytearray)) or len(public_bytes) != 32:
        raise BootVerificationError("Ed25519 公钥长度无效")
    return hashlib.sha256(bytes(public_bytes)).hexdigest()[:32]


def decode_public_key(value):
    if isinstance(value, (bytes, bytearray)):
        data = bytes(value)
    else:
        try:
            data = base64.b64decode(str(value), validate=True)
        except Exception as exc:
            raise BootVerificationError("公钥不是有效的 base64") from exc
    if len(data) != 32:
        raise BootVerificationError("Ed25519 公钥长度无效")
    return data


def load_private_key(path_or_bytes):
    try:
        from cryptography.hazmat.primitives import serialization
    except ImportError as exc:
        raise BootVerificationError("缺少 cryptography，无法使用签名验证") from exc
    try:
        if hasattr(path_or_bytes, "sign"):
            return path_or_bytes
        if isinstance(path_or_bytes, (bytes, bytearray)):
            data = bytes(path_or_bytes)
        else:
            with open(path_or_bytes, "rb") as stream:
                data = stream.read()
        key = serialization.load_pem_private_key(data, password=None)
    except Exception as exc:
        raise BootVerificationError("无法读取 Ed25519 私钥") from exc
    if not hasattr(key, "sign"):
        raise BootVerificationError("私钥不是 Ed25519 私钥")
    return key


def public_key_bytes(private_key):
    try:
        from cryptography.hazmat.primitives import serialization
    except ImportError as exc:
        raise BootVerificationError("缺少 cryptography，无法使用签名验证") from exc
    raw = private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    return raw


def sign_bytes(private_key, payload):
    return private_key.sign(payload)


def _load_trusted_keys(keys=None, include_runtime=True):
    source = TRUSTED_PUBLIC_KEYS if keys is None else keys
    if not source and not (include_runtime and _RUNTIME_TRUSTED_KEYS):
        raise BootVerificationError("Bootloader 没有配置可信公钥")
    if isinstance(source, dict):
        result = {}
        for key_id, value in source.items():
            result[str(key_id).lower()] = decode_public_key(value)
    else:
        result = {}
        for value in source:
            raw = decode_public_key(value)
            result[public_key_id(raw)] = raw
    if keys is None and include_runtime:
        result.update(_RUNTIME_TRUSTED_KEYS)
    return result


def _device_private_path(root_dir):
    return os.path.join(root_dir, PROTECTED_DIR, DEVICE_PRIVATE_KEY_NAME)


def _device_public_path(root_dir):
    return os.path.join(root_dir, PROTECTED_DIR, DEVICE_PUBLIC_KEY_NAME)


def configure_runtime_keys(root_dir, locked):
    _RUNTIME_TRUSTED_KEYS.clear()
    if locked:
        return {}
    path = _device_public_path(root_dir)
    if os.path.islink(path) or not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="ascii") as stream:
            raw = decode_public_key(stream.read().strip())
        key_id = public_key_id(raw)
    except (OSError, BootVerificationError):
        return {}
    _RUNTIME_TRUSTED_KEYS[key_id] = raw
    return dict(_RUNTIME_TRUSTED_KEYS)


def ensure_developer_key(root_dir, locked=False):
    if locked:
        raise BootVerificationError("LOCKED 模式不能生成设备开发密钥")
    private_path = _device_private_path(root_dir)
    public_path = _device_public_path(root_dir)
    if os.path.islink(private_path) or os.path.islink(public_path):
        raise BootVerificationError("开发密钥路径不能是符号链接")
    try:
        private_key = load_private_key(private_path)
    except BootVerificationError:
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives import serialization
        except ImportError as exc:
            raise BootVerificationError("缺少 cryptography，无法生成开发密钥") from exc
        private_key = Ed25519PrivateKey.generate()
        pem = private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        _atomic_bytes(private_path, pem, ".device-key-")
    raw_public = public_key_bytes(private_key)
    public_value = base64.b64encode(raw_public) + b"\n"
    _atomic_bytes(public_path, public_value, ".device-key-")
    key_id = public_key_id(raw_public)
    _RUNTIME_TRUSTED_KEYS.clear()
    _RUNTIME_TRUSTED_KEYS[key_id] = raw_public
    return {
        "key_id": key_id,
        "private_key": private_path,
        "public_key": public_path,
    }


def developer_key_id(root_dir):
    path = _device_public_path(root_dir)
    if os.path.islink(path) or not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="ascii") as stream:
            return public_key_id(decode_public_key(stream.read().strip()))
    except (OSError, BootVerificationError):
        return None


def _validate_path(path):
    if not isinstance(path, str) or not path or "\\" in path or "\x00" in path:
        raise BootVerificationError(f"manifest 路径无效: {path!r}")
    if path.startswith("/") or path.startswith("./") or path == ".":
        raise BootVerificationError(f"manifest 路径必须是相对路径: {path}")
    parts = path.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise BootVerificationError(f"manifest 路径不安全: {path}")
    if any(":" in part for part in parts):
        raise BootVerificationError(f"manifest 路径不能包含特殊字符: {path}")
    if os.path.splitdrive(path)[0] or re.match(r"^[A-Za-z]:", path):
        raise BootVerificationError(f"manifest 路径不能包含盘符: {path}")
    if path in (MANIFEST_NAME, SIGNATURE_NAME):
        raise BootVerificationError("manifest 不能自包含验证文件")
    return path


def validate_manifest(manifest):
    if not isinstance(manifest, dict):
        raise BootVerificationError("manifest 必须是 JSON 对象")
    if manifest.get("format") != 1:
        raise BootVerificationError("不支持的 manifest 格式")
    if manifest.get("algorithm") != ALGORITHM:
        raise BootVerificationError("不支持的签名算法")
    if manifest.get("product") != "PySpOS":
        raise BootVerificationError("manifest 产品标识不匹配")
    version = manifest.get("version")
    if not isinstance(version, str) or not version.strip():
        raise BootVerificationError("manifest 缺少系统版本")
    security_version = manifest.get("security_version")
    if isinstance(security_version, bool) or not isinstance(security_version, int) \
            or security_version < 0:
        raise BootVerificationError("manifest security_version 无效")
    key_id = manifest.get("key_id")
    if not isinstance(key_id, str) or not _KEY_ID.fullmatch(key_id):
        raise BootVerificationError("manifest key_id 无效")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise BootVerificationError("manifest 缺少文件哈希表")
    for path, digest in files.items():
        _validate_path(path)
        if not isinstance(digest, str) or not _HEX64.fullmatch(digest):
            raise BootVerificationError(f"文件哈希无效: {path}")
    return manifest


def parse_manifest(raw):
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BootVerificationError("manifest 不是有效 UTF-8 JSON") from exc
    return validate_manifest(value)


def _signature_bytes(raw):
    if len(raw) == 64:
        return raw
    try:
        value = base64.b64decode(raw.decode("ascii").strip(), validate=True)
    except Exception as exc:
        raise BootVerificationError("签名编码无效") from exc
    if len(value) != 64:
        raise BootVerificationError("Ed25519 签名长度无效")
    return value


def validate_policy(policy):
    if not isinstance(policy, dict) or policy.get("format") != 1:
        raise BootVerificationError("Bootloader policy 格式无效")
    if policy.get("algorithm") != ALGORITHM or policy.get("product") != "PySpOS":
        raise BootVerificationError("Bootloader policy 标识无效")
    if not isinstance(policy.get("locked"), bool):
        raise BootVerificationError("Bootloader policy.locked 无效")
    for key in ("policy_version", "rollback_index"):
        value = policy.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise BootVerificationError(f"Bootloader policy.{key} 无效")
    key_id = policy.get("key_id")
    if not isinstance(key_id, str) or not _KEY_ID.fullmatch(key_id):
        raise BootVerificationError("Bootloader policy.key_id 无效")
    return policy


def verify_policy_bytes(raw, signature, keys=None):
    try:
        policy = validate_policy(json.loads(raw.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BootVerificationError("Bootloader policy 不是有效 JSON") from exc
    trusted = _load_trusted_keys(keys, include_runtime=False)
    key_id = policy["key_id"].lower()
    if key_id not in trusted:
        raise BootVerificationError("Bootloader policy 使用了不受信任的密钥")
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        Ed25519PublicKey.from_public_bytes(trusted[key_id]).verify(
            _signature_bytes(signature), raw)
    except BootVerificationError:
        raise
    except Exception as exc:
        raise BootVerificationError("Bootloader policy 签名验证失败") from exc
    return policy


def verify_manifest_bytes(raw, signature, keys=None, floor=0):
    manifest = parse_manifest(raw)
    trusted = _load_trusted_keys(keys)
    key_id = manifest["key_id"].lower()
    if key_id not in trusted:
        raise BootVerificationError("manifest 使用了不受信任的密钥")
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        public_key = Ed25519PublicKey.from_public_bytes(trusted[key_id])
        public_key.verify(_signature_bytes(signature), raw)
    except BootVerificationError:
        raise
    except Exception as exc:
        raise BootVerificationError("manifest 签名验证失败") from exc
    if manifest["security_version"] < floor:
        raise BootVerificationError(
            f"系统版本被回滚：{manifest['security_version']} < {floor}")
    return manifest


def _is_mutable(path):
    return path in MUTABLE_TOP_LEVEL or path.startswith("etc/")


def _iter_tree_files(tree_path):
    if os.path.islink(tree_path) or not os.path.isdir(tree_path):
        raise BootVerificationError("系统镜像目录无效")
    for root, dirs, files in os.walk(tree_path, topdown=True, followlinks=False):
        relative_root = os.path.relpath(root, tree_path)
        if relative_root == ".":
            relative_root = ""
        for directory in list(dirs):
            full = os.path.join(root, directory)
            if os.path.islink(full):
                raise BootVerificationError("系统镜像不能包含符号链接")
            rel = os.path.join(relative_root, directory).replace(os.sep, "/")
            if _is_mutable(rel):
                dirs.remove(directory)
        for filename in files:
            full = os.path.join(root, filename)
            rel = os.path.join(relative_root, filename).replace(os.sep, "/")
            yield rel, full


def _safe_tree_path(tree_path, relative):
    relative = _validate_path(relative)
    full = os.path.realpath(os.path.join(tree_path, relative))
    root = os.path.realpath(tree_path)
    try:
        inside = os.path.commonpath((root, full)) == root
    except ValueError as exc:
        raise BootVerificationError("系统镜像路径越界") from exc
    if not inside or full == root:
        raise BootVerificationError("系统镜像路径越界")
    if os.path.islink(full):
        raise BootVerificationError("系统镜像不能包含符号链接")
    return full


def verify_tree(tree_path, manifest, keys=None, floor=0):
    validate_manifest(manifest)
    trusted = _load_trusted_keys(keys)
    if manifest["key_id"].lower() not in trusted:
        raise BootVerificationError("manifest 使用了不受信任的密钥")
    if manifest["security_version"] < floor:
        raise BootVerificationError("系统版本低于防回滚下限")
    listed = set(manifest["files"])
    seen = set()
    for relative, full in _iter_tree_files(tree_path):
        if relative in (MANIFEST_NAME, SIGNATURE_NAME) or _is_mutable(relative):
            continue
        if relative in seen:
            raise BootVerificationError(f"系统镜像文件重复: {relative}")
        seen.add(relative)
        if relative not in listed:
            raise BootVerificationError(f"系统镜像包含未签名文件: {relative}")
        if not stat.S_ISREG(os.stat(full, follow_symlinks=False).st_mode):
            raise BootVerificationError(f"系统镜像文件类型无效: {relative}")
        if sha256_file(full).lower() != manifest["files"][relative].lower():
            raise BootVerificationError(f"系统镜像文件哈希不匹配: {relative}")
    missing = set(listed) - seen
    if missing:
        raise BootVerificationError(f"系统镜像缺少文件: {sorted(missing)[0]}")
    return manifest


# 启动期状态文件（构建机/运行期的 current_slot、.hotreset）。
# 打进更新包属于打包事故：它们描述的是**构建那台机器**的状态，
# 落到目标槽位会污染启动判断。处理方式是验签与解包时直接跳过
# （不报错、不落地），而不是让整个更新失败；防线仍在：
# 签名、manifest 清单比对、防回滚 floor 一行不少。
_BOOT_STATE_MEMBERS = frozenset({"current_slot", ".hotreset"})


def _is_boot_state_member(name):
    """判断是否为启动期状态文件（允许 src/ 前缀）。"""
    if not isinstance(name, str):
        return False
    stripped = name[4:] if name.startswith("src/") else name
    return stripped in _BOOT_STATE_MEMBERS


def _normalized_member(name):
    if not isinstance(name, str) or not name or "\\" in name or "\x00" in name:
        raise BootVerificationError(f"更新包成员路径无效: {name!r}")
    if name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        raise BootVerificationError(f"更新包成员不能是绝对路径: {name}")
    parts = name.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise BootVerificationError(f"更新包成员路径不安全: {name}")
    if name.startswith("src/"):
        name = name[4:]
    if not name or name.endswith("/"):
        return None
    if name == "current_slot" or name == ".hotreset":
        raise BootVerificationError("更新包不能携带启动状态")
    return _validate_path(name)


def _package_manifest_path(names):
    if "src/" + MANIFEST_NAME in names:
        return "src/" + MANIFEST_NAME
    if MANIFEST_NAME in names:
        return MANIFEST_NAME
    return None


def _package_signature_path(manifest_path):
    if manifest_path.startswith("src/"):
        return "src/" + SIGNATURE_NAME
    return SIGNATURE_NAME


def verify_package(package_path, keys=None, floor=0, locked=True):
    if locked and keys is None:
        _RUNTIME_TRUSTED_KEYS.clear()
    try:
        archive = zipfile.ZipFile(package_path, "r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise BootVerificationError("更新包不是有效 ZIP") from exc
    with archive:
        infos = archive.infolist()
        if len(infos) > 20000:
            raise BootVerificationError("更新包成员过多")
        names = [info.filename for info in infos]
        if len(set(names)) != len(names):
            raise BootVerificationError("更新包包含重复成员名")
        names = set(names)
        manifest_path = _package_manifest_path(names)
        if manifest_path is None:
            for info in infos:
                if not info.is_dir() and not _is_boot_state_member(info.filename):
                    _normalized_member(info.filename)
            if locked:
                raise BootVerificationError("更新包缺少签名 manifest")
            return None
        signature_path = _package_signature_path(manifest_path)
        if signature_path not in names:
            raise BootVerificationError("更新包缺少 manifest 签名")
        manifest = verify_manifest_bytes(
            archive.read(manifest_path), archive.read(signature_path), keys, floor)
        normalized = {}
        total_size = 0
        for info in infos:
            if info.is_dir():
                continue
            if info.filename in (MANIFEST_NAME, SIGNATURE_NAME,
                                 "src/" + MANIFEST_NAME, "src/" + SIGNATURE_NAME):
                continue
            if _is_boot_state_member(info.filename):
                continue
            rel = _normalized_member(info.filename)
            if rel is None:
                continue
            if _is_mutable(rel):
                raise BootVerificationError("签名更新包不能携带运行时数据")
            if info.flag_bits & 0x1:
                raise BootVerificationError("更新包不支持加密成员")
            if info.file_size < 0 or info.file_size > 128 * 1024 * 1024:
                raise BootVerificationError("更新包单文件过大")
            total_size += info.file_size
            if total_size > 512 * 1024 * 1024:
                raise BootVerificationError("更新包解压体积过大")
            if rel in normalized:
                raise BootVerificationError(f"更新包成员重复: {rel}")
            normalized[rel] = info
        listed = set(manifest["files"])
        if set(normalized) != listed:
            extra = sorted(set(normalized) - listed)
            missing = sorted(listed - set(normalized))
            detail = extra[0] if extra else (missing[0] if missing else "")
            raise BootVerificationError(f"更新包文件清单不匹配: {detail}")
        for rel, info in normalized.items():
            digest = hashlib.sha256()
            with archive.open(info, "r") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest().lower() != manifest["files"][rel].lower():
                raise BootVerificationError(f"更新包文件哈希不匹配: {rel}")
        return manifest


def _zip_member_map(archive):
    result = {}
    has_src = any(info.filename.startswith("src/") for info in archive.infolist())
    for info in archive.infolist():
        if info.is_dir():
            continue
        if _is_boot_state_member(info.filename):
            continue
        rel = _normalized_member(info.filename)
        if rel is None or rel in (MANIFEST_NAME, SIGNATURE_NAME):
            continue
        if _is_mutable(rel):
            raise BootVerificationError("签名更新包不能携带运行时数据")
        if rel in result:
            raise BootVerificationError(f"更新包成员重复: {rel}")
        result[rel] = info
    return result, has_src


def make_manifest_from_zip(package_path, version, security_version, key_id):
    with zipfile.ZipFile(package_path, "r") as archive:
        members, has_src = _zip_member_map(archive)
        files = {}
        for rel, info in members.items():
            if _is_mutable(rel):
                continue
            digest = hashlib.sha256()
            with archive.open(info, "r") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            files[rel] = digest.hexdigest()
    if not files:
        raise BootVerificationError("更新包没有可签名的系统文件")
    return {
        "format": 1,
        "algorithm": ALGORITHM,
        "product": "PySpOS",
        "version": version,
        "security_version": security_version,
        "key_id": key_id,
        "files": files,
    }


def sign_package(package_path, version, security_version, private_key_path,
                  trusted_keys=None):
    private_key = load_private_key(private_key_path)
    raw_public = public_key_bytes(private_key)
    key_id = public_key_id(raw_public)
    if key_id not in _load_trusted_keys(trusted_keys):
        raise BootVerificationError("签名私钥对应的公钥不在 Bootloader 信任库中")
    manifest = make_manifest_from_zip(package_path, version, security_version, key_id)
    raw_manifest = canonical_bytes(manifest)
    signature = sign_bytes(private_key, raw_manifest)
    temp_path = package_path + ".signed"
    with zipfile.ZipFile(package_path, "r") as source:
        with zipfile.ZipFile(temp_path, "w", zipfile.ZIP_DEFLATED) as target:
            has_src = any(info.filename.startswith("src/") for info in source.infolist())
            for info in source.infolist():
                if info.is_dir() or info.filename in (MANIFEST_NAME, SIGNATURE_NAME,
                                                       "src/" + MANIFEST_NAME,
                                                       "src/" + SIGNATURE_NAME):
                    continue
                target.writestr(info, source.read(info.filename))
            prefix = "src/" if has_src else ""
            target.writestr(prefix + MANIFEST_NAME, raw_manifest)
            target.writestr(prefix + SIGNATURE_NAME, signature)
    os.replace(temp_path, package_path)
    return manifest


def _state_path(root_dir):
    return os.path.join(root_dir, STATE_RELATIVE_PATH)


def _policy_path(root_dir):
    return os.path.join(root_dir, POLICY_RELATIVE_PATH)


def _policy_signature_path(root_dir):
    return os.path.join(root_dir, POLICY_SIGNATURE_RELATIVE_PATH)


def _default_state():
    return {
        "format": 1,
        "active_slot": None,
        "pending_slot": None,
        "previous_slot": None,
        "rollback_index": 0,
        "attempts_remaining": 0,
    }


def _atomic_bytes(path, payload, prefix):
    parent = os.path.dirname(path)
    os.makedirs(parent, mode=0o700, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=prefix, dir=parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _atomic_json(path, value):
    payload = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)
               + "\n").encode("utf-8")
    _atomic_bytes(path, payload, ".boot-state-")


def _validate_state(value):
    if not isinstance(value, dict) or value.get("format") != 1:
        raise BootVerificationError("boot state 格式无效")
    for key in ("active_slot", "pending_slot", "previous_slot"):
        slot = value.get(key)
        if slot is not None and slot not in SLOTS:
            raise BootVerificationError("boot state 槽位无效")
    rollback = value.get("rollback_index")
    attempts = value.get("attempts_remaining")
    if isinstance(rollback, bool) or not isinstance(rollback, int) or rollback < 0:
        raise BootVerificationError("boot state rollback_index 无效")
    if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 0:
        raise BootVerificationError("boot state attempts_remaining 无效")
    return value


def load_state(root_dir, create=True):
    path = _state_path(root_dir)
    if os.path.islink(path):
        raise BootVerificationError("boot state 不能是符号链接")
    try:
        with open(path, "r", encoding="utf-8") as stream:
            return _validate_state(json.load(stream))
    except FileNotFoundError:
        if not create:
            raise BootVerificationError("boot state 不存在")
        state = _default_state()
        _atomic_json(path, state)
        return state
    except (OSError, json.JSONDecodeError) as exc:
        raise BootVerificationError("boot state 损坏，拒绝启动") from exc


def save_state(root_dir, state):
    _atomic_json(_state_path(root_dir), _validate_state(state))


def read_policy(root_dir, keys=None):
    policy_path = _policy_path(root_dir)
    signature_path = _policy_signature_path(root_dir)
    if not os.path.lexists(policy_path) and not os.path.lexists(signature_path):
        return None
    if (os.path.islink(policy_path) or os.path.islink(signature_path)
            or not os.path.isfile(policy_path) or not os.path.isfile(signature_path)):
        raise BootVerificationError("Bootloader policy 文件不完整或包含符号链接")
    try:
        with open(policy_path, "rb") as stream:
            raw = stream.read()
        with open(signature_path, "rb") as stream:
            signature = stream.read()
    except OSError as exc:
        raise BootVerificationError("无法读取 Bootloader policy") from exc
    return verify_policy_bytes(raw, signature, keys)


def write_policy(root_dir, locked, rollback_index, private_key_path, trusted_keys=None):
    if isinstance(rollback_index, bool) or not isinstance(rollback_index, int) \
            or rollback_index < 0:
        raise BootVerificationError("policy rollback_index 无效")
    private_key = load_private_key(private_key_path)
    raw_public = public_key_bytes(private_key)
    key_id = public_key_id(raw_public)
    if key_id not in _load_trusted_keys(trusted_keys, include_runtime=False):
        raise BootVerificationError("签名私钥对应的公钥不在 Bootloader 信任库中")
    policy = {
        "format": 1,
        "algorithm": ALGORITHM,
        "product": "PySpOS",
        "policy_version": 1,
        "locked": bool(locked),
        "rollback_index": int(rollback_index),
        "key_id": key_id,
    }
    raw = canonical_bytes(policy)
    signature = sign_bytes(private_key, raw)
    _atomic_bytes(_policy_path(root_dir), raw, ".boot-policy-")
    _atomic_bytes(_policy_signature_path(root_dir), signature, ".boot-policy-")
    try:
        os.chmod(os.path.join(root_dir, PROTECTED_DIR), 0o700)
    except OSError:
        pass
    return policy


def read_locked(root_dir, keys=None):
    policy = read_policy(root_dir, keys)
    if policy is None:
        return True
    return policy["locked"]


def policy_rollback_index(root_dir, keys=None):
    policy = read_policy(root_dir, keys)
    return 0 if policy is None else policy["rollback_index"]


def _slot_path(root_dir, slot):
    if slot not in SLOTS:
        raise BootVerificationError("槽位名称无效")
    path = os.path.realpath(os.path.join(root_dir, slot))
    root = os.path.realpath(root_dir)
    try:
        inside = os.path.commonpath((root, path)) == root
    except ValueError as exc:
        raise BootVerificationError("槽位路径越界") from exc
    if not inside or os.path.basename(path) != slot or os.path.islink(path):
        raise BootVerificationError("槽位路径无效")
    return path


def _legacy_slot(root_dir):
    path = os.path.join(root_dir, "current_slot")
    try:
        with open(path, "r", encoding="utf-8") as stream:
            value = stream.read().strip()
    except OSError:
        return None
    return value if value in SLOTS else None


def verify_slot(root_dir, slot, locked=True, keys=None, floor=0):
    if locked and keys is None:
        _RUNTIME_TRUSTED_KEYS.clear()
    manifest = _manifest_from_slot(root_dir, slot, keys, floor)
    if locked and manifest is None:
        raise BootVerificationError("锁定槽位缺少签名 manifest")
    return manifest


def _manifest_from_slot(root_dir, slot, keys, floor):
    path = _slot_path(root_dir, slot)
    manifest_path = os.path.join(path, MANIFEST_NAME)
    signature_path = os.path.join(path, SIGNATURE_NAME)
    if not os.path.isfile(manifest_path) or not os.path.isfile(signature_path):
        return None
    with open(manifest_path, "rb") as stream:
        raw_manifest = stream.read()
    with open(signature_path, "rb") as stream:
        signature = stream.read()
    manifest = verify_manifest_bytes(raw_manifest, signature, keys, floor)
    verify_tree(path, manifest, keys, floor)
    return manifest


def _choose_candidates(root_dir, state, legacy_slot):
    candidates = []
    for slot in (state.get("pending_slot"), state.get("active_slot"),
                 legacy_slot, "slot_a", "slot_b"):
        if slot in SLOTS and slot not in candidates:
            candidates.append(slot)
    return candidates


def prepare_boot(root_dir, locked, keys=None, legacy_slot=None):
    if locked and keys is None:
        _RUNTIME_TRUSTED_KEYS.clear()
    state = load_state(root_dir)
    floor = max(state["rollback_index"], policy_rollback_index(root_dir, keys))
    candidates = _choose_candidates(root_dir, state, legacy_slot)
    for slot in candidates:
        try:
            path = _slot_path(root_dir, slot)
        except BootVerificationError:
            continue
        if not os.path.isfile(os.path.join(path, "main.py")):
            continue
        try:
            manifest = _manifest_from_slot(root_dir, slot, keys, floor)
            if locked and manifest is None:
                continue
            if manifest is not None:
                if state.get("pending_slot") == slot and state.get("attempts_remaining"):
                    state["attempts_remaining"] -= 1
                    save_state(root_dir, state)
            return {"slot": slot, "manifest": manifest, "state": state}
        except BootVerificationError:
            if locked and state.get("pending_slot") == slot:
                state["attempts_remaining"] = 0
                state["pending_slot"] = None
                save_state(root_dir, state)
                continue
            if not locked:
                return {"slot": slot, "manifest": None, "state": state}
            continue
    if locked:
        raise BootVerificationError("没有通过签名和防回滚检查的可启动槽位")
    return None


def mark_boot_success(root_dir, slot, manifest=None):
    if slot not in SLOTS:
        raise BootVerificationError("成功启动的槽位无效")
    state = load_state(root_dir)
    previous = state.get("active_slot")
    if previous and previous != slot:
        state["previous_slot"] = previous
    state["active_slot"] = slot
    state["pending_slot"] = None
    state["attempts_remaining"] = 0
    if manifest is not None:
        state["rollback_index"] = max(state["rollback_index"],
                                      int(manifest["security_version"]))
    save_state(root_dir, state)


def stage_slot(root_dir, slot, manifest=None):
    if slot not in SLOTS:
        raise BootVerificationError("待切换槽位无效")
    state = load_state(root_dir)
    if state.get("active_slot") is None:
        state["active_slot"] = _legacy_slot(root_dir)
    state["previous_slot"] = state.get("active_slot")
    state["pending_slot"] = slot
    state["attempts_remaining"] = 3
    save_state(root_dir, state)


def image_security_version(root_dir, slot):
    try:
        manifest = _manifest_from_slot(root_dir, slot, None, 0)
    except BootVerificationError:
        return None
    return None if manifest is None else manifest["security_version"]


def secure_slot_present(root_dir, slot, keys=None, floor=0):
    try:
        return _manifest_from_slot(root_dir, slot, keys, floor) is not None
    except BootVerificationError:
        return False


def stage_directory_replace(root_dir, slot, staging_path):
    target = _slot_path(root_dir, slot)
    if os.path.commonpath((os.path.realpath(root_dir), os.path.realpath(staging_path))) \
            != os.path.realpath(root_dir):
        raise BootVerificationError("staging 路径越界")
    backup = target + ".old-" + uuid.uuid4().hex[:12]
    if os.path.exists(target):
        os.replace(target, backup)
    try:
        os.replace(staging_path, target)
    except Exception:
        if os.path.exists(backup) and not os.path.exists(target):
            os.replace(backup, target)
        raise
    shutil.rmtree(backup, ignore_errors=True)
