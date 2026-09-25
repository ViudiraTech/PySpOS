import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import time
import uuid
import zipfile
from typing import Any, Dict, Iterable, List, Optional


PACKAGE_FORMAT = 1
PACKAGE_SUFFIX = ".pyspkg"
MANIFEST_NAME = "package.json"
MAX_MANIFEST_SIZE = 256 * 1024
MAX_FILE_SIZE = 8 * 1024 * 1024
MAX_TOTAL_SIZE = 32 * 1024 * 1024
MAX_FILE_COUNT = 512

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+_-]{0,63}$")
_HASH_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class PackageError(ValueError):
    pass


class PackageSource:
    def __init__(self, source: os.PathLike[str] | str):
        self.path = os.path.abspath(os.fspath(source))
        self._zip = None
        self._directory_files: Dict[str, str] = {}
        self._zip_files: Dict[str, zipfile.ZipInfo] = {}
        self._total_size = 0
        self.manifest: Dict[str, Any] = {}
        if os.path.isdir(self.path):
            self._load_directory()
        elif os.path.isfile(self.path):
            self._load_zip()
        else:
            raise PackageError(f"包路径不存在: {source}")

    def __enter__(self) -> "PackageSource":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def close(self) -> None:
        if self._zip is not None:
            self._zip.close()
            self._zip = None

    def _load_directory(self) -> None:
        manifest_path = os.path.join(self.path, MANIFEST_NAME)
        if not os.path.isfile(manifest_path) or os.path.islink(manifest_path):
            raise PackageError("包目录缺少 package.json")
        if os.path.getsize(manifest_path) > MAX_MANIFEST_SIZE:
            raise PackageError("package.json 过大")
        for root, dirs, files in os.walk(self.path, topdown=True, followlinks=False):
            dirs[:] = sorted(dirs)
            for name in dirs:
                full = os.path.join(root, name)
                if os.path.islink(full):
                    raise PackageError(f"包目录不允许符号链接: {name}")
            for name in sorted(files):
                full = os.path.join(root, name)
                if os.path.islink(full):
                    raise PackageError(f"包目录不允许符号链接: {name}")
                relative = os.path.relpath(full, self.path).replace(os.sep, "/")
                relative = _safe_member_name(relative)
                if relative == MANIFEST_NAME:
                    continue
                info = os.stat(full)
                if not stat.S_ISREG(info.st_mode):
                    raise PackageError(f"包成员不是普通文件: {relative}")
                self._check_size(relative, info.st_size)
                self._directory_files[relative] = full
        if len(self._directory_files) > MAX_FILE_COUNT:
            raise PackageError("包文件数量超过限制")
        self._load_manifest_from_file(manifest_path)
        self.manifest = _validate_source(self.manifest, self._member_names(), self)

    def _load_zip(self) -> None:
        try:
            self._zip = zipfile.ZipFile(self.path, "r")
        except (OSError, zipfile.BadZipFile) as exc:
            raise PackageError(f"无法打开包文件: {exc}") from exc
        try:
            total = 0
            seen = set()
            for info in self._zip.infolist():
                raw_name = info.filename
                if info.is_dir():
                    _safe_member_name(raw_name.rstrip("/"))
                    continue
                name = _safe_member_name(raw_name)
                if name in seen:
                    raise PackageError(f"包内有重复成员: {name}")
                seen.add(name)
                if info.flag_bits & 0x1:
                    raise PackageError(f"包成员加密，无法安装: {name}")
                mode = (info.external_attr >> 16) & 0xFFFF
                if stat.S_ISLNK(mode):
                    raise PackageError(f"包内不允许符号链接: {name}")
                self._check_size(name, info.file_size)
                total += info.file_size
                if total > MAX_TOTAL_SIZE:
                    raise PackageError("包解压总大小超过限制")
                self._zip_files[name] = info
            if len(self._zip_files) > MAX_FILE_COUNT:
                raise PackageError("包文件数量超过限制")
            if MANIFEST_NAME not in self._zip_files:
                raise PackageError("包文件缺少 package.json")
            manifest_bytes = self._read_zip(MANIFEST_NAME)
            self.manifest = _parse_manifest(manifest_bytes)
            self.manifest = _validate_source(self.manifest, self._member_names(), self)
        except Exception:
            self.close()
            raise

    def _load_manifest_from_file(self, path: str) -> None:
        try:
            with open(path, "rb") as stream:
                raw = stream.read(MAX_MANIFEST_SIZE + 1)
        except OSError as exc:
            raise PackageError(f"读取 package.json 失败: {exc}") from exc
        self.manifest = _parse_manifest(raw)

    def _check_size(self, name: str, size: int) -> None:
        if size < 0 or size > MAX_FILE_SIZE:
            raise PackageError(f"包成员过大: {name}")
        if name != MANIFEST_NAME:
            self._total_size += size
            if self._total_size > MAX_TOTAL_SIZE:
                raise PackageError("包解压总大小超过限制")

    def _member_names(self) -> set[str]:
        return set(self._directory_files) | set(self._zip_files)

    def _read_zip(self, name: str) -> bytes:
        info = self._zip_files.get(name)
        if info is None or self._zip is None:
            raise PackageError(f"包成员不存在: {name}")
        try:
            with self._zip.open(info, "r") as stream:
                data = stream.read(MAX_FILE_SIZE + 1)
        except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
            raise PackageError(f"读取包成员失败: {name}: {exc}") from exc
        if len(data) > MAX_FILE_SIZE:
            raise PackageError(f"包成员过大: {name}")
        return data

    def read_member(self, name: str) -> bytes:
        name = _safe_member_name(name)
        if name == MANIFEST_NAME:
            if self._zip is not None:
                return self._read_zip(name)
            with open(os.path.join(self.path, name), "rb") as stream:
                data = stream.read(MAX_MANIFEST_SIZE + 1)
            if len(data) > MAX_MANIFEST_SIZE:
                raise PackageError("package.json 过大")
            return data
        source_path = self._directory_files.get(name)
        if source_path is not None:
            try:
                with open(source_path, "rb") as stream:
                    data = stream.read(MAX_FILE_SIZE + 1)
            except OSError as exc:
                raise PackageError(f"读取包成员失败: {name}: {exc}") from exc
            if len(data) > MAX_FILE_SIZE:
                raise PackageError(f"包成员过大: {name}")
            return data
        return self._read_zip(name)

    def materialize(self, destination: str) -> None:
        os.makedirs(destination, exist_ok=True)
        for name in sorted(self._member_names()):
            relative = _safe_member_name(name)
            target = os.path.join(destination, *relative.split("/"))
            parent = os.path.dirname(target)
            os.makedirs(parent, exist_ok=True)
            data = self.read_member(relative)
            with open(target, "wb") as stream:
                stream.write(data)
            try:
                os.chmod(target, 0o644)
            except OSError:
                pass


