'''
 *
 *      client.py
 *      GUI clients submit scenes and receive input; they never create host windows.
 *
 *      2026/9/27 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

from collections import deque
import base64
import socket
import threading
import time

from . import PROTOCOL_VERSION
from .protocol import MAX_MESSAGE, ProtocolError, decode, encode, read_endpoint


class Client:
    def __init__(self, endpoint=None, timeout=5):
        descriptor = read_endpoint(endpoint)
        transport = descriptor["transport"]
        if transport == "unix":
            self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            address = descriptor["address"]
        elif transport == "tcp":
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            address = tuple(descriptor["address"])
            if address[0] != "127.0.0.1":
                self.socket.close()
                raise ProtocolError("compositor must use a local socket")
        else:
            raise ProtocolError("unknown socket transport")
        self.timeout = timeout
        self.socket.settimeout(timeout)
        self.incoming = bytearray()
        self.events = deque(maxlen=128)
        self.sequence = 0
        self.lock = threading.RLock()
        try:
            self.socket.connect(address)
            self.info = self.request("hello", version=PROTOCOL_VERSION, token=descriptor["token"])
        except BaseException:
            self.socket.close()
            raise

    def _receive(self, timeout):
        deadline = None if timeout is None else time.monotonic() + timeout
        while b"\n" not in self.incoming:
            self.socket.settimeout(None if deadline is None else max(0.001, deadline - time.monotonic()))
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError("compositor response timed out")
            data = self.socket.recv(65536)
            if not data:
                raise ConnectionError("compositor disconnected")
            self.incoming.extend(data)
            if len(self.incoming) > MAX_MESSAGE and b"\n" not in self.incoming:
                raise ProtocolError("oversized compositor response")
        line, _, rest = self.incoming.partition(b"\n")
        self.incoming = bytearray(rest)
        return decode(line)

    def request(self, operation, **fields):
        with self.lock:
            self.sequence += 1
            request_id = self.sequence
            self.socket.settimeout(self.timeout)
            self.socket.sendall(encode({**fields, "id": request_id, "op": operation}))
            deadline = time.monotonic() + self.timeout
            while True:
                message = self._receive(max(0, deadline - time.monotonic()))
                if "event" in message:
                    self.events.append(message["event"])
                    continue
                if message.get("id") != request_id:
                    raise ProtocolError("response id mismatch")
                if not message.get("ok"):
                    raise ProtocolError(message.get("error", "compositor rejected request"))
                return message["result"]

    def create(self, title="PySpOS", width=480, height=320, background="#162032e8", **options):
        return self.request("create", title=title, width=width, height=height,
                            background=background, **options)["window"]

    def present(self, window, items, **options):
        return self.request("present", window=window, items=items, **options)

    def destroy(self, window):
        return self.request("destroy", window=window)

    def resize(self, window, width, height):
        return self.request("resize", window=window, width=width, height=height)

    def set_title(self, window, title):
        return self.request("set_title", window=window, title=title)

    def present_pixels(self, window, width, height, pixels):
        """Atomically submit tightly packed, straight-alpha RGBA bytes."""
        if type(width) is not int or type(height) is not int:
            raise ValueError("pixel dimensions must be integers")
        pixels = memoryview(pixels).cast("B")
        if len(pixels) != width * height * 4:
            raise ValueError("expected width * height * 4 RGBA bytes")
        if "pixel-buffer" not in self.info.get("capabilities", []):
            raise ProtocolError("compositor does not support pixel buffers")
        with self.lock:
            upload = self.request("buffer_begin", window=window, width=width,
                                  height=height, format="rgba8888")
            buffer_id, chunk_size = upload["buffer"], upload["chunk_size"]
            try:
                for offset in range(0, len(pixels), chunk_size):
                    data = base64.b64encode(pixels[offset:offset + chunk_size]).decode("ascii")
                    self.request("buffer_write", buffer=buffer_id, offset=offset, data=data)
                return self.request("buffer_commit", buffer=buffer_id)
            except BaseException:
                try:
                    self.request("buffer_cancel", buffer=buffer_id)
                except (OSError, ProtocolError):
                    pass
                raise

    def snapshot(self, window):
        return base64.b64decode(self.request("snapshot", window=window)["png"], validate=True)

    def next_event(self, timeout=None):
        with self.lock:
            if self.events:
                return self.events.popleft()
            try:
                message = self._receive(timeout)
            except TimeoutError:
                return None
            if "event" not in message:
                raise ProtocolError("expected input event")
            return message["event"]

    def close(self):
        self.socket.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()
