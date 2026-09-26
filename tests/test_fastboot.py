'''
 *
 *      test_fastboot.py
 *      Tests for the PySpOS fastboot protocol server and host client.
 *
 *      2026/9/26 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import os
import socket
import threading

import pytest

import fastboot


# Run one request against a bare handler and return the reply line.
def ask(command):
    return fastboot.handle_command(command)


# A fake client that speaks the protocol over a real loopback socket.
class WireClient:
    def __init__(self, port):
        self.sock = socket.create_connection(("127.0.0.1", port), 5.0)
        self.buffer = b""

    def readline(self):
        while b"\n" not in self.buffer:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise OSError("closed")
            self.buffer += chunk
        line, self.buffer = self.buffer.split(b"\n", 1)
        return line.decode().strip()

    def send(self, command):
        self.sock.sendall((command + "\n").encode())
        return self.readline()

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


# Start the server on an ephemeral port and hand the port to the caller.
def start_server(monkeypatch, tmp_path):
    monkeypatch.setattr(fastboot.main, "root_dir", str(tmp_path))
    monkeypatch.setattr(fastboot, "is_locked", lambda: False)
    port = 0
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    thread = threading.Thread(
        target=fastboot.fastboot_main, args=("test", port), daemon=True)
    thread.start()
    return port, thread


# Wait until the server accepts connections, so tests never race the bind.
def wait_for(port, attempts=100):
    import time
    for _ in range(attempts):
        try:
            conn = socket.create_connection(("127.0.0.1", port), 0.2)
            conn.close()
            return True
        except OSError:
            time.sleep(0.05)
    return False


def test_getvar_version():
    assert ask("getvar:version") == f"OKAY{fastboot.PROTOCOL_VERSION}"


def test_getvar_unknown_fails():
    assert ask("getvar:definitely-not-a-var").startswith("FAIL")


def test_getvar_bare_uses_version():
    assert ask("getvar") == f"OKAY{fastboot.PROTOCOL_VERSION}"


def test_variables_expose_core_fields():
    values = fastboot.collect_variables()
    for key in ("version", "product", "unlocked", "current-slot",
                "slot-count", "max-download-size"):
        assert key in values
    assert values["product"] == "PySpOS"
    assert values["slot-count"] == "2"


def test_download_reports_data_size():
    reply = ask("download:00001000")
    assert reply == "DATA00001000"
    assert int(reply[4:], 16) == 0x1000


def test_download_rejects_bad_size():
    assert ask("download:zzzz").startswith("FAIL")
    assert ask(f"download:{fastboot.MAX_DOWNLOAD_SIZE + 1:x}").startswith("FAIL")


def test_flash_without_download_fails():
    fastboot.reset_state()
    assert ask("flash:slot_a").startswith("FAIL")


def test_flash_unknown_partition_fails():
    fastboot.reset_state()
    fastboot.stage_bytes(b"payload")
    reply = ask("flash:not-a-slot")
    assert reply.startswith("FAIL")


def test_locked_device_refuses_flash_and_erase(monkeypatch):
    monkeypatch.setattr(fastboot, "is_locked", lambda: True)
    fastboot.reset_state()
    fastboot.stage_bytes(b"payload")
    assert ask("flash:slot_a").startswith("FAIL")
    assert ask("erase:slot_a").startswith("FAIL")


def test_erase_unknown_partition_fails(monkeypatch):
    monkeypatch.setattr(fastboot, "is_locked", lambda: False)
    assert ask("erase:not-a-slot").startswith("FAIL")


def test_boot_without_download_fails():
    fastboot.reset_state()
    assert ask("boot").startswith("FAIL")


def test_boot_with_download_targets_system():
    fastboot.reset_state()
    fastboot.stage_bytes(b"payload")
    assert ask("boot").startswith("OKAY")
    # The image is never executed from fastboot: it stays staged, so the boot
    # goes to the system and the verified installer still has to run.
    assert fastboot.take_pending_boot() == "system"


def test_continue_sets_pending_system():
    fastboot.reset_state()
    assert ask("continue").startswith("OKAY")
    assert fastboot.take_pending_boot() == "system"


def test_reboot_sets_pending():
    fastboot.reset_state()
    assert ask("reboot") == "OKAY"
    assert fastboot.take_pending_boot() == "reboot"


def test_reboot_bootloader_sets_pending():
    fastboot.reset_state()
    assert ask("reboot-bootloader") == "OKAY"
    assert fastboot.take_pending_boot() == "reboot"


def test_powerdown_sets_pending():
    fastboot.reset_state()
    assert ask("powerdown") == "OKAY"
    assert fastboot.take_pending_boot() == "poweroff"


def test_flashing_usage_error():
    assert ask("flashing").startswith("FAIL")
    assert ask("flashing bogus").startswith("FAIL")


def test_unknown_command_fails():
    assert ask("definitely-not-a-command").startswith("FAIL")


def test_oem_process_list_is_single_line(monkeypatch):
    fastboot.reset_state()
    reply = ask("oem pyspos-ps")
    assert reply.startswith("OKAY")
    assert "\n" not in reply


def test_oem_signal_requires_arguments(monkeypatch):
    assert ask("oem pyspos-signal").startswith("FAIL")
    assert ask("oem pyspos-signal 1").startswith("FAIL")


def test_oem_signal_rejects_bad_pid(monkeypatch):
    assert ask("oem pyspos-signal notapid SIGTERM").startswith("FAIL")


def test_oem_signal_rejects_unknown_signal(monkeypatch):
    assert ask("oem pyspos-signal 1 SIGNOPE").startswith("FAIL")


def test_oem_unknown_command_fails():
    assert ask("oem something-else").startswith("FAIL")


def test_oem_empty_fails():
    assert ask("oem").startswith("FAIL")


def test_staging_round_trip():
    fastboot.reset_state()
    assert fastboot.staged_size() == 0
    fastboot.stage_bytes(b"abcdef")
    assert fastboot.staged_size() == 6
    assert fastboot.staged_bytes() == b"abcdef"


def test_staged_bytes_returns_copy():
    fastboot.reset_state()
    fastboot.stage_bytes(b"abc")
    copy = fastboot.staged_bytes()
    copy += b"d"
    assert fastboot.staged_bytes() == b"abc"


def test_reset_state_clears_pending():
    fastboot.reset_state()
    fastboot.stage_bytes(b"x")
    fastboot.set_pending_boot("reboot")
    fastboot.reset_state()
    assert fastboot.staged_size() == 0
    assert fastboot.take_pending_boot() is None


def test_signal_numbers_cover_gui_choices():
    from fastboot_gui import SIGNALS
    assert set(SIGNALS) == set(fastboot.SIGNAL_NUMBERS)


def test_wire_round_trip(monkeypatch, tmp_path):
    port, _thread = start_server(monkeypatch, tmp_path)
    assert wait_for(port)
    client = WireClient(port)
    try:
        assert client.send("getvar:version") == f"OKAY{fastboot.PROTOCOL_VERSION}"
        assert client.send("download:00000004") == "DATA00000004"
        client.sock.sendall(b"abcd")
        assert client.readline() == "OKAY"
        assert client.send("oem pyspos-ps").startswith("OKAY")
    finally:
        client.close()
    fastboot.reset_state()


def test_wire_reboot_ends_session(monkeypatch, tmp_path):
    port, _thread = start_server(monkeypatch, tmp_path)
    assert wait_for(port)
    client = WireClient(port)
    try:
        assert client.send("reboot") == "OKAY"
        with pytest.raises(OSError):
            client.readline()
    finally:
        client.close()
    fastboot.reset_state()


# Sign a locked policy with the device key, the way fastboot lock does, so the
# scratch device starts in a real trust state.
def seed_locked_policy(root):
    import secure_boot
    secure_boot.ensure_developer_key(root, locked=False)
    secure_boot.write_policy(root, True, 1, fastboot.device_key_path(),
                             fastboot._device_trusted_keys())
    secure_boot.configure_runtime_keys(root, True)


def test_unlock_then_lock_round_trip(monkeypatch, tmp_path):
    root = str(tmp_path)
    for name in ("slot_a", "slot_b"):
        os.makedirs(os.path.join(root, name), exist_ok=True)
    monkeypatch.setattr(fastboot.main, "root_dir", root)
    monkeypatch.setattr(fastboot, "is_locked", lambda: secure_boot_read_locked(root))
    seed_locked_policy(root)
    assert fastboot.is_locked() is True

    ok, message = fastboot.perform_unlock()
    assert ok, message
    # The unlocked policy must be readable, otherwise the device would look
    # locked again on the next query.
    assert fastboot.is_locked() is False
    # AOSP wipes user data on unlock, but the signed slots must survive or the
    # device would have nothing left to boot.
    assert os.path.isdir(os.path.join(root, "slot_a"))
    assert os.path.isdir(os.path.join(root, "slot_b"))
    assert not os.path.isdir(os.path.join(root, "etc"))

    ok, message = fastboot.perform_lock()
    # Locking needs a signed active slot: an unsigned dev slot would leave the
    # device unable to boot, exactly like locking a phone after flashing
    # unsigned images.
    assert ok is False
    assert "签名" in message


def test_lock_allowed_when_active_slot_is_signed(monkeypatch, tmp_path):
    root = str(tmp_path)
    for name in ("slot_a", "slot_b"):
        os.makedirs(os.path.join(root, name), exist_ok=True)
    monkeypatch.setattr(fastboot.main, "root_dir", root)
    monkeypatch.setattr(fastboot, "is_locked", lambda: secure_boot_read_locked(root))
    seed_locked_policy(root)
    monkeypatch.setattr(fastboot, "active_slot_is_signed", lambda: True)
    ok, message = fastboot.perform_lock()
    assert ok, message
    assert fastboot.is_locked() is True


def secure_boot_read_locked(root):
    import secure_boot
    return secure_boot.read_locked(root, fastboot._device_trusted_keys())


def test_locked_device_refuses_flash_by_default(monkeypatch, tmp_path):
    root = str(tmp_path)
    for name in ("slot_a", "slot_b"):
        os.makedirs(os.path.join(root, name), exist_ok=True)
    monkeypatch.setattr(fastboot.main, "root_dir", root)
    seed_locked_policy(root)
    fastboot.reset_state()
    fastboot.stage_bytes(b"payload")
    assert fastboot.handle_command("flash:slot_a").startswith("FAILdevice is locked")


def test_flash_writes_staged_bytes_when_unlocked(monkeypatch, tmp_path):
    root = str(tmp_path)
    for name in ("slot_a", "slot_b"):
        os.makedirs(os.path.join(root, name), exist_ok=True)
    monkeypatch.setattr(fastboot.main, "root_dir", root)
    monkeypatch.setattr(fastboot, "is_locked", lambda: False)
    fastboot.reset_state()
    fastboot.stage_bytes(b"IMAGE-DATA")
    reply = fastboot.handle_command("flash:slot_b")
    assert reply.startswith("OKAY")
    # The image must land in the OTA staging area, never inside a slot: the
    # signed manifest covers every slot file and an extra one would brick it.
    staged = fastboot.staging_path()
    assert os.path.isfile(staged)
    with open(staged, "rb") as handle:
        assert handle.read() == b"IMAGE-DATA"
    assert not os.path.exists(os.path.join(root, "slot_b", "update.zip"))


def test_erase_never_deletes_a_slot(monkeypatch, tmp_path):
    root = str(tmp_path)
    for name in ("slot_a", "slot_b"):
        os.makedirs(os.path.join(root, name), exist_ok=True)
    monkeypatch.setattr(fastboot.main, "root_dir", root)
    monkeypatch.setattr(fastboot, "is_locked", lambda: False)
    # Erasing a slot name wipes user data instead of the signed system image.
    fastboot.perform_erase("slot_a")
    assert os.path.isdir(os.path.join(root, "slot_a"))
    assert os.path.isdir(os.path.join(root, "slot_b"))


def test_erase_unknown_target_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(fastboot.main, "root_dir", str(tmp_path))
    ok, _message = fastboot.perform_erase("not-a-partition")
    assert ok is False


def test_bind_server_succeeds_on_a_free_port():
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    server, error = fastboot._bind_server(port, attempts=1, delay=0)
    assert error is None
    assert server is not None
    server.close()


def test_bind_server_reports_an_occupied_port():
    # An occupied port is the reason a previous run appears to skip fastboot,
    # so the failure has to surface instead of silently returning to the shell.
    holder = socket.socket()
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    port = holder.getsockname()[1]
    try:
        server, error = fastboot._bind_server(port, attempts=2, delay=0)
        assert server is None
        assert isinstance(error, OSError)
    finally:
        holder.close()


def test_fastboot_main_reports_a_bind_failure(monkeypatch, capsys):
    monkeypatch.setattr(fastboot.kernel, "screen_clear", lambda: None)
    monkeypatch.setattr(fastboot, "is_locked", lambda: False)
    monkeypatch.setattr(fastboot, "_bind_server", lambda *a, **k: (None, OSError("busy")))
    assert fastboot.fastboot_main("test") == "reboot"
    out = capsys.readouterr().out
    assert "已被另一个 PySpOS 实例占用" in out
    assert "fastboot --port" in out


def test_leave_boot_mode_reboots_for_real(monkeypatch):
    # The client's reboot button used to do nothing visible: fastboot_main's
    # return value was dropped, so the device fell back to the shell prompt.
    from shell import sys_cmds
    triggered = []
    monkeypatch.setenv("PYSPOS_HOTRESET_SUPERVISED", "1")
    monkeypatch.setattr("hotreset_env.trigger", lambda: triggered.append(True))
    sys_cmds._leave_boot_mode("reboot")
    assert triggered == [True]


def test_leave_boot_mode_powers_off(monkeypatch):
    from shell import sys_cmds
    called = []
    monkeypatch.setattr(sys_cmds.kernel, "exit", lambda: called.append(True))
    sys_cmds._leave_boot_mode("poweroff")
    assert called == [True]


def test_leave_boot_mode_without_supervisor_warns(monkeypatch, capsys):
    from shell import sys_cmds
    monkeypatch.delenv("PYSPOS_HOTRESET_SUPERVISED", raising=False)
    monkeypatch.setattr("hotreset_env.trigger",
                        lambda: pytest.fail("must not trigger"))
    sys_cmds._leave_boot_mode("reboot")
    assert "没有热重启监督进程" in capsys.readouterr().out


def test_leave_boot_mode_ignores_unknown_action(monkeypatch):
    from shell import sys_cmds
    monkeypatch.setattr("hotreset_env.trigger",
                        lambda: pytest.fail("must not trigger"))
    sys_cmds._leave_boot_mode("something-else")


def test_cmd_fastboot_honours_the_leave_action(monkeypatch):
    # Entering fastboot from the shell must still honour what the client asked
    # for. Dropping this return value is why reboot looked like a no-op.
    from shell import sys_cmds
    triggered = []
    monkeypatch.setattr(fastboot, "fastboot_main", lambda *_a, **_k: "reboot")
    monkeypatch.setenv("PYSPOS_HOTRESET_SUPERVISED", "1")
    monkeypatch.setattr("hotreset_env.trigger", lambda: triggered.append(True))
    sys_cmds.cmd_fastboot("")
    assert triggered == [True]


def test_cmd_fastboot_powers_off_on_request(monkeypatch):
    from shell import sys_cmds
    called = []
    monkeypatch.setattr(fastboot, "fastboot_main", lambda *_a, **_k: "poweroff")
    monkeypatch.setattr(sys_cmds.kernel, "exit", lambda: called.append(True))
    sys_cmds.cmd_fastboot("")
    assert called == [True]


def test_cmd_fastboot_rejects_a_bad_port(monkeypatch, capsys):
    from shell import sys_cmds
    monkeypatch.setattr(fastboot, "fastboot_main",
                        lambda *_a, **_k: pytest.fail("must not serve"))
    sys_cmds.cmd_fastboot("--port not-a-number")
    assert "用法：fastboot" in capsys.readouterr().out
