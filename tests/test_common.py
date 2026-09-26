'''
 *
 *      test_common.py
 *      Common path resolution plus the open sandbox with the full builtin set.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import os
import sys

sys.path.insert(0, "src")


# The root is the src tree itself, and an unreadable current_slot falls back to slot_a instead of raising.
def test_common_paths():
    from common.paths import get_root_dir, read_current_slot
    here_src = os.path.join(os.getcwd(), "src")
    assert get_root_dir(here_src) == os.getcwd()
    assert get_root_dir("/tmp/xyz") == "/tmp/xyz"
    assert read_current_slot("/nonexistent-dir") == "slot_a"


# open hello must resolve apps/ through get_app_path() and run with the complete builtin set, not report an undefined name.
def test_open_apps_have_full_builtins():
    import contextlib
    import io
    import os
    import main
    old = os.getcwd()
    # open hello resolves apps/ through get_app_path(), so it has to run from src
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
