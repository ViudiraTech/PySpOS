"""公共路径解析 + open 沙箱回归（builtins 完整）。"""
import os
import sys

sys.path.insert(0, "src")


def test_common_paths():
    from common.paths import get_root_dir, read_current_slot
    here_src = os.path.join(os.getcwd(), "src")
    assert get_root_dir(here_src) == os.getcwd()
    assert get_root_dir("/tmp/xyz") == "/tmp/xyz"
    assert read_current_slot("/nonexistent-dir") == "slot_a"


def test_open_apps_have_full_builtins():
    import contextlib
    import io
    import os
    import main
    old = os.getcwd()
    # open hello 经 get_app_path() 解析 apps 目录，需在 src 下运行
    os.chdir(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main.handle_command("open hello")
        out = buf.getvalue()
    finally:
        os.chdir(old)
    assert "Hello from apps/hello.py" in out
    assert "is not defined" not in out
