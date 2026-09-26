'''
 *
 *      test_elf_engines.py
 *      ELF engines: unicorn by default, the in-house engine as fallback, same output and exit 0.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import os
import sys

sys.path.insert(0, "src")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ELF_SIMPLE = os.path.join(ROOT, "splibc", "test_simple.elf")
ELF_SPLIBC = os.path.join(ROOT, "splibc", "test_splibc.elf")


# Skip rather than fail when the prebuilt splibc binaries are missing.
def _need_elfs():
    import pytest
    if not (os.path.exists(ELF_SIMPLE) and os.path.exists(ELF_SPLIBC)):
        pytest.skip("splibc/*.elf 不存在")


# Unicorn must load the trivial ELF and run it to exit 0 with the expected stdout.
def test_unicorn_simple():
    _need_elfs()
    from elf_loader.unicorn_runner import UnicornRunner, unicorn_available
    import pytest
    if not unicorn_available():
        pytest.skip("unicorn 未安装")
    r = UnicornRunner(ELF_SIMPLE)
    assert r.load()
    res = r.run(max_instructions=2000000)
    assert res.exit_code == 0, res.stderr
    assert "Hello from SpLibC" in res.stdout


# The heavier splibc binary must also reach exit 0 under unicorn within the instruction cap.
def test_unicorn_splibc():
    _need_elfs()
    from elf_loader.unicorn_runner import UnicornRunner, unicorn_available
    import pytest
    if not unicorn_available():
        pytest.skip("unicorn 未安装")
    r = UnicornRunner(ELF_SPLIBC)
    assert r.load()
    res = r.run(max_instructions=2000000)
    assert res.exit_code == 0, res.stderr
    assert "splibc" in res.stdout


# The in-house engine must give the same stdout and exit 0, so the fallback is truly interchangeable.
def test_native_fallback_simple():
    _need_elfs()
    import logging
    logging.disable(logging.CRITICAL)
    from elf_loader import ELFRunner
    r = ELFRunner(ELF_SIMPLE)
    assert r.load()
    res = r.run(max_instructions=2000000)
    assert res.exit_code == 0
    assert "Hello from SpLibC" in res.stdout


# run must pick unicorn by default and name the engine it used in its output.
def test_shell_run_uses_unicorn_by_default():
    _need_elfs()
    import contextlib
    import io
    import main
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main.handle_command("run --stats %s" % ELF_SIMPLE)
    out = buf.getvalue()
    assert "Hello from SpLibC" in out
    assert "unicorn" in out
