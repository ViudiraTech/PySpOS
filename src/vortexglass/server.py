'''
 *
 *      server.py
 *      An event-driven local socket service; all host windows belong to this process.
 *
 *      2026/9/27 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import base64
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import queue
import secrets
import selectors
import socket
import threading
import time

from . import PROTOCOL_VERSION
from .model import Compositor, integer
from .protocol import MAX_MESSAGE, MAX_PENDING, ProtocolError, decode, encode


@dataclass
class Connection:
    socket: socket.socket
    owner: int
    authenticated: bool = False
    incoming: bytearray = field(default_factory=bytearray)
    outgoing: bytearray = field(default_factory=bytearray)
    deadline: float = field(default_factory=lambda: time.monotonic() + 5)
    closing: bool = False
    stop_after_write: bool = False


class Server:
    def __init__(self, endpoint, *, transport=None, model=None, backend="headless", control_token=None):
        self.endpoint = Path(endpoint)
        self.transport = transport or ("unix" if os.name != "nt" else "tcp")
        self.model = model or Compositor()
        self.backend = backend
        self.capture = None
        self.control_token = control_token
        self.token = secrets.token_hex(32)
        self.selector = selectors.DefaultSelector()
        self.connections = {}
        self.next_owner = 1
        self.listener = None
        self.stopping = threading.Event()
        self.ready = threading.Event()
        self.posts = queue.Queue(maxsize=512)
        self.overflow = set()
        self.post_lock = threading.Lock()
        self.wake_read, self.wake_write = socket.socketpair()
        self.wake_read.setblocking(False)
        self.wake_write.setblocking(False)
        self.selector.register(self.wake_read, selectors.EVENT_READ, "wake")
        self.owns_endpoint = False
        self.socket_path = None
        self.owns_socket = False
        self.select_calls = 0

    def open(self):
        self.endpoint.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        if self.endpoint.exists():
            raise FileExistsError(f"endpoint already exists: {self.endpoint}")
        if self.transport == "unix":
            self.socket_path = self.endpoint.with_suffix(".sock")
            self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.listener.bind(str(self.socket_path))
            self.owns_socket = True
            os.chmod(self.socket_path, 0o600)
            address = str(self.socket_path)
        elif self.transport == "tcp":
            self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.listener.bind(("127.0.0.1", 0))
            address = list(self.listener.getsockname())
        else:
            raise ValueError("transport must be unix or tcp")
        self.listener.listen(32)
        self.listener.setblocking(False)
        self.selector.register(self.listener, selectors.EVENT_READ, "listen")
        descriptor = {"version": PROTOCOL_VERSION, "transport": self.transport,
                      "address": address, "token": self.token, "pid": os.getpid(),
                      "backend": self.backend}
        # Exclusive creation never replaces another compositor's descriptor.
        fd = os.open(self.endpoint, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        self.owns_endpoint = True
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(descriptor, stream)
        self.ready.set()

    def _wake(self):
        try:
            self.wake_write.send(b"w")
        except (BlockingIOError, OSError):
            pass

    def stop(self):
        self.stopping.set()
        self._wake()

    def emit(self, owner, event):
        """Called by the GUI thread, never writes a peer socket directly."""
        try:
            self.posts.put_nowait((owner, {"event": event}))
        except queue.Full:
            with self.post_lock:
                self.overflow.add(owner)
        self._wake()

    def _send(self, peer, message):
        payload = encode(message)
        if len(peer.outgoing) + len(payload) > MAX_PENDING:
            self._drop(peer)
            return
        peer.outgoing.extend(payload)
        self.selector.modify(peer.socket, selectors.EVENT_READ | selectors.EVENT_WRITE, peer)

    def _drop(self, peer):
        if self.connections.pop(peer.owner, None) is None:
            return
        self.model.disconnect(peer.owner)
        try:
            self.selector.unregister(peer.socket)
        except (KeyError, ValueError):
            pass
        peer.socket.close()

    def _accept(self):
        while True:
            try:
                stream, _address = self.listener.accept()
            except BlockingIOError:
                return
            if len(self.connections) >= 64:
                stream.close()
                continue
            stream.setblocking(False)
            peer = Connection(stream, self.next_owner)
            self.next_owner += 1
            self.connections[peer.owner] = peer
            self.selector.register(stream, selectors.EVENT_READ, peer)

    def _request(self, peer, message):
        integer(message.get("id"), "id", 0, 2**53)
        operation = message.get("op")
        if not peer.authenticated:
            token = message.get("token", "")
            if (operation != "hello" or message.get("version") != PROTOCOL_VERSION
                    or not isinstance(token, str) or not secrets.compare_digest(token, self.token)):
                peer.closing = True
                raise ProtocolError("authentication or protocol version failed")
            peer.authenticated = True
            return {"version": PROTOCOL_VERSION, "backend": self.backend,
                    "capabilities": ["display-list", "input", "rgba", "frameless"]}
        if operation == "ping":
            return {"pong": True}
        if operation == "status":
            with self.model.lock:
                return {"backend": self.backend, "connections": len(self.connections),
                        "windows": len(self.model.windows),
                        "owned": [w.id for w in self.model.windows.values() if w.owner == peer.owner]}
        if operation == "shutdown":
            control = message.get("control", "")
            if (not self.control_token or not isinstance(control, str)
                    or not secrets.compare_digest(control, self.control_token)):
                raise ProtocolError("service control requires the supervisor token")
            peer.stop_after_write = True
            return {"stopping": True}
        if operation == "create":
            return self.model.create(peer.owner, message)
        if operation == "present":
            return self.model.present(peer.owner, message)
        if operation == "resize":
            return self.model.resize(peer.owner, message)
        if operation == "destroy":
            return self.model.destroy(peer.owner, message.get("window"))
        if operation == "snapshot":
            window = self.model.owned_snapshot(peer.owner, message.get("window"))
            if self.capture is None:
                raise ProtocolError("PNG capture requires the Qt backend (use --offscreen)")
            return {"png": base64.b64encode(self.capture(window)).decode("ascii")}
        raise ProtocolError("unknown operation")

    def _read(self, peer):
        try:
            data = peer.socket.recv(65536)
        except BlockingIOError:
            return
        if not data:
            self._drop(peer)
            return
        peer.incoming.extend(data)
        while b"\n" in peer.incoming and not peer.closing:
            line, _, rest = peer.incoming.partition(b"\n")
            peer.incoming = bytearray(rest)
            request_id = None
            try:
                message = decode(line)
                request_id = message.get("id")
                result = self._request(peer, message)
                self._send(peer, {"id": request_id, "ok": True, "result": result})
            except (ProtocolError, ValueError, TypeError, TimeoutError) as exc:
                # Never reflect arbitrary objects or huge ids in error replies.
                request_id = request_id if type(request_id) is int else None
                self._send(peer, {"id": request_id, "ok": False, "error": str(exc)[:512]})
            if peer.owner not in self.connections:
                return
        if len(peer.incoming) > MAX_MESSAGE:
            self._drop(peer)

    def _write(self, peer):
        try:
            written = peer.socket.send(peer.outgoing)
        except BlockingIOError:
            return
        del peer.outgoing[:written]
        if not peer.outgoing:
            if peer.stop_after_write:
                self.stop()
            if peer.closing:
                self._drop(peer)
            else:
                self.selector.modify(peer.socket, selectors.EVENT_READ, peer)

    def _posts(self):
        try:
            while self.wake_read.recv(4096):
                pass
        except BlockingIOError:
            pass
        with self.post_lock:
            overflow, self.overflow = self.overflow, set()
        for owner in overflow:
            if owner in self.connections:
                self._drop(self.connections[owner])
        while True:
            try:
                owner, message = self.posts.get_nowait()
            except queue.Empty:
                break
            peer = self.connections.get(owner)
            if peer and peer.authenticated:
                self._send(peer, message)

    def run(self):
        try:
            if not self.ready.is_set():
                self.open()
            while not self.stopping.is_set():
                deadlines = [p.deadline for p in self.connections.values() if not p.authenticated]
                timeout = max(0, min(deadlines) - time.monotonic()) if deadlines else None
                self.select_calls += 1
                for key, mask in self.selector.select(timeout):
                    if key.data == "listen":
                        self._accept()
                    elif key.data == "wake":
                        self._posts()
                    else:
                        peer = key.data
                        try:
                            if mask & selectors.EVENT_READ and not peer.closing:
                                self._read(peer)
                            if mask & selectors.EVENT_WRITE and peer.owner in self.connections:
                                self._write(peer)
                        except (OSError, ValueError):
                            self._drop(peer)
                now = time.monotonic()
                for peer in list(self.connections.values()):
                    if not peer.authenticated and peer.deadline <= now:
                        self._drop(peer)
        finally:
            self.close()

    def close(self):
        for peer in list(self.connections.values()):
            self._drop(peer)
        self.selector.close()
        for stream in (self.listener, self.wake_read, self.wake_write):
            if stream:
                stream.close()
        if self.owns_endpoint:
            self.endpoint.unlink(missing_ok=True)
        if self.socket_path and self.owns_socket:
            self.socket_path.unlink(missing_ok=True)
