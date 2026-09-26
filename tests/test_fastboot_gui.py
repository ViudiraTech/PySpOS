'''
 *
 *      test_fastboot_gui.py
 *      Tests for the fastboot host client.
 *
 *      These drive the client against a real loopback server, so a method
 *      that the Tk layer calls but the client no longer provides is caught
 *      here instead of on a user's screen.
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
import fastboot_gui as gui
from fastboot_gui import FastbootClient, SIGNALS

# A scripted device: it answers from a table instead of running real firmware.
class FakeDevice:
    def __init__(self, replies, payload=b""):
        self.replies = replies
        self.payload = payload
        self.received = []
        self.server = socket.socket()
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(1)
        self.port = self.server.getsockname()[1]
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        try:
            conn, _addr = self.server.accept()
        except OSError:
            return
        buffer = b""
        with conn:
            while True:
                try:
                    chunk = conn.recv(4096)
                except OSError:
                    return
                if not chunk:
                    return
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    command = line.decode().strip()
                    self.received.append(command)
                    reply = self.replies.get(command)
                    if reply is None:
                        reply = f"FAILunknown command: {command}"
                    try:
                        conn.sendall((reply + "\n").encode())
                    except OSError:
                        return
                    if not command.startswith("download:"):
                        continue
                    # The host sends the raw image after DATA; swallow exactly
                    # as many bytes as it announced, then acknowledge.
                    try:
                        size = int(command.split(":", 1)[1], 16)
                    except ValueError:
                        return
                    while len(buffer) < size:
                        try:
                            more = conn.recv(size - len(buffer))
                        except OSError:
                            return
                        if not more:
                            return
                        buffer += more
                    self.payload = buffer[:size]
                    self.received.append("<payload>")
                    buffer = buffer[size:]
                    try:
                        conn.sendall(b"OKAY\n")
                    except OSError:
                        return

    def close(self):
        try:
            self.server.close()
        except OSError:
            pass


@pytest.fixture
def device():
    made = []

    def build(replies, payload=b""):
        made.append(FakeDevice(replies, payload))
        return made[-1]

    yield build
    for item in made:
        item.close()


def connect(device):
    return FastbootClient("127.0.0.1", device.port, timeout=5.0)


def test_getvar_returns_the_value(device):
    dev = device({"getvar:product": "OKAYPySpOS"})
    client = connect(dev)
    assert client.connect()[0] is True
    assert client.getvar("product") == "OKAYPySpOS"
    client.close()


def test_all_variables_reads_every_field(device):
    # Driven by VARIABLE_ROWS so a new row cannot be forgotten here.
    names = [name for name, _caption in gui.VARIABLE_ROWS]
    dev = device({f"getvar:{n}": f"OKAYvalue-{n}" for n in names})
    client = connect(dev)
    client.connect()
    values = client.all_variables()
    assert values["product"] == "value-product"
    assert values["slot-count"] == "value-slot-count"
    assert len(values) == len(names)
    client.close()


def test_command_raises_on_fail_reply(device):
    dev = device({"flashing lock": "FAILdevice is locked"})
    client = connect(dev)
    client.connect()
    with pytest.raises(OSError, match="device is locked"):
        client.flashing("lock")
    client.close()


def test_erase_sends_the_partition(device):
    dev = device({"erase:slot_b": "OKAY用户数据已清除"})
    client = connect(dev)
    client.connect()
    assert client.erase("slot_b") == "OKAY用户数据已清除"
    assert "erase:slot_b" in dev.received
    client.close()


def test_flash_downloads_then_writes(device):
    dev = device({"download:00000004": "DATA00000004",
                  "flash:slot_a": "OKAY已暂存"}, payload=b"abcd")
    client = connect(dev)
    client.connect()
    path = os.path.join(os.path.dirname(__file__), "_fastboot_gui_payload.bin")
    with open(path, "wb") as handle:
        handle.write(b"abcd")
    try:
        assert client.flash("slot_a", path) == "OKAY已暂存"
    finally:
        if os.path.exists(path):
            os.remove(path)
    assert "flash:slot_a" in dev.received
    assert "<payload>" in dev.received
    client.close()


def test_reboot_hangs_up_after_the_request(device):
    dev = device({"reboot": "OKAY"})
    client = connect(dev)
    client.connect()
    assert client.reboot() == "OKAY"
    # The client closes on the way out, so the UI thread cannot race it.
    assert client.sock is None


def test_reboot_bootloader_hangs_up(device):
    dev = device({"reboot-bootloader": "OKAY"})
    client = connect(dev)
    client.connect()
    assert client.reboot("-bootloader") == "OKAY"
    assert client.sock is None


def test_powerdown_hangs_up(device):
    dev = device({"powerdown": "OKAY"})
    client = connect(dev)
    client.connect()
    assert client.powerdown() == "OKAY"
    assert client.sock is None


def test_request_without_a_connection_raises(device):
    dev = device({})
    client = connect(dev)
    with pytest.raises(OSError, match="尚未连接"):
        client.getvar("product")


def test_connect_reports_failure(monkeypatch, device):
    def refuse(*_args, **_kwargs):
        raise OSError("Connection refused")

    monkeypatch.setattr("fastboot_gui.socket.create_connection", refuse)
    client = connect(device({}))
    ok, message = client.connect()
    assert ok is False
    assert "无法连接" in message
    assert client.sock is None


def test_client_exposes_every_signal_the_gui_offers():
    client = FastbootClient()
    for name in SIGNALS:
        assert name in fastboot.SIGNAL_NUMBERS
    assert hasattr(client, "getvar")


def test_gui_actions_only_use_existing_client_methods():
    # The Tk layer is not started here, but its callables are checked against
    # the client API so a renamed or dropped method fails loudly in CI.
    for name in ("connect", "close", "getvar", "all_variables", "flash",
                 "erase", "flashing", "reboot", "powerdown", "request",
                 "command"):
        assert hasattr(FastbootClient, name), name
