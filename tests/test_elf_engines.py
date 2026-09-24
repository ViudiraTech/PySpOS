"""ELF 双引擎：unicorn 默认 + 自研引擎兜底，输出一致且 exit 0。"""
import os
import sys

sys.path.insert(0, "src")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ELF_SIMPLE = os.path.join(ROOT, "splibc", "test_simple.elf")
ELF_SPLIBC = os.path.join(ROOT, "splibc", "test_splibc.elf")


def _need_elfs():
    import pytest
    if not (os.path.exists(ELF_SIMPLE) and os.path.exists(ELF_SPLIBC)):
        pytest.skip("splibc/*.elf 不存在")


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
