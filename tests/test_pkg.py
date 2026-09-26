'''
 *
 *      test_pkg.py
 *      User packages: verify, build, install, command resolution, removal and the rejection cases.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import hashlib
import json
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, "src")
import package_core as pkg


REPO = Path(__file__).resolve().parents[1]


# Write a minimal source package: one entrypoint plus a manifest whose file hash matches the payload.
def _make_package(tmp_path, package_id="org.test.demo", command="demo", body=None):
    body = body or "print('demo package')\n"
    source = tmp_path / "source"
    payload = source / "payload"
    payload.mkdir(parents=True)
    script = payload / f"{command}.py"
    script.write_text(body, encoding="utf-8")
    digest = hashlib.sha256(script.read_bytes()).hexdigest()
    manifest = {
        "format": 1,
        "id": package_id,
        "version": "1.0.0",
        "entrypoints": [{
            "name": command,
            "runtime": "python",
            "path": f"payload/{command}.py",
        }],
        "files": {f"payload/{command}.py": digest},
    }
    (source / "package.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return source


# The whole lifecycle works: verify, install, list, resolve the command to the installed file, then remove and lose both.
def test_verify_install_resolve_and_remove(tmp_path):
    source = _make_package(tmp_path)
    root = tmp_path / "system"
    manifest = pkg.verify_package(source)
    assert manifest["id"] == "org.test.demo"

    pkg.install_package(source, str(root), reserved_commands={"ls"})
    assert [item["id"] for item in pkg.list_packages(str(root))] == ["org.test.demo"]
    target = pkg.resolve_command("demo", str(root))
    assert target is not None
    assert Path(target["path"]).read_text(encoding="utf-8") == "print('demo package')\n"

    pkg.remove_package("org.test.demo", str(root))
    assert pkg.list_packages(str(root)) == []
    assert pkg.resolve_command("demo", str(root)) is None


# A built archive verifies, and installing it twice replaces cleanly instead of duplicating.
def test_build_archive_and_replace(tmp_path):
    source = _make_package(tmp_path)
    archive = tmp_path / "demo.pyspkg"
    pkg.build_package(source, archive)
    assert pkg.verify_package(archive)["id"] == "org.test.demo"

    root = tmp_path / "system"
    pkg.install_package(archive, str(root))
    pkg.install_package(archive, str(root))
    assert pkg.get_package("org.test.demo", str(root))["version"] == "1.0.0"


# A payload edited after the manifest was written must be refused on the hash, not installed.
def test_hash_mismatch_is_rejected(tmp_path):
    source = _make_package(tmp_path)
    script = source / "payload" / "demo.py"
    script.write_text("print('changed')\n", encoding="utf-8")
    with pytest.raises(pkg.PackageError, match="哈希"):
        pkg.verify_package(source)


# A zip member escaping the extraction root is refused, since trusting it writes outside the system tree.
def test_zip_path_traversal_is_rejected(tmp_path):
    archive = tmp_path / "bad.pyspkg"
    manifest = {
        "format": 1,
        "id": "org.test.bad",
        "version": "1.0.0",
        "entrypoints": [{
            "name": "bad",
            "runtime": "python",
            "path": "payload/bad.py",
        }],
        "files": {},
    }
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("package.json", json.dumps(manifest))
        package.writestr("payload/bad.py", "print('bad')\n")
        package.writestr("../escape.py", "print('escape')\n")
    with pytest.raises(pkg.PackageError, match="路径不安全"):
        pkg.verify_package(archive)


# A package may not claim a command name the shell reserves.
def test_command_conflict_is_rejected(tmp_path):
    source = _make_package(tmp_path, command="ls")
    with pytest.raises(pkg.PackageError, match="冲突"):
        pkg.install_package(source, str(tmp_path / "system"),
                             reserved_commands={"ls"})


# A user package is an external app: pkg install works under ROOT and its command runs the installed entrypoint.
def test_pkg_is_an_external_app_and_runs_installed_entrypoint(tmp_path, monkeypatch, capsys):
    sys._launcher_detected = True
    sys.path.insert(0, str(REPO / "src"))
    import main

    monkeypatch.chdir(REPO / "src")
    monkeypatch.setattr(main, "root_dir", str(tmp_path / "system"))
    monkeypatch.setattr(main, "rootstate", True)
    monkeypatch.setattr(main, "boot_locked", False)
    source = str(REPO / "examples" / "greeter")

    main.handle_command("pkg list")
    assert "没有已安装的用户包" in capsys.readouterr().out

    main.handle_command(f"pkg install {source}")
    output = capsys.readouterr().out
    assert "已安装: org.pyspos.greeter@1.0.0" in output

    main.handle_command("pkg list")
    assert "org.pyspos.greeter" in capsys.readouterr().out

    main.handle_command("greeter PySpOS")
    assert "你好，PySpOS！这是 PySpOS 用户包。" in capsys.readouterr().out


# Installing without ROOT is refused and leaves no package directory behind.
def test_pkg_install_requires_root(tmp_path, monkeypatch, capsys):
    sys._launcher_detected = True
    sys.path.insert(0, str(REPO / "src"))
    import main

    monkeypatch.chdir(REPO / "src")
    monkeypatch.setattr(main, "root_dir", str(tmp_path / "system"))
    monkeypatch.setattr(main, "rootstate", False)
    monkeypatch.setattr(main, "boot_locked", False)
    monkeypatch.setitem(main.bootcfg, "rootstate", False)
    source = str(REPO / "examples" / "greeter")

    main.handle_command(f"pkg install {source}")
    assert "需要 ROOT" in capsys.readouterr().out
    assert not (tmp_path / "system" / "etc" / "packages").exists()
