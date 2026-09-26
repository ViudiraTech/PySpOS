'''
 *
 *      test_spc.py
 *      SpaceConfig parse and serialize roundtrip.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import sys

sys.path.insert(0, "src")
import spc


# Sections and typed values survive a dumps plus loads roundtrip unchanged.
def test_loads_dumps_roundtrip():
    text = """
# 注释
[boot]
locked = true
rootstate = false
count = 42
ratio = 1.5
name = hello world
[net]
host = "example.com"
"""
    data = spc.loads(text)
    assert data["boot"]["locked"] is True
    assert data["boot"]["count"] == 42
    assert data["boot"]["ratio"] == 1.5
    assert data["boot"]["name"] == "hello world"
    assert data["net"]["host"] == "example.com"
    again = spc.loads(spc.dumps(data))
    assert again == data


# The legacy bootcfg checksum is dropped on the way to SPC, and both flags survive the way back.
def test_bootcfg_convert():
    bootcfg = {"locked": True, "rootstate": False, "checksum": "xxx"}
    data = spc.bootcfg_to_spc(bootcfg)
    assert "checksum" not in data["boot"]
    back = spc.spc_to_bootcfg(data)
    assert back["locked"] is True and back["rootstate"] is False


# dump writes a file that load reads back with the same value.
def test_dump_load_file(tmp_path):
    p = tmp_path / "boot.spc"
    spc.dump({"boot": {"locked": False}}, str(p))
    assert spc.load(str(p))["boot"]["locked"] is False
