"""SPC v2：转义/行尾注释/null/列表/Schema/工具命令；旧文件逐字兼容。"""
import contextlib
import io
import sys

sys.path.insert(0, "src")
import spc


def test_escapes_roundtrip():
    data = spc.loads('[s]\npath = "C:\\\\temp\\\\a\\"b\\n"\n')
    assert data["s"]["path"] == 'C:\\temp\\a"b\n'
    assert spc.loads(spc.dumps(data)) == data


def test_inline_comments():
    text = ("[s]\n"
            "a = 1 # comment\n"
            "b = x#y ; kept\n"
            'c = "a#b" # tail\n'
            "# full line\n"
            "; full line\n")
    data = spc.loads(text)
    assert data["s"] == {"a": 1, "b": "x#y", "c": "a#b"}


def test_null_forms():
    data = spc.loads("[s]\na = null\nb = none\nc = ~\nd = \ne = \"\"\n")
    assert data["s"] == {"a": None, "b": None, "c": None, "d": None, "e": ""}


def test_lists():
    data = spc.loads('[s]\nnums = [1, 2, 3]\nmix = [1, "a, b", true, null]\n')
    assert data["s"]["nums"] == [1, 2, 3]
    assert data["s"]["mix"] == [1, "a, b", True, None]
    assert spc.loads(spc.dumps(data)) == data


def test_v1_files_parse_identically():
    # v1 风格文件在 v2 下解析结果必须一致（格式稳定承诺）
    text = '[boot]\nlocked = true\nrootstate = false\ncount = 42\nratio = 1.5\nname = hello\n'
    assert spc.loads(text) == {
        "default": {}, "boot": {"locked": True, "rootstate": False,
                                "count": 42, "ratio": 1.5, "name": "hello"}}


def _schema():
    return {"boot": {"locked": {"type": "bool", "required": True},
                     "retries": {"type": "int", "min": 0, "max": 5, "default": 3},
                     "mode": {"type": "str", "choices": ["a", "b"]}}}


def test_schema_valid_and_defaults():
    data = {"boot": {"locked": True}}
    assert [i for i in spc.validate(data, _schema()) if i.level == "error"] == []
    filled = spc.apply_defaults(data, _schema())
    assert filled["boot"]["retries"] == 3
    assert data["boot"].get("retries") is None  # 不修改输入


def test_schema_errors_with_lineno():
    text = "[boot]\nlocked = yesplease\nretries = 99\n"
    data, meta = spc.loads(text, with_meta=True)
    issues = spc.validate(data, _schema(), meta)
    by_key = {(i.section, i.key): i for i in issues if i.level == "error"}
    assert by_key[("boot", "locked")].code == "TYPE_MISMATCH"
    assert by_key[("boot", "locked")].lineno == 2
    assert by_key[("boot", "retries")].code == "OUT_OF_RANGE"
    try:
        spc.ensure_valid(data, _schema(), meta)
        assert False, "应抛 SPCSchemaError"
    except spc.SPCSchemaError as e:
        assert len(e.issues) >= 2


def test_schema_missing_required_and_unknown_warning():
    issues = spc.validate({"boot": {"mystery": 1}}, _schema())
    codes = {(i.code, i.level) for i in issues}
    assert ("MISSING_REQUIRED", "error") in codes
    assert ("UNKNOWN_KEY", "warning") in codes


def _run(cmd):
    import main
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main.handle_command(cmd)
    return buf.getvalue()


def test_shell_validate_get_set(tmp_path):
    good = tmp_path / "good.spc"
    good.write_text("[boot]\nlocked = true\nrootstate = false\n", encoding="utf-8")
    out = _run(f"spc_validate {good}")
    assert "校验通过" in out
    bad = tmp_path / "bad.spc"
    bad.write_text("[boot]\nlocked = yesplease\n", encoding="utf-8")
    out = _run(f"spc_validate {bad}")
    assert "TYPE_MISMATCH" in out or "类型应为" in out

    target = tmp_path / "w.spc"
    out = _run(f"spc_set net.host example.com {target}")
    assert "已写入" in out
    out = _run(f"spc_get net.host {target}")
    assert "example.com" in out
    out = _run(f"spc_set nums.list [1, 2] {target}")
    assert "已写入" in out
    assert spc.load(str(target))["nums"]["list"] == [1, 2]


def test_shell_migrate_roundtrip(tmp_path):
    import json
    j = tmp_path / "bootcfg.json"
    j.write_text('{"locked": true, "rootstate": false}', encoding="utf-8")
    s = tmp_path / "bootcfg.spc"
    out = _run(f"spc_migrate json2spc {j} {s}")
    assert "已迁移" in out
    assert spc.load(str(s))["boot"]["locked"] is True
    j2 = tmp_path / "back.json"
    out = _run(f"spc_migrate spc2json {s} {j2}")
    assert "已迁移" in out
    back = json.loads(j2.read_text(encoding="utf-8"))
    assert back["locked"] is True and "checksum" in back