def _parse_manifest(raw: bytes) -> Dict[str, Any]:
    if len(raw) > MAX_MANIFEST_SIZE:
        raise PackageError("package.json 过大")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PackageError(f"package.json 格式错误: {exc}") from exc
    if not isinstance(value, dict):
        raise PackageError("package.json 必须是对象")
    return value


def _safe_member_name(name: str) -> str:
    if not isinstance(name, str) or not name or "\\" in name:
        raise PackageError(f"非法包成员路径: {name!r}")
    if name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        raise PackageError(f"包成员不能是绝对路径: {name}")
    parts = name.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise PackageError(f"包成员路径不安全: {name}")
    return "/".join(parts)


def _validate_manifest(manifest: Dict[str, Any], members: set[str],
                       source: PackageSource) -> Dict[str, Any]:
    if manifest.get("format") != PACKAGE_FORMAT:
        raise PackageError(f"不支持的包格式: {manifest.get('format')!r}")
    package_id = manifest.get("id")
    if not isinstance(package_id, str) or not _ID_RE.fullmatch(package_id):
        raise PackageError("包 id 无效")
    version = manifest.get("version")
    if not isinstance(version, str) or not _VERSION_RE.fullmatch(version):
        raise PackageError("包 version 无效")
    description = manifest.get("description", "")
    if not isinstance(description, str) or len(description) > 512:
        raise PackageError("包 description 无效")
    requires = manifest.get("requires", [])
    if not isinstance(requires, list) or any(not isinstance(item, str) for item in requires):
        raise PackageError("包 requires 必须是字符串列表")
    if requires:
        raise PackageError("当前版本暂不支持依赖安装")
    entrypoints = manifest.get("entrypoints")
    if not isinstance(entrypoints, list) or not entrypoints:
        raise PackageError("包必须声明至少一个 entrypoint")
    normalized_entries = []
    names = set()
    for entry in entrypoints:
        if not isinstance(entry, dict):
            raise PackageError("entrypoint 必须是对象")
        name = entry.get("name")
        if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
            raise PackageError("entrypoint name 无效")
        if name in names:
            raise PackageError(f"entrypoint 名称重复: {name}")
        names.add(name)
        runtime = entry.get("runtime", "python")
        if runtime != "python":
            raise PackageError(f"暂不支持运行时: {runtime}")
        path = entry.get("path")
        if not isinstance(path, str) or not path.startswith("payload/"):
            raise PackageError("entrypoint path 必须位于 payload/")
        path = _safe_member_name(path)
        if path not in members:
            raise PackageError(f"entrypoint 文件不存在: {path}")
        if not path.endswith(".py"):
            raise PackageError("Python entrypoint 必须是 .py 文件")
        aliases = entry.get("aliases", [])
        if not isinstance(aliases, list):
            raise PackageError("entrypoint aliases 必须是列表")
        clean_aliases = []
        for alias in aliases:
            if not isinstance(alias, str) or not _NAME_RE.fullmatch(alias):
                raise PackageError("entrypoint alias 无效")
            if alias in names or alias in clean_aliases:
                raise PackageError(f"entrypoint 名称重复: {alias}")
            clean_aliases.append(alias)
        names.update(clean_aliases)
        normalized_entries.append({
            "name": name,
            "runtime": runtime,
            "path": path,
            "aliases": clean_aliases,
        })
    files = manifest.get("files")
    normalized_files = {}
    if files is not None:
        if not isinstance(files, dict):
            raise PackageError("包 files 必须是对象")
        for name, digest in files.items():
            name = _safe_member_name(name)
            if name == MANIFEST_NAME or not name.startswith("payload/"):
                raise PackageError(f"files 成员路径无效: {name}")
            if not isinstance(digest, str) or not _HASH_RE.fullmatch(digest):
                raise PackageError(f"文件哈希无效: {name}")
            normalized_files[name] = digest.lower()
    actual_files = members - {MANIFEST_NAME}
    if normalized_files and set(normalized_files) != actual_files:
        missing = sorted(actual_files - set(normalized_files))
        extra = sorted(set(normalized_files) - actual_files)
        detail = []
        if missing:
            detail.append("未列出: " + ", ".join(missing))
        if extra:
            detail.append("找不到: " + ", ".join(extra))
        raise PackageError("包 files 与实际成员不一致（" + "; ".join(detail) + "）")
    for name in actual_files:
        data = source.read_member(name)
        digest = _hash_bytes(data)
        expected = normalized_files.get(name)
        if expected is not None and expected != digest:
            raise PackageError(f"文件哈希校验失败: {name}")
        normalized_files[name] = digest
    result = dict(manifest)
    result["entrypoints"] = normalized_entries
    result["files"] = normalized_files
    return result


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _validate_source(manifest: Dict[str, Any], members: set[str],
                      source: PackageSource) -> Dict[str, Any]:
    return _validate_manifest(manifest, members, source)


