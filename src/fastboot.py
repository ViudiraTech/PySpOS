'''
 *
 *      fastboot.py
 *      PySpOS fastboot protocol server (device side).
 *
 *      Mirrors the AOSP fastboot wire protocol: the device never offers a
 *      local UI, it only answers protocol requests coming from a host client.
 *      PySpOS ships fastboot_gui.py as that host tool, so every privileged
 *      operation (flashing, erasing, unlocking the bootloader) is reachable
 *      only through a client, never by typing inside the running system.
 *
 *      2026/9/26 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import os
import socket
import threading

import bootmode
import kernel
import logk
import main
import ota
import printk
import process as proc
import secure_boot

# Protocol version advertised through "getvar:version", like AOSP's 0.4.
PROTOCOL_VERSION = "0.4"

# Default TCP port the host client connects to. Loopback only on purpose:
# the flashing channel must never be reachable from the network.
DEFAULT_PORT = 5555

# Loopback address the server binds to.
BIND_HOST = "127.0.0.1"

# How many bytes "getvar:max-download-size" reports as downloadable at once.
MAX_DOWNLOAD_SIZE = 64 * 1024 * 1024

# Seconds a client may stay silent before the server drops the connection.
CLIENT_TIMEOUT = 600.0

# Prefix marking an OEM-specific request, reserved by the specification.
OEM_PREFIX = "oem "

# Signal names the host client may deliver, mapped to process.py numbers.
SIGNAL_NUMBERS = {
    "SIGTERM": proc.SIGTERM,
    "SIGKILL": proc.SIGKILL,
    "SIGSTOP": proc.SIGSTOP,
    "SIGCONT": proc.SIGCONT,
    "SIGUSR1": proc.SIGUSR1,
    "SIGUSR2": proc.SIGUSR2,
}


# ---------------------------------------------------------------------------
# Server state
# ---------------------------------------------------------------------------

# Bytes staged by the last "download" command, waiting for flash or boot.
_download_buffer = bytearray()

# Set once the host asks to boot a staged image, so the loop can exit.
_pending_boot = None

# Guards the staged image against two clients racing on the same session.
_state_lock = threading.Lock()


# Reset the staged download buffer, the pending boot request and the state
# lock, so a fresh session never sees bytes from an earlier one.
def reset_state() -> None:
    global _download_buffer, _pending_boot
    with _state_lock:
        _download_buffer = bytearray()
        _pending_boot = None


# Report the staged download size in bytes.
def staged_size() -> int:
    with _state_lock:
        return len(_download_buffer)


# Return a copy of the staged download so callers cannot corrupt the buffer.
def staged_bytes() -> bytes:
    with _state_lock:
        return bytes(_download_buffer)


# Replace the staged download with new bytes.
def stage_bytes(data: bytes) -> None:
    global _download_buffer
    with _state_lock:
        _download_buffer = bytearray(data)


# Ask the server to hand control to a staged image once the loop ends.
def set_pending_boot(partition: str) -> None:
    global _pending_boot
    with _state_lock:
        _pending_boot = partition


# Read and clear the pending boot request, reporting the partition name.
def take_pending_boot():
    global _pending_boot
    with _state_lock:
        pending, _pending_boot = _pending_boot, None
        return pending


# ---------------------------------------------------------------------------
# Bootloader variables, the answer side of "getvar"
# ---------------------------------------------------------------------------

# Report whether the bootloader is locked, treating an unreadable policy as
# locked so a broken trust domain never looks unlocked.
def is_locked() -> bool:
    try:
        return bool(secure_boot.read_locked(main.root_dir, _device_trusted_keys()))
    except Exception:
        return True


# Report the rollback index floor that the verified policy carries.
def rollback_index() -> int:
    try:
        policy = secure_boot.read_policy(main.root_dir, _device_trusted_keys())
        return int(policy["rollback_index"]) if policy else 0
    except Exception:
        return 0


# Report the version string of one slot, or "unknown" when it has none.
def slot_version(slot: str) -> str:
    try:
        return ota.get_version(slot) or "unknown"
    except Exception:
        return "unknown"


# Build the variable table exposed through "getvar". Values must stay short
# because the protocol has no continuation for long replies.
def collect_variables() -> dict:
    try:
        current = ota.get_current_slot()
    except Exception:
        current = "unknown"
    try:
        version = ota.get_current_version()
    except Exception:
        version = "unknown"
    locked = is_locked()
    return {
        "version": PROTOCOL_VERSION,
        "product": "PySpOS",
        "unlocked": "no" if locked else "yes",
        "secure": "yes" if locked else "no",
        "current-slot": str(current),
        "slot-count": "2",
        "version-bootloader": f"pyspos-{version}",
        "rollback-index": str(rollback_index()),
        "max-download-size": str(MAX_DOWNLOAD_SIZE),
        "is-userspace": "no",
        "super-partition-name": "pyspos_super",
        "snapshot-update-status": "none",
    }


# Resolve a single "getvar" name, reporting the value or None when unknown.
def read_variable(name: str):
    return collect_variables().get(name)


# ---------------------------------------------------------------------------
# Privileged actions
# ---------------------------------------------------------------------------

# Return the path of the device private signing key used by fastboot unlock.
def device_key_path() -> str:
    return os.path.join(main.root_dir, secure_boot.PROTECTED_DIR,
                        secure_boot.DEVICE_PRIVATE_KEY_NAME)


# Build the trusted key set that fastboot accepts: the OEM keys plus the
# device development key. Policy verification deliberately ignores the
# runtime trust store, so an unlocked policy signed by the device key would
# otherwise never verify and the device would look locked forever. The extra
# key is only honoured here, inside the mode that already demands ROOT, which
# keeps the normal boot trust boundary unchanged.
# The device key is derived from the private key that actually signs, never
# from the published .pub file: a stale or unreadable .pub would otherwise
# silently shrink the trust store and make every unlock and lock fail.
def _device_trusted_keys():
    keys = dict(secure_boot.TRUSTED_PUBLIC_KEYS)
    try:
        private = secure_boot.load_private_key(device_key_path())
        raw_public = secure_boot.public_key_bytes(private)
        keys[secure_boot.public_key_id(raw_public)] = raw_public
        return keys
    except Exception as exc:
        logk.printl("fastboot",
                    f"读取设备开发密钥失败，信任库仅含 OEM 公钥: {exc}",
                    main.boot_time)
    public_path = os.path.join(main.root_dir, secure_boot.PROTECTED_DIR,
                               secure_boot.DEVICE_PUBLIC_KEY_NAME)
    if os.path.islink(public_path) or not os.path.isfile(public_path):
        return keys
    try:
        with open(public_path, "r", encoding="ascii") as stream:
            raw_public = secure_boot.decode_public_key(stream.read().strip())
        keys[secure_boot.public_key_id(raw_public)] = raw_public
    except Exception as exc:
        logk.printl("fastboot", f"读取设备开发公钥失败: {exc}", main.boot_time)
    return keys


# Return the OTA staging path for the active root. The directory is derived
# here instead of reusing the ota module constant, which is bound to the root
# that was current at import time and would ignore a later change.
def staging_path() -> str:
    return os.path.join(main.root_dir, "ota", ota.OTA_PACKAGE_NAME)


# Wipe the device the way recovery erase does, instead of deleting the slots
# themselves. The A/B slots hold the signed system images and are immutable
# install targets: dropping files in or wiping them here would break manifest
# verification and leave the device unbootable.
def _wipe_user_data() -> tuple:
    try:
        from common import reset
        report = reset.factory_reset(main.root_dir, preserve_slots=True)
    except Exception as exc:
        return False, f"清除用户数据失败: {exc}"
    failed = [name for name, (ok, _note) in report.items() if not ok]
    if failed:
        return False, f"部分数据未能清除：{'、'.join(failed)}"
    return True, "用户数据已清除"


# Unlock the bootloader through the offline developer key, then wipe user
# data. AOSP erases data on unlock for privacy, and so does PySpOS: both
# slots are cleared so no signed image survives the trust change.
# Log why a signing attempt failed, traceback included. A bare message from a
# Tk client log is not enough to tell a trust-store rejection from a broken
# runtime, and these paths only run on a real device.
def _log_failure(action, exc):
    import traceback
    logk.printl("fastboot", f"{action} Bootloader 失败: {type(exc).__name__}: {exc}",
                main.boot_time)
    for line in traceback.format_exc().splitlines():
        logk.printl("fastboot", line, main.boot_time)


# Sign and store a bootloader policy, turning a trust-store rejection into a
# message that names the key and the store. A bare "not in the trust store"
# is indistinguishable from a stale build, which is exactly the case that is
# hard to diagnose from the GUI log.
def _write_policy(root, locked, floor) -> None:
    try:
        secure_boot.write_policy(root, locked, floor, device_key_path(),
                                 _device_trusted_keys())
    except secure_boot.BootVerificationError as exc:
        trusted = sorted(_device_trusted_keys())
        try:
            used = secure_boot.public_key_id(
                secure_boot.public_key_bytes(
                    secure_boot.load_private_key(device_key_path())))
        except Exception:
            used = "unknown"
        raise secure_boot.BootVerificationError(
            f"{exc}（签名密钥 {used}，信任库 {trusted or '空'}；"
            f"若密钥与信任库不匹配，多半是设备跑的是旧构建，请重新同步槽位）"
        ) from exc


# Refresh the runtime trust store. This is best effort: policy verification in
# fastboot resolves the device key from the private key directly, so a failure
# here must not abort an unlock that already succeeded.
def _refresh_runtime_keys(root, locked):
    try:
        secure_boot.configure_runtime_keys(root, locked)
    except Exception as exc:
        logk.printl("fastboot", f"刷新运行时信任库失败（已忽略）: {exc}", main.boot_time)


# Unlock the bootloader through the offline developer key, then wipe user
# data. AOSP erases data on unlock for privacy, and so does PySpOS: the user
# data goes, while the signed system images stay so the device can still boot.
def perform_unlock() -> tuple:
    root = main.root_dir
    try:
        secure_boot.ensure_developer_key(root, locked=False)
        _write_policy(root, False, 0)
    except Exception as exc:
        _log_failure("解锁", exc)
        return False, f"签发解锁策略失败: {type(exc).__name__}: {exc}"
    _refresh_runtime_keys(root, False)
    wiped, message = _wipe_user_data()
    if not wiped:
        return False, f"已解锁，但{message}"
    return True, "Bootloader 已解锁，用户数据已清除"


# Report whether the slot that would be booted has a signed manifest. A locked
# bootloader refuses unsigned images, so locking while the active slot is
# unsigned would leave the device unable to start at all.
def active_slot_is_signed() -> bool:
    try:
        slot = ota.get_current_slot()
        manifest = secure_boot._manifest_from_slot(main.root_dir, slot, None, 0)
    except Exception:
        return False
    return manifest is not None


# Re-lock the bootloader with the developer key, keeping the current floor.
def perform_lock() -> tuple:
    root = main.root_dir
    if not active_slot_is_signed():
        return False, ("当前启动槽位没有签名镜像，锁定后设备将无法启动"
                       "（与真机刷错镜像后锁定会变砖同理）")
    try:
        secure_boot.ensure_developer_key(root, locked=False)
        _write_policy(root, True, rollback_index())
    except Exception as exc:
        _log_failure("锁定", exc)
        return False, f"签发锁定策略失败: {type(exc).__name__}: {exc}"
    _refresh_runtime_keys(root, True)
    return True, "Bootloader 已锁定"


# Stage the downloaded image for the verified installer. It deliberately does
# not write into a slot: the signed manifest covers every file in the slot
# tree, so an extra unsigned file would make the slot fail verification and
# the device would no longer boot.
def perform_flash(partition: str) -> tuple:
    data = staged_bytes()
    if not data:
        return False, "没有已下载的镜像"
    if partition not in (ota.SLOT_A, ota.SLOT_B):
        return False, f"没有名为 {partition} 的分区"
    if is_locked():
        return False, "Bootloader 已锁定，拒绝刷写未签名镜像"
    path = staging_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(data)
    except OSError as exc:
        return False, f"写入镜像失败: {exc}"
    return True, f"镜像已暂存（{len(data)} 字节），等待验签安装到 {partition}"


# Stage the staged image as the next boot target, mirroring "boot". The image
# stays in the OTA staging area: nothing installs it automatically at boot, so
# the verified installer still has to run before it reaches a slot.
def perform_boot() -> tuple:
    if not staged_bytes():
        return False, "没有已下载的镜像"
    bootmode.clear_mode(main.root_dir)
    set_pending_boot("system")
    return True, "已安排启动系统，镜像保留在暂存区等待验签安装"


# Hand control back to the running system, mirroring "continue".
def perform_continue() -> tuple:
    set_pending_boot("system")
    return True, "继续启动系统"

# Build the process table shown by the host client. The rows are joined with
# ";" because the protocol is strictly one reply line per request.
def process_listing() -> str:
    try:
        rows = proc.list_procs(include_done=True)
    except Exception as exc:
        return f"读取进程表失败: {exc}"
    if not rows:
        return "(没有进程)"
    lines = []
    for row in rows:
        remote = "*" if getattr(row, "remote", False) else " "
        lines.append(f"{row.pid}{remote} {row.ppid} {row.state} {row.kind} {row.cmd}")
    return ";".join(lines)


# Deliver a signal to one process on behalf of the host client.
def signal_process(pid_text: str, signame: str) -> tuple:
    try:
        pid = int(pid_text)
    except ValueError:
        return False, f"PID {pid_text} 不是数字"
    signum = SIGNAL_NUMBERS.get(signame.upper())
    if signum is None:
        return False, f"未知信号 {signame}"
    try:
        ok, message = proc.send_signal(pid, signum)
    except Exception as exc:
        return False, f"发送信号失败: {exc}"
    return (True, f"已向 {pid} 发送 {signame}") if ok else (False, message)


# ---------------------------------------------------------------------------
# Protocol engine
# ---------------------------------------------------------------------------

# Report whether the bootloader is locked, for command handlers.
def _locked() -> bool:
    return is_locked()


# Handle one protocol request, returning the reply string to send back.
def handle_command(command: str) -> str:
    command = (command or "").strip()
    if not command:
        return "OKAY"
    if command.startswith("getvar"):
        name = command[6:].lstrip(":") or "version"
        value = read_variable(name)
        if value is None:
            return f"FAILunknown variable: {name}"
        return f"OKAY{value}"
    if command.startswith("download:"):
        try:
            size = int(command[9:].strip(), 16)
        except ValueError:
            return "FAILinvalid size"
        if size < 0 or size > MAX_DOWNLOAD_SIZE:
            return "FAILtoo large"
        return f"DATA{size:08x}"
    if command.startswith("flash:"):
        if _locked():
            return "FAILdevice is locked"
        ok, message = perform_flash(command[6:].strip())
        return f"OKAY{message}" if ok else f"FAIL{message}"
    if command.startswith("erase:"):
        if _locked():
            return "FAILdevice is locked"
        ok, message = perform_erase(command[6:].strip())
        return f"OKAY{message}" if ok else f"FAIL{message}"
    if command == "boot":
        ok, message = perform_boot()
        return f"OKAY{message}" if ok else f"FAIL{message}"
    if command == "continue":
        # Leaving for the system: drop any pending fastboot request so the
        # next boot does not land here again.
        bootmode.clear_mode(main.root_dir)
        ok, message = perform_continue()
        return f"OKAY{message}" if ok else f"FAIL{message}"
    if command in ("reboot", "reboot-bootloader", "powerdown"):
        if command == "reboot-bootloader":
            # Keep the request so the reboot comes back into fastboot.
            bootmode.request_mode(main.root_dir, bootmode.MODE_FASTBOOT)
            set_pending_boot("reboot")
        elif command == "reboot":
            bootmode.clear_mode(main.root_dir)
            set_pending_boot("reboot")
        else:
            bootmode.clear_mode(main.root_dir)
            set_pending_boot("poweroff")
        return "OKAY"
    if command.startswith("flashing"):
        parts = command.split()
        if len(parts) != 2:
            return "FAILusage: flashing <unlock|lock>"
        if parts[1] == "unlock":
            ok, message = perform_unlock()
        elif parts[1] == "lock":
            ok, message = perform_lock()
        else:
            return f"FAILunknown flashing option: {parts[1]}"
        return f"OKAY{message}" if ok else f"FAIL{message}"
    if command.startswith(OEM_PREFIX):
        return _handle_oem(command[len(OEM_PREFIX):].strip())
    if command == "getvar":
        return "OKAY"
    return f"FAILunknown command: {command}"


# Handle the OEM extension used by the host client: the process list and
# signal delivery. Everything else stays reserved for future use.
def _handle_oem(rest: str) -> str:
    parts = rest.split()
    if not parts:
        return "FAILempty oem command"
    if parts[0] == "pyspos-ps":
        return f"OKAY{process_listing()}"
    if parts[0] == "pyspos-signal":
        if len(parts) != 3:
            return "FAILusage: oem pyspos-signal <pid> <signame>"
        ok, message = signal_process(parts[1], parts[2])
        return f"OKAY{message}" if ok else f"FAIL{message}"
    return f"FAILunknown oem command: {parts[0]}"


# Erase the staged image or wipe user data, depending on the target. The A/B
# slots are never erased: they carry the signed system images.
def perform_erase(partition: str) -> tuple:
    if partition in (ota.SLOT_A, ota.SLOT_B):
        return _wipe_user_data()
    if partition in ("cache", "data", "userdata"):
        return _wipe_user_data()
    staged = staging_path()
    if os.path.isfile(staged):
        try:
            os.remove(staged)
        except OSError as exc:
            return False, f"清除暂存镜像失败: {exc}"
        return True, "已清除暂存镜像"
    return False, f"没有名为 {partition} 的分区"


# Serve one connected client until it disconnects or asks to reboot.
def serve_client(conn: socket.socket, address) -> None:
    host = f"{address[0]}:{address[1]}" if address else "unknown"
    logk.printl("fastboot", f"客户端已连接 {host}", main.boot_time)
    try:
        conn.settimeout(CLIENT_TIMEOUT)
        buffer = b""
        while True:
            while b"\n" not in buffer:
                try:
                    chunk = conn.recv(4096)
                except socket.timeout:
                    logk.printl("fastboot", "客户端超时，断开连接", main.boot_time)
                    return
                except OSError:
                    return
                if not chunk:
                    return
                buffer += chunk
            line, buffer = buffer.split(b"\n", 1)
            try:
                command = line.decode("utf-8", "replace").strip()
            except Exception:
                command = ""
            if not command:
                continue
            reply = handle_command(command)
            try:
                conn.sendall((reply + "\n").encode("utf-8"))
            except OSError:
                return
            if reply.startswith("DATA"):
                # The host sends the raw payload right after the DATA reply.
                # It may already sit in the buffer, so read the exact count
                # instead of waiting for another segment.
                try:
                    size = int(reply[4:], 16)
                except ValueError:
                    return
                payload = buffer[:size]
                while len(payload) < size:
                    try:
                        chunk = conn.recv(size - len(payload))
                    except socket.timeout:
                        logk.printl("fastboot", "下载超时，断开连接", main.boot_time)
                        return
                    except OSError:
                        return
                    if not chunk:
                        return
                    payload += chunk
                buffer = buffer[size:]
                stage_bytes(payload)
                try:
                    conn.sendall(b"OKAY\n")
                except OSError:
                    return
            if take_pending_boot() is not None:
                return
    finally:
        try:
            conn.close()
        except OSError:
            pass
        logk.printl("fastboot", f"客户端断开 {host}", main.boot_time)


# Run the fastboot server until a client asks the device to leave the mode.
def fastboot_main(jumpinfo: str = "kernel_jump", port: int = DEFAULT_PORT) -> str:
    reset_state()
    kernel.screen_clear()
    logk.printl("fastboot", f"跳入 fastboot，jumpinfo={jumpinfo}", main.boot_time)
    printk.info(f"< PySpOS > fastboot v{PROTOCOL_VERSION}")
    printk.info(f"product: PySpOS / version: {ota.get_current_version()}")
    printk.info(f"unlocked: {'no' if is_locked() else 'yes'}")
    printk.info(f"等待 host 客户端连接 {BIND_HOST}:{port} ...\n")
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind((BIND_HOST, port))
    except OSError as exc:
        printk.error(f"无法监听 {BIND_HOST}:{port}: {exc}\n")
        try:
            server.close()
        except OSError:
            pass
        return "reboot"
    server.listen(1)
    try:
        while True:
            try:
                conn, address = server.accept()
            except OSError:
                break
            serve_client(conn, address)
            pending = take_pending_boot()
            if pending is not None:
                if pending == "poweroff":
                    kernel.exit()
                return "reboot"
    finally:
        try:
            server.close()
        except OSError:
            pass
        reset_state()
    return "reboot"


# Return the protocol version, used by the host client for its handshake.
def protocol_version() -> str:
    return PROTOCOL_VERSION
