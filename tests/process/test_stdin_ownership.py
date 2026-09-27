'''
 *
 *      test_stdin_ownership.py
 *      PTY regression for exited app relays consuming shell typeahead.
 *
 *      2026/9/27 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import os
import select
import subprocess
import sys
import time

import pytest

from tests.support import SRC


# Run a real terminal with several foreground children and type before each prompt.
@pytest.mark.integration
@pytest.mark.skipif(os.name != "posix", reason="requires a POSIX PTY")
def test_exited_apps_do_not_steal_shell_input(tmp_path):
    import pty
    apps = tmp_path / "apps"
    apps.mkdir()
    (apps / "quick.py").write_text("def main():\n    print('child finished', flush=True)\n")
    (apps / "answer.py").write_text("def main():\n    print('ANSWER-READY', flush=True)\n    print('ANSWER=' + input(), flush=True)\n")
    script = tmp_path / "session.py"
    script.write_text(
        "import sys, time, forkexec, process\n"
        "sys._launcher_detected = True\n"
        "process.boot_system()\n"
        "for i in range(5):\n"
        "    pcb = forkexec.fork_exec('app:quick.py', src_dir=sys.argv[1])\n"
        "    assert forkexec.wait(pcb.pid, timeout=5).exit_code == 0\n"
        "    print('SHELL-READY-' + str(i), flush=True)\n"
        "    time.sleep(0.1)\n"
        "    print('LINE=' + input('command> '), flush=True)\n"
        "    assert not forkexec._input_relays\n"
        "pcb = forkexec.fork_exec('app:answer.py', src_dir=sys.argv[1])\n"
        "assert forkexec.wait(pcb.pid, timeout=5).exit_code == 0\n"
        "print('FINAL-READY', flush=True)\n"
        "print('FINAL=' + input(), flush=True)\n")
    master, slave = pty.openpty()
    child = subprocess.Popen([sys.executable, str(script), str(tmp_path)],
                             stdin=slave, stdout=slave, stderr=slave,
                             env={**os.environ, "PYTHONPATH": str(SRC)})
    os.close(slave)
    transcript = bytearray()

    # Read until a marker without depending on one PTY read per printed line.
    def until(marker):
        deadline = time.monotonic() + 8
        while marker not in transcript and time.monotonic() < deadline:
            if select.select([master], [], [], 0.1)[0]:
                try:
                    transcript.extend(os.read(master, 65536))
                except OSError:
                    break
        assert marker in transcript, transcript.decode(errors="replace")

    try:
        for index in range(5):
            until(f"SHELL-READY-{index}".encode())
            command = f"echo 完整输入-{index}-abcdef0123456789"
            os.write(master, (command + "\n").encode())
            until(("LINE=" + command).encode())
        until(b"ANSWER-READY")
        os.write(master, "应用输入保留完整\n".encode())
        until("ANSWER=应用输入保留完整".encode())
        until(b"FINAL-READY")
        os.write(master, b"final-command\n")
        until(b"FINAL=final-command")
        assert child.wait(timeout=3) == 0
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
        os.close(master)