def packages_dir(root_dir: str) -> str:
    return os.path.join(os.path.abspath(root_dir), "etc", "packages")


def registry_path(root_dir: str) -> str:
    return os.path.join(packages_dir(root_dir), "registry.json")


def _empty_registry() -> Dict[str, Any]:
    return {"format": PACKAGE_FORMAT, "packages": {}}


def _validate_registry_manifest(package_id: str, manifest: Dict[str, Any]) -> None:
    if manifest.get("format") != PACKAGE_FORMAT or manifest.get("id") != package_id:
        raise PackageError(f"包注册表 manifest 无效: {package_id}")
    if not isinstance(manifest.get("version"), str):
        raise PackageError(f"包注册表 version 无效: {package_id}")
    entries = manifest.get("entrypoints")
    if not isinstance(entries, list) or not entries:
        raise PackageError(f"包注册表 entrypoints 无效: {package_id}")
    for entry in entries:
        if not isinstance(entry, dict):
            raise PackageError(f"包注册表 entrypoint 无效: {package_id}")
        name = entry.get("name")
        path = entry.get("path")
        if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
            raise PackageError(f"包注册表 entrypoint name 无效: {package_id}")
        if not isinstance(path, str) or not path.startswith("payload/"):
            raise PackageError(f"包注册表 entrypoint path 无效: {package_id}")
        _safe_member_name(path)
        aliases = entry.get("aliases", [])
        if not isinstance(aliases, list) or any(
                not isinstance(alias, str) or not _NAME_RE.fullmatch(alias)
                for alias in aliases):
            raise PackageError(f"包注册表 entrypoint aliases 无效: {package_id}")


