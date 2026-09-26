'''
 *
 *      test_fastfetch_cmd.py
 *      Tests for the fastfetch branding wrapper.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import contextlib
import io
import json
import os
import stat
import sys

sys.path.insert(0, "src")
import main
import proc
from shell import fastfetch_cmd, shexec


def run(cmd):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main.handle_command(cmd)
    return buf.getvalue()


def setup_function(_):
    proc.reset()
    shexec.reset_state()


def _fake_fastfetch(path, body='import sys;print("FAKE " + " ".join(sys.argv[1:]))'):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("#!/usr/bin/env python3\n" + body + "\n")
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)


def test_missing_binary_reports_gracefully(monkeypatch):
    monkeypatch.setattr(fastfetch_cmd, "real_binary", lambda: None)
    out = run("fastfetch")
    assert "没有安装" in out


def test_branding_flags_injected(tmp_path, monkeypatch, capfd):
    fake = tmp_path / "fastfetch"
    _fake_fastfetch(str(fake))
    monkeypatch.setattr(fastfetch_cmd, "real_binary", lambda: str(fake))
    run("fastfetch")
    captured = capfd.readouterr()
    assert "--config" in captured.out
    assert "data-raw" in captured.out
    assert "pyspos-fastfetch.jsonc" in captured.out


def test_user_logo_wins(tmp_path, monkeypatch, capfd):
    fake = tmp_path / "fastfetch"
    _fake_fastfetch(str(fake))
    monkeypatch.setattr(fastfetch_cmd, "real_binary", lambda: str(fake))
    run("fastfetch --logo arch")
    captured = capfd.readouterr()
    assert "--logo arch" in captured.out
    assert "data-raw" not in captured.out


def test_config_cache_content(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    import tempfile
    tempfile.tempdir = None
    import subprocess
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: type("P", (), {"stdout": "Title:OS:Shell:Memory"})())
    path = fastfetch_cmd.config_path("9.9", "x86_64", "/usr/bin/fastfetch")
    assert path is not None
    with open(path, encoding="utf-8") as handle:
        config = json.load(handle)
    assert config["modules"][0] == "Title"
    formats = {m["type"]: m["format"] for m in config["modules"]
               if isinstance(m, dict)}
    assert formats["shell"] == "PySpOS shell 9.9"
    assert formats["os"] == "PySpOS 9.9 x86_64"
    assert "Memory" in config["modules"]
    tempfile.tempdir = None


def test_scan_args():
    assert fastfetch_cmd.scan_args(["--logo", "x"]) == (True, False, False)
    assert fastfetch_cmd.scan_args(["-c", "f"]) == (False, True, False)
    assert fastfetch_cmd.scan_args(["-s", "a:b"]) == (False, False, True)
    assert fastfetch_cmd.scan_args(["--structure=X"]) == (False, False, True)
    assert fastfetch_cmd.scan_args(["--logo-type", "data"]) == (True, False, False)
    assert fastfetch_cmd.scan_args([]) == (False, False, False)
