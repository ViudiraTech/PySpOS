'''
 *
 *      test_vortexglass.py
 *      Real socket protocol, ownership, bounded resources and service lifecycle.
 *
 *      2026/9/27 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time

import pytest

import process as proc
from tests.support import REPO
from vortexglass import PROTOCOL_VERSION
from vortexglass.client import Client
from vortexglass.demos import Calculator, Canvas, Clock, calculate
from vortexglass.model import Compositor, validate_scene
from vortexglass.protocol import ENDPOINT_ENV, MAX_MESSAGE, ProtocolError, decode, encode
from vortexglass.server import Server
from vortexglass.service import ServiceManager


def eventually(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    assert predicate()


@pytest.fixture(params=["unix", "tcp"] if os.name != "nt" else ["tcp"])
def server(tmp_path, request):
    built = Server(tmp_path / "endpoint.json", transport=request.param, control_token="test-control")
    built.open()
    thread = threading.Thread(target=built.run, daemon=True)
    thread.start()
    yield built
    built.stop()
    thread.join(3)
    assert not thread.is_alive()
    assert not built.endpoint.exists()
    if built.socket_path:
        assert not built.socket_path.exists()


def test_socket_roundtrip_and_scene_updates(server):
    with Client(server.endpoint) as client:
        assert client.info["version"] == PROTOCOL_VERSION
        assert client.request("ping") == {"pong": True}
        window = client.create("Socket client", 340, 220, "#00000000")
        scene = Canvas().scene(540, 340)
        assert client.present(window, scene)["revision"] == 1
        state = server.model.snapshot(window)
        assert state.items == validate_scene(scene)
        assert state.background == "#00000000"
        client.present(window, [], background="#12345680")
        assert server.model.snapshot(window).background == "#12345680"
        client.request("resize", window=window, width=420, height=280)
        assert server.model.snapshot(window).width == 420
        client.destroy(window)
        assert server.model.snapshot(window) is None


def test_other_client_cannot_modify_or_capture_a_window(server):
    with Client(server.endpoint) as first, Client(server.endpoint) as second:
        window = first.create()
        for operation, fields in (("present", {"items": []}), ("destroy", {}),
                                  ("snapshot", {}), ("resize", {"width": 200, "height": 100})):
            with pytest.raises(ProtocolError, match="belong"):
                second.request(operation, window=window, **fields)
        assert first.request("status")["owned"] == [window]
        assert second.request("status")["owned"] == []


def test_disconnect_only_reclaims_the_owners_windows(server):
    with Client(server.endpoint) as remaining:
        survivor = remaining.create()
        disposable = Client(server.endpoint)
        windows = [disposable.create() for _ in range(3)]
        disposable.close()
        eventually(lambda: all(server.model.snapshot(w) is None for w in windows))
        assert server.model.snapshot(survivor) is not None


def test_events_are_routed_to_the_owner_and_survive_reply_interleaving(server):
    with Client(server.endpoint) as first, Client(server.endpoint) as second:
        window = first.create()
        owner = server.model.snapshot(window).owner
        server.emit(owner, {"type": "click", "window": window, "target": "1"})
        first.request("ping")
        assert first.next_event(1)["target"] == "1"
        assert second.next_event(0.02) is None


def test_invalid_update_is_atomic_and_does_not_crash_service(server):
    with Client(server.endpoint) as client:
        window = client.create()
        client.present(window, [{"type": "text", "text": "unchanged"}])
        before = server.model.snapshot(window)
        for scene in ([{"type": "exec"}], [{"type": "rect", "width": -1, "height": 4}],
                      [{"type": "text", "size": True}], [{}] * 257):
            with pytest.raises(ProtocolError):
                client.present(window, scene)
            assert server.model.snapshot(window) == before
        assert client.request("ping")["pong"]


def test_limits_and_service_control_are_enforced(server):
    with Client(server.endpoint) as client:
        for _ in range(8):
            client.create()
        with pytest.raises(ProtocolError, match="limit"):
            client.create()
        with pytest.raises(ProtocolError, match="supervisor"):
            client.request("shutdown", control="wrong")
        with pytest.raises(ProtocolError, match="unknown operation"):
            client.request("run-python", source="pass")
        assert client.request("ping")["pong"]


def raw_socket(server):
    stream = socket.socket(socket.AF_UNIX if server.transport == "unix" else socket.AF_INET,
                           socket.SOCK_STREAM)
    address = str(server.socket_path) if server.transport == "unix" else server.listener.getsockname()
    stream.settimeout(2)
    stream.connect(address)
    return stream


def test_bad_authentication_closes_connection(server):
    with raw_socket(server) as stream:
        stream.sendall(encode({"id": 1, "op": "hello", "version": 1, "token": "wrong"}))
        reply = stream.makefile("rb").readline()
        assert decode(reply)["ok"] is False
        assert stream.recv(1) == b""


def test_fragmented_and_coalesced_messages(server):
    with raw_socket(server) as stream:
        hello = encode({"id": 1, "op": "hello", "version": 1, "token": server.token})
        stream.sendall(hello[:5])
        stream.sendall(hello[5:] + encode({"id": 2, "op": "ping"}) + encode({"id": 3, "op": "ping"}))
        with stream.makefile("rb") as reader:
            assert [decode(reader.readline())["id"] for _ in range(3)] == [1, 2, 3]


def test_oversized_frame_disconnects_without_affecting_other_clients(server):
    with raw_socket(server) as stream, Client(server.endpoint) as other:
        stream.sendall(b"x" * (MAX_MESSAGE + 1))
        eventually(lambda: len(server.connections) == 1)
        assert other.request("ping")["pong"]


def test_authenticated_idle_service_does_not_poll(server):
    with Client(server.endpoint) as client:
        client.request("ping")
        # Allow the selector to return to its blocking wait after the last write.
        time.sleep(0.03)
        before = server.select_calls
        time.sleep(0.12)
        assert server.select_calls == before


@pytest.mark.parametrize("message", [b"[]", b'{"x":NaN}', b'{"x":Infinity}', b"not JSON"])
def test_protocol_rejects_nonobjects_and_nonfinite_values(message):
    with pytest.raises(ProtocolError):
        decode(message)


def test_model_budgets_and_hit_testing():
    model = Compositor()
    ids = [model.create(1, {"width": 1600, "height": 1200})["window"] for _ in range(4)]
    with pytest.raises(ProtocolError, match="pixel budget"):
        model.create(2, {"width": 1600, "height": 1200})
    window = ids[0]
    model.present(1, {"window": window, "items": [
        {"type": "button", "id": "a", "x": 3, "y": 4, "width": 10, "height": 12}]})
    assert model.button_at(window, 5, 6) == "a"
    assert model.button_at(window, 50, 60) is None
    with pytest.raises(ProtocolError):
        model.resize(1, {"window": window, "width": True, "height": 120})


@pytest.mark.parametrize("expression,expected", [("0.1+0.2", "0.3"), ("(12-2)*3/5", "6"), ("-4+2", "-2")])
def test_calculator_evaluates_only_arithmetic(expression, expected):
    assert calculate(expression) == expected


@pytest.mark.parametrize("expression", ["__import__('os')", "2**20", "1/0", "[1]", "1e999"])
def test_calculator_rejects_invalid_expressions(expression):
    with pytest.raises((ValueError, ArithmeticError)):
        calculate(expression)


def test_all_demo_scenes_use_the_validated_protocol():
    for demo in (Calculator(), Clock(), Canvas()):
        assert validate_scene(demo.scene(*demo.size))
    calc = Calculator()
    for key in ("1", "+", "2", "="):
        calc.handle({"type": "click", "target": key})
    assert calc.expression == "3"
    canvas = Canvas()
    canvas.handle({"type": "click", "target": None, "x": 100, "y": 100})
    assert len(canvas.marks) == 1
    canvas.handle({"type": "click", "target": "clear"})
    assert not canvas.marks


def test_service_is_a_real_init_child_and_restores_environment(monkeypatch):
    proc.boot_system()
    manager = ServiceManager()
    monkeypatch.setenv(ENDPOINT_ENV, "previous-endpoint")
    try:
        status = manager.start(mode="headless")
        pcb = manager.pcb
        assert status["state"] == "running"
        assert pcb.ppid == proc.PID_INIT and pcb.kind == "service" and pcb.remote
        assert manager.handle.pid != os.getpid()
        assert manager.start(mode="headless")["pid"] == pcb.pid
        path = Path(status["endpoint"])
        with Client() as client:
            assert client.request("ping")["pong"]
        manager.stop()
        assert not path.exists()
        assert proc.get(pcb.pid) is None
        assert os.environ[ENDPOINT_ENV] == "previous-endpoint"
    finally:
        manager.stop()


def test_demo_clients_run_in_separate_processes(server):
    env = {**os.environ, "PYTHONPATH": str(REPO / "src"), ENDPOINT_ENV: str(server.endpoint)}
    children = [subprocess.Popen([sys.executable, "-m", "vortexglass.demos", kind, "--duration", "1"],
                                 env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                for kind in ("calc", "clock", "canvas")]
    try:
        eventually(lambda: len(server.model.windows) == 3)
        for child in children:
            stdout, stderr = child.communicate(timeout=5)
            assert child.returncode == 0, stdout + stderr
        eventually(lambda: not server.model.windows)
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait()


def test_endpoint_descriptor_and_unix_socket_are_private(server):
    descriptor = json.loads(server.endpoint.read_text())
    assert descriptor["address"]
    if os.name != "nt":
        assert server.endpoint.stat().st_mode & 0o777 == 0o600
        if server.socket_path:
            assert server.socket_path.stat().st_mode & 0o777 == 0o600


def test_update_payload_includes_compositor_and_gui_dependencies():
    import build_update
    files = {relative for _path, relative in build_update._iter_payload_files()}
    assert {"requirements-gui.txt", "src/vortexglass/server.py",
            "src/vortexglass/qt_backend.py", "src/apps/vortexglassd.py",
            "src/apps/guicalc.py", "src/apps/guiclock.py", "src/apps/guicanvas.py"} <= files