def load_registry(root_dir: str) -> Dict[str, Any]:
    path = registry_path(root_dir)
    try:
        with open(path, "r", encoding="utf-8") as stream:
            value = json.load(stream)
    except FileNotFoundError:
        return _empty_registry()
    except (OSError, json.JSONDecodeError) as exc:
        raise PackageError(f"包注册表损坏: {exc}") from exc
    if not isinstance(value, dict) or value.get("format") != PACKAGE_FORMAT:
        raise PackageError("包注册表格式无效")
    packages = value.get("packages")
    if not isinstance(packages, dict):
        raise PackageError("包注册表 packages 无效")
    for package_id, record in packages.items():
        if not isinstance(package_id, str) or not _ID_RE.fullmatch(package_id):
            raise PackageError("包注册表包含非法 id")
        if not isinstance(record, dict) or not isinstance(record.get("manifest"), dict):
            raise PackageError(f"包注册表记录无效: {package_id}")
        _validate_registry_manifest(package_id, record["manifest"])
    return value


def _write_json_atomic(path: str, value: Dict[str, Any]) -> None:
    parent = os.path.dirname(path)
    os.makedirs(parent, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".registry-", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def save_registry(root_dir: str, registry: Dict[str, Any]) -> None:
    _write_json_atomic(registry_path(root_dir), registry)


def _entrypoint_names(manifest: Dict[str, Any]) -> Iterable[str]:
    for entry in manifest.get("entrypoints", []):
        yield entry.get("name", "")
        yield from entry.get("aliases", [])


def _check_conflicts(manifest: Dict[str, Any], root_dir: str,
                     replacing_id: Optional[str], reserved_commands: Iterable[str]) -> None:
    reserved = set(reserved_commands)
    incoming = set(_entrypoint_names(manifest))
    conflict = sorted(incoming & reserved)
    if conflict:
        raise PackageError("包命令与系统命令冲突: " + ", ".join(conflict))
    registry = load_registry(root_dir)
    for package_id, record in registry["packages"].items():
        if package_id == replacing_id:
            continue
        existing = record["manifest"]
        overlap = sorted(incoming & set(_entrypoint_names(existing)))
        if overlap:
            raise PackageError(
                f"包命令与已安装包 {package_id} 冲突: " + ", ".join(overlap))


def _remove_path(path: str) -> None:
    if not os.path.lexists(path):
        return
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
    else:
        os.unlink(path)


def _installed_base(root_dir: str, package_id: str) -> str:
    if not _ID_RE.fullmatch(package_id):
        raise PackageError("包 id 无效")
    return os.path.join(packages_dir(root_dir), package_id)


def _is_within(base: str, target: str) -> bool:
    try:
        return os.path.commonpath((base, target)) == base
    except ValueError:
        return False


def _installed_entry_path(root_dir: str, package_id: str, relative: str) -> str:
    base = os.path.realpath(_installed_base(root_dir, package_id))
    relative = _safe_member_name(relative)
    target = os.path.realpath(os.path.join(base, *relative.split("/")))
    if not _is_within(base, target):
        raise PackageError("已安装包成员路径逃逸")
    return target


def _record_for_manifest(manifest: Dict[str, Any], source: str) -> Dict[str, Any]:
    return {
        "manifest": manifest,
        "installed_at": int(time.time()),
        "source": os.path.basename(os.path.abspath(source)),
    }


def install_package(source: os.PathLike[str] | str, root_dir: str, *,
                     replace: bool = True,
                     reserved_commands: Iterable[str] = ()) -> Dict[str, Any]:
    with PackageSource(source) as package:
        manifest = package.manifest
        package_id = manifest["id"]
        registry = load_registry(root_dir)
        if package_id in registry["packages"] and not replace:
            raise PackageError(f"包已安装: {package_id}")
        _check_conflicts(manifest, root_dir, package_id, reserved_commands)
        base = packages_dir(root_dir)
        os.makedirs(base, exist_ok=True)
        target = _installed_base(root_dir, package_id)
        staging = tempfile.mkdtemp(prefix=f".{package_id}.staging-", dir=base)
        backup = None
        try:
            package.materialize(staging)
            if os.path.lexists(target):
                backup = os.path.join(base, f".{package_id}.backup-{uuid.uuid4().hex}")
                os.replace(target, backup)
            try:
                os.replace(staging, target)
                staging = None
                registry["packages"][package_id] = _record_for_manifest(manifest, str(source))
                save_registry(root_dir, registry)
            except Exception:
                if os.path.lexists(target):
                    failed = os.path.join(base, f".{package_id}.failed-{uuid.uuid4().hex}")
                    os.replace(target, failed)
                    _remove_path(failed)
                if backup is not None and os.path.lexists(backup):
                    os.replace(backup, target)
                backup = None
                raise
            if backup is not None:
                try:
                    _remove_path(backup)
                except OSError:
                    pass
            return manifest
        finally:
            if staging is not None:
                try:
                    _remove_path(staging)
                except OSError:
                    pass
            if backup is not None and os.path.lexists(backup) and not os.path.lexists(target):
                os.replace(backup, target)


def remove_package(package_id: str, root_dir: str) -> Dict[str, Any]:
    if not _ID_RE.fullmatch(package_id):
        raise PackageError("包 id 无效")
    registry = load_registry(root_dir)
    record = registry["packages"].pop(package_id, None)
    if record is None:
        raise PackageError(f"包未安装: {package_id}")
    target = _installed_base(root_dir, package_id)
    backup = None
    if os.path.lexists(target):
        backup = os.path.join(packages_dir(root_dir), f".{package_id}.removed-{uuid.uuid4().hex}")
        os.replace(target, backup)
    try:
        save_registry(root_dir, registry)
    except Exception:
        if backup is not None and os.path.lexists(backup) and not os.path.lexists(target):
            os.replace(backup, target)
        raise
    if backup is not None:
        try:
            _remove_path(backup)
        except OSError:
            pass
    return record["manifest"]


def list_packages(root_dir: str) -> List[Dict[str, Any]]:
    registry = load_registry(root_dir)
    result = []
    for package_id in sorted(registry["packages"]):
        record = registry["packages"][package_id]
        item = dict(record.get("manifest", {}))
        item["id"] = package_id
        result.append(item)
    return result


def get_package(package_id: str, root_dir: str) -> Optional[Dict[str, Any]]:
    if not _ID_RE.fullmatch(package_id):
        return None
    record = load_registry(root_dir)["packages"].get(package_id)
    if record is None:
        return None
    result = dict(record.get("manifest", {}))
    result["id"] = package_id
    return result


def _entrypoint_record(package_id: str, manifest: Dict[str, Any], entry: Dict[str, Any],
                       root_dir: str) -> Dict[str, Any]:
    path = _installed_entry_path(root_dir, package_id, entry["path"])
    if not os.path.isfile(path):
        return {}
    return {
        "name": entry["name"],
        "aliases": list(entry.get("aliases", [])),
        "package_id": package_id,
        "version": manifest["version"],
        "path": path,
        "package_dir": _installed_base(root_dir, package_id),
    }


def resolve_command(command: str, root_dir: str) -> Optional[Dict[str, Any]]:
    if not isinstance(command, str) or not command:
        return None
    registry = load_registry(root_dir)
    for package_id in sorted(registry["packages"]):
        manifest = registry["packages"][package_id]["manifest"]
        for entry in manifest.get("entrypoints", []):
            if command == entry.get("name") or command in entry.get("aliases", []):
                try:
                    result = _entrypoint_record(package_id, manifest, entry, root_dir)
                except PackageError:
                    return None
                return result or None
    return None


def resolve_package_entrypoint(package_id: str, root_dir: str,
                                entrypoint: Optional[str] = None) -> Optional[Dict[str, Any]]:
    manifest = get_package(package_id, root_dir)
    if manifest is None:
        return None
    entries = manifest.get("entrypoints", [])
    if entrypoint is None:
        entry = entries[0]
    else:
        entry = next((item for item in entries
                      if item.get("name") == entrypoint
                      or entrypoint in item.get("aliases", [])), None)
        if entry is None:
            return None
    try:
        return _entrypoint_record(package_id, manifest, entry, root_dir)
    except PackageError:
        return None


def discover_commands(root_dir: str) -> List[Dict[str, Any]]:
    registry = load_registry(root_dir)
    result = []
    for package_id in sorted(registry["packages"]):
        manifest = registry["packages"][package_id]["manifest"]
        for entry in manifest.get("entrypoints", []):
            try:
                record = _entrypoint_record(package_id, manifest, entry, root_dir)
            except PackageError:
                continue
            if record:
                result.append(record)
    return result


def verify_package(source: os.PathLike[str] | str) -> Dict[str, Any]:
    with PackageSource(source) as package:
        return dict(package.manifest)


def build_package(source: os.PathLike[str] | str,
                  output: os.PathLike[str] | str) -> str:
    source_path = os.path.abspath(os.fspath(source))
    output_path = os.path.abspath(os.fspath(output))
    if output_path == source_path or (
            os.path.isdir(source_path) and _is_within(source_path, output_path)):
        raise PackageError("输出文件不能覆盖源包")
    with PackageSource(source) as package:
        parent = os.path.dirname(output_path)
        os.makedirs(parent, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".package-", suffix=PACKAGE_SUFFIX, dir=parent)
        os.close(fd)
        try:
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(MANIFEST_NAME, json.dumps(
                    package.manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8"))
                for name in sorted(package._member_names()):
                    archive.writestr(name, package.read_member(name))
            os.replace(temporary, output_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return output_path
