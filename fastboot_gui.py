#!/usr/bin/env python3
'''
 *
 *      fastboot_gui.py
 *      PySpOS fastboot host client (graphical tool).
 *
 *      The device never offers a local flashing UI: this tool is the host
 *      side of the fastboot protocol, the way the Android "fastboot" binary
 *      drives a phone in fastboot mode. It talks to src/fastboot.py over
 *      loopback TCP and exposes the privileged operations (flashing, erasing,
 *      unlocking the bootloader) as buttons, plus a process panel that can
 *      send signals to running PySpOS processes.
 *
 *      2026/9/26 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import argparse
import queue
import socket
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# Where the device-side fastboot server listens by default.
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5555

# Seconds allowed for one protocol round trip.
TIMEOUT = 10.0

# Signals the process panel can deliver, mapped to the device-side names.
SIGNALS = ("SIGTERM", "SIGKILL", "SIGSTOP", "SIGCONT", "SIGUSR1", "SIGUSR2")


# One connection to the device: a request is one line, the reply is one line,
# except for "download", where the client sends raw bytes after DATA.
class FastbootClient:
    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT, timeout=TIMEOUT):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock = None
        self.buffer = b""
        # Every request runs on a worker thread while the UI thread may close
        # the socket, so socket use is serialized. Without this, clicking a
        # reboot button could null the socket between the worker's send and
        # its read, which surfaced as "'NoneType' object has no attribute
        # 'recv'".
        self._lock = threading.RLock()

    # Open the socket, reporting the failure instead of raising.
    def connect(self):
        self.close()
        try:
            sock = socket.create_connection((self.host, self.port), self.timeout)
        except OSError as exc:
            return False, f"无法连接 {self.host}:{self.port}：{exc}"
        with self._lock:
            self.sock = sock
            self.buffer = b""
        return True, f"已连接 {self.host}:{self.port}"

    # Drop the socket, ignoring an already closed one.
    def close(self):
        with self._lock:
            sock, self.sock = self.sock, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    # Read one newline-terminated reply from the device.
    def _readline(self):
        while b"\n" not in self.buffer:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise OSError("设备已断开连接")
            self.buffer += chunk
        line, self.buffer = self.buffer.split(b"\n", 1)
        return line.decode("utf-8", "replace").strip()

    # Send one command and return the raw reply line.
    def request(self, command):
        with self._lock:
            if self.sock is None:
                raise OSError("尚未连接设备")
            self.sock.sendall((command + "\n").encode("utf-8"))
            return self._readline()

    # Run a command that must succeed, raising OSError on a FAIL reply.
    def command(self, command):
        reply = self.request(command)
        if reply.startswith("FAIL"):
            raise OSError(reply[4:] or "设备拒绝了该请求")
        return reply

    # Download a file into the device, then return the flash reply.
    def flash(self, partition, path):
        with open(path, "rb") as handle:
            data = handle.read()
        with self._lock:
            reply = self.request(f"download:{len(data):08x}")
            if not reply.startswith("DATA"):
                raise OSError(reply[4:] or "设备拒绝下载")
            self.sock.sendall(data)
            # The device acknowledges the payload with its own OKAY line.
            self._readline()
            reply = self.command(f"flash:{partition}")
        return reply

    # Ask the device to erase one partition.
    def erase(self, partition):
        return self.command(f"erase:{partition}")

    # Change the bootloader trust domain.
    def flashing(self, option):
        return self.command(f"flashing {option}")

    # Send a command and then hang up. The device reboots, so the connection
    # is finished either way; closing here keeps the UI thread from racing the
    # worker that is still talking to the device.
    def reboot(self, target=""):
        try:
            return self.command(f"reboot{target}")
        finally:
            self.close()

    # Ask the device to power off, then hang up.
    def powerdown(self):
        try:
            return self.command("powerdown")
        finally:
            self.close()

    # Read one getvar value, reporting the raw reply for unknown names.
    def getvar(self, name):
        return self.request(f"getvar:{name}")

    # Read every bootloader variable the device exposes.
    def all_variables(self):
        names = ("version", "product", "unlocked", "secure", "current-slot",
                 "slot-count", "version-bootloader", "rollback-index",
                 "max-download-size", "is-userspace", "super-partition-name")
        values = {}
        for name in names:
            reply = self.getvar(name)
            values[name] = reply[4:] if reply.startswith("OKAY") else reply
        return values


# The graphical front end: a log pane, a device panel and a process panel.
class FastbootGui:
    def __init__(self, root, host, port):
        self.root = root
        self.client = FastbootClient(host, port)
        self.events = queue.Queue()
        self.root.title("PySpOS Fastboot")
        self.root.geometry("720x560")
        self._build()
        self.root.after(100, self._drain)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # Build every widget of the window.
    def _build(self):
        bar = ttk.Frame(self.root, padding=6)
        bar.pack(fill="x")
        ttk.Label(bar, text="设备").pack(side="left")
        self.host_var = tk.StringVar(value=self.client.host)
        ttk.Entry(bar, textvariable=self.host_var, width=14).pack(side="left", padx=4)
        ttk.Label(bar, text="端口").pack(side="left")
        self.port_var = tk.StringVar(value=str(self.client.port))
        ttk.Entry(bar, textvariable=self.port_var, width=7).pack(side="left", padx=4)
        ttk.Button(bar, text="连接", command=self._on_connect).pack(side="left", padx=4)
        ttk.Button(bar, text="断开", command=self._on_disconnect).pack(side="left")

        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=6, pady=4)

        dev = ttk.Frame(nb, padding=8)
        self.var_text = tk.Text(dev, height=9, wrap="none")
        self.var_text.pack(fill="x")
        ttk.Button(dev, text="读取变量 (getvar all)",
                   command=self._on_refresh).pack(anchor="w", pady=4)

        ops = ttk.LabelFrame(dev, text="分区操作", padding=8)
        ops.pack(fill="x", pady=4)
        self.slot_var = tk.StringVar(value="slot_a")
        ttk.Combobox(ops, textvariable=self.slot_var,
                     values=("slot_a", "slot_b"), state="readonly",
                     width=10).pack(side="left")
        ttk.Button(ops, text="刷写镜像",
                   command=self._on_flash).pack(side="left", padx=4)
        ttk.Button(ops, text="擦除分区",
                   command=self._on_erase).pack(side="left")

        bl = ttk.LabelFrame(dev, text="Bootloader", padding=8)
        bl.pack(fill="x", pady=4)
        ttk.Button(bl, text="解锁 (会清除数据)",
                   command=lambda: self._on_flashing("unlock")).pack(side="left", padx=4)
        ttk.Button(bl, text="锁定",
                   command=lambda: self._on_flashing("lock")).pack(side="left", padx=4)
        ttk.Button(bl, text="重启", command=self._on_reboot).pack(side="left", padx=4)
        ttk.Button(bl, text="重启到 bootloader",
                   command=self._on_reboot_bl).pack(side="left", padx=4)
        ttk.Button(bl, text="关机", command=self._on_poweroff).pack(side="left")
        nb.add(dev, text="设备")

        sig = ttk.Frame(nb, padding=8)
        ttk.Label(sig, text="向 PySpOS 进程发送信号").pack(anchor="w")
        listbox = ttk.Frame(sig)
        listbox.pack(fill="both", expand=True, pady=4)
        scroll = ttk.Scrollbar(listbox)
        scroll.pack(side="right", fill="y")
        self.pid_list = tk.Listbox(listbox, height=12, selectmode="browse",
                                   yscrollcommand=scroll.set)
        self.pid_list.pack(side="left", fill="both", expand=True)
        scroll.config(command=self.pid_list.yview)
        self.sig_var = tk.StringVar(value="SIGTERM")
        ttk.Combobox(sig, textvariable=self.sig_var, values=SIGNALS,
                     state="readonly", width=12).pack(side="left")
        ttk.Button(sig, text="发送信号",
                   command=self._on_signal).pack(side="left", padx=4)
        ttk.Button(sig, text="刷新进程",
                   command=self._on_refresh_ps).pack(side="left")
        nb.add(sig, text="进程信号")

        log = ttk.LabelFrame(self.root, text="日志", padding=6)
        log.pack(fill="both", expand=False, padx=6, pady=4)
        self.log_text = tk.Text(log, height=10, state="disabled")
        self.log_text.pack(fill="both", expand=True)
        sb = ttk.Scrollbar(log, orient="vertical", command=self.log_text.yview)
        sb.pack(side="right", fill="y")
        self.log_text.config(yscrollcommand=sb.set)

    # Append one line to the log pane.
    def _log(self, text):
        stamp = ""
        self.log_text.config(state="normal")
        self.log_text.insert("end", f"{stamp}{text}\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    # Queue work for the UI thread and report the result in the log.
    def _run(self, label, work):
        def task():
            try:
                message = work()
                self.events.put((label, True, message))
            except Exception as exc:
                self.events.put((label, False, str(exc)))
        threading.Thread(target=task, daemon=True).start()

    # Move finished background results into the widgets.
    def _drain(self):
        try:
            while True:
                label, ok, message = self.events.get_nowait()
                self._log(f"{'OK' if ok else 'FAIL'} {label}: {message}")
        except queue.Empty:
            pass
        self.root.after(100, self._drain)

    # Connect to the device, then read its variables.
    def _on_connect(self):
        host = self.host_var.get().strip() or DEFAULT_HOST
        try:
            port = int(self.port_var.get().strip() or DEFAULT_PORT)
        except ValueError:
            self._log("FAIL 端口必须是数字")
            return
        self.client.host, self.client.port = host, port

        def job():
            ok, message = self.client.connect()
            if not ok:
                raise OSError(message)
            # Read the variables as part of connecting, but keep the connect
            # message even if a later variable read fails.
            try:
                read = self._refresh_vars()
            except Exception as exc:
                self._log(f"WARN 读取变量失败: {exc}")
            else:
                self._log(read)
            return message

        self._run("连接", job)

    # Close the socket and forget the device.
    def _on_disconnect(self):
        self.client.close()
        self._log("OK 已断开")

    # Read the variable table straight into the text pane.
    def _refresh_vars(self):
        values = self.client.all_variables()
        self.var_text.config(state="normal")
        self.var_text.delete("1.0", "end")
        for name, value in values.items():
            self.var_text.insert("end", f"{name:24} {value}\n")
        self.var_text.config(state="disabled")
        return f"读取 {len(values)} 个变量"

    # Read variables on a background thread.
    def _on_refresh(self):
        self._run("getvar", self._refresh_vars)

    # Flash a chosen image file into the selected slot.
    def _on_flash(self):
        path = filedialog.askopenfilename(title="选择要刷写的镜像")
        if not path:
            return
        slot = self.slot_var.get()
        self._run(f"flash {slot}", lambda: self.client.flash(slot, path)[4:])

    # Erase the selected slot after an explicit confirmation.
    def _on_erase(self):
        slot = self.slot_var.get()
        if not messagebox.askyesno("确认", f"确定要擦除 {slot} 吗？此操作不可撤销。"):
            return
        self._run(f"erase {slot}", lambda: self.client.erase(slot)[4:])

    # Change the bootloader trust domain.
    def _on_flashing(self, option):
        if option == "unlock" and not messagebox.askyesno(
                "确认", "解锁 Bootloader 会清除两个槽位的全部数据，继续？"):
            return
        self._run(f"flashing {option}", lambda: self.client.flashing(option)[4:])

    # Reboot the device. The client hangs up itself once the request is sent.
    def _on_reboot(self):
        self._run("reboot", lambda: self.client.reboot()[4:])

    # Reboot back into fastboot.
    def _on_reboot_bl(self):
        self._run("reboot-bootloader", lambda: self.client.reboot("-bootloader")[4:])

    # Power the device off.
    def _on_poweroff(self):
        self._run("powerdown", lambda: self.client.powerdown()[4:])

    # Ask the device for the process list over the OEM extension.
    def _refresh_ps(self):
        reply = self.client.request("oem pyspos-ps")
        if not reply.startswith("OKAY"):
            raise OSError(reply[4:] or "设备不支持该命令")
        body = reply[4:]
        rows = [] if body.startswith("(") else body.split(";")
        self.pid_list.delete(0, "end")
        for line in rows:
            self.pid_list.insert("end", line)
        return f"共 {self.pid_list.size()} 个进程"

    # Refresh the process list on a background thread.
    def _on_refresh_ps(self):
        self._run("ps", self._refresh_ps)

    # Send the selected signal to the highlighted process.
    def _on_signal(self):
        selection = self.pid_list.curselection()
        if not selection:
            self._log("FAIL 请先选中一个进程")
            return
        pid = self.pid_list.get(selection[0]).split()[0]
        signame = self.sig_var.get()
        self._run(f"signal {pid} {signame}",
                  lambda: self.client.request(f"oem pyspos-signal {pid} {signame}")[4:])

    # Close the socket before the window goes away.
    def _on_close(self):
        self.client.close()
        self.root.destroy()


# Parse the command line and start the window.
def main(argv=None):
    parser = argparse.ArgumentParser(description="PySpOS fastboot 图形客户端")
    parser.add_argument("--host", default=DEFAULT_HOST, help="设备地址")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="设备端口")
    args = parser.parse_args(argv)
    try:
        root = tk.Tk()
    except Exception as exc:
        print(f"无法启动图形界面：{exc}", file=sys.stderr)
        print("请确认已安装 tkinter（Linux 需要 python3-tk）。", file=sys.stderr)
        return 1
    FastbootGui(root, args.host, args.port)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
