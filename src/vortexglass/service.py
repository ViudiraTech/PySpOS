'''
 *
 *      service.py
 *      PID 1 lifecycle management for the real VortexGlass compositor child.
 *
 *      2026/9/27 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import atexit
from collections import deque
import os
from pathlib import Path
import secrets
import shlex
import shutil
import tempfile
import threading
import time

import process as proc

from .client import Client
from .daemon import CONTROL_ENV
from .protocol import ENDPOINT_ENV


class ServiceManager:
    def __init__(self):
        self.lock = threading.RLock()
        self.pcb = None
        self.handle = None
        self.directory = None
        self.endpoint = None
        self.control = None
        self.previous_endpoint = None
        self.last_error = None
        self.log_offset = 0
        self.log_lines = deque(maxlen=512)

    def status(self):
        with self.lock:
            running = bool(self.handle and self.handle.is_alive())
            result = {"name": "vortexglass", "state": "running" if running else "stopped",
                      "pid": self.pcb.pid if self.pcb else None,
                      "endpoint": str(self.endpoint) if self.endpoint else None,
                      "error": self.last_error}
            if running:
                try:
                    with Client(self.endpoint, timeout=1) as client:
                        result.update(client.request("status"))
                except (OSError, ValueError, ConnectionError) as exc:
                    result["state"] = "failed"
                    result["error"] = str(exc)
            return result

    def start(self, *, mode=None, theme_dir=None, src_dir=None, timeout=8):
        with self.lock:
            if self.handle and self.handle.is_alive():
                return self.status()
            self.stop()
            import forkexec
            self.directory = Path(tempfile.mkdtemp(prefix="pyspos-vg-"))
            self.log_offset = 0
            self.endpoint = self.directory / "endpoint.json"
            self.previous_endpoint = os.environ.get(ENDPOINT_ENV)
            self.control = secrets.token_hex(32)
            self.last_error = None
            src_dir = str(src_dir or Path(__file__).resolve().parents[1])
            arguments = ["--endpoint", str(self.endpoint)]
            if mode in ("headless", "offscreen"):
                arguments.append("--" + mode)
            if theme_dir:
                arguments.extend(("--theme-dir", str(theme_dir)))
            env = {ENDPOINT_ENV: str(self.endpoint), CONTROL_ENV: self.control,
                   "PYSPOS_APP_ARGS": shlex.join(arguments)}
            self.pcb = forkexec.fork_exec("app:vortexglassd.py", kind="service", ppid=proc.PID_INIT,
                                         background=True, src_dir=src_dir,
                                         env=env, log_path=str(self.directory / "service.log"))
            self.handle = proc._table().handles.get(self.pcb.pid)
            deadline = time.monotonic() + timeout
            while self.handle and self.handle.is_alive() and time.monotonic() < deadline:
                try:
                    with Client(self.endpoint, timeout=0.25) as client:
                        client.request("ping")
                    os.environ[ENDPOINT_ENV] = str(self.endpoint)
                    return self.status()
                except (OSError, ValueError, ConnectionError):
                    # Startup readiness only; the running service has no polling loop.
                    time.sleep(0.02)
            log = self.directory / "service.log"
            error = log.read_text(errors="replace")[-2048:] if log.exists() else ""
            self.last_error = error.strip() or "VortexGlass did not become ready"
            self.stop()
            raise RuntimeError(self.last_error)

    # Retain unread child output before its temporary service directory disappears.
    def _collect_logs(self):
        if not self.directory:
            return
        try:
            with (self.directory / "service.log").open("rb") as stream:
                stream.seek(self.log_offset)
                data = stream.read(65536)
                self.log_offset = stream.tell()
            self.log_lines.extend(data.decode("utf-8", "replace").splitlines())
        except OSError:
            pass

    # Drain bounded child output into the system service journal.
    def read_logs(self):
        with self.lock:
            self._collect_logs()
            lines = list(self.log_lines)
            self.log_lines.clear()
            return lines

    def stop(self):
        with self.lock:
            handle = self.handle
            if handle and handle.is_alive():
                try:
                    with Client(self.endpoint, timeout=1) as client:
                        client.request("shutdown", control=self.control)
                except (OSError, ValueError, ConnectionError):
                    pass
                handle.join(3)
                if handle.is_alive():
                    handle.terminate()
                    handle.join(2)
                if handle.is_alive():
                    handle.kill()
                    handle.join(2)
            if self.pcb and handle and not handle.is_alive():
                # Join the output relay before collecting or removing its log file.
                import forkexec
                forkexec.wait(self.pcb.pid, timeout=2)
            if self.pcb and proc.get(self.pcb.pid) is self.pcb:
                if self.pcb.state not in proc.TERMINAL_STATES:
                    proc.finish(self.pcb.pid, int(handle.exitcode or 0) if handle else 1)
                proc.reap_children(proc.PID_INIT)
            if self.endpoint and os.environ.get(ENDPOINT_ENV) == str(self.endpoint):
                if self.previous_endpoint is None:
                    os.environ.pop(ENDPOINT_ENV, None)
                else:
                    os.environ[ENDPOINT_ENV] = self.previous_endpoint
            if self.directory:
                self._collect_logs()
                shutil.rmtree(self.directory, ignore_errors=True)
            self.pcb = self.handle = self.directory = self.endpoint = self.control = None
            self.previous_endpoint = None


manager = ServiceManager()
atexit.register(manager.stop)
