"""Shared bootstrap and isolation for the whole regression suite."""

import sys
from pathlib import Path

import pytest

from tests.support import REPO

sys._launcher_detected = True


@pytest.fixture(autouse=True)
def isolated_host_state(monkeypatch, tmp_path):
    """Keep cwd and host history changes inside this test's lifetime."""
    monkeypatch.chdir(REPO)
    # Factory reset clears ~/.pyspos_history. Never point it at a developer's home.
    host_home = tmp_path / "host-home"
    host_home.mkdir()
    monkeypatch.setenv("HOME", str(host_home))
    monkeypatch.setenv("USERPROFILE", str(host_home))
    import common.reset as reset
    monkeypatch.setattr(reset, "READLINE_HISTORY", str(host_home / ".pyspos_history"))


def pytest_collection_modifyitems(items):
    integration = {
        "process/test_fork_exec.py", "process/test_fork_stdio_relay.py",
        "shell/test_hostexec.py", "ui/test_fastboot_gui.py", "ota/test_fastboot.py",
    }
    for item in items:
        relative = Path(item.path).relative_to(REPO / "tests").as_posix()
        if relative in integration:
            item.add_marker(pytest.mark.integration)
