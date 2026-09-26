'''
 *
 *      bootmode.py
 *      Boot mode request: the PySpOS counterpart of the AOSP BCB
 *      "boot-fastboot" message.
 *
 *      A reboot has to be able to come back into fastboot instead of the
 *      shell, and that intent has to outlive the process that asked for it.
 *      The request lives in the protected boot directory, is written before
 *      the restart and consumed by the next kernel.loop().
 *
 *      2026/9/26 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import os

import secure_boot

# Normal system boot, the default when no request is pending.
MODE_NORMAL = "normal"

# Boot straight into the fastboot protocol server.
MODE_FASTBOOT = "fastboot"

# Every mode the request file may hold.
VALID_MODES = (MODE_NORMAL, MODE_FASTBOOT)

# File holding the pending request inside the protected boot directory.
REQUEST_NAME = "boot_mode"


# Return the path of the boot mode request for a root directory.
def request_path(root_dir):
    return os.path.join(root_dir, secure_boot.PROTECTED_DIR, REQUEST_NAME)


# Read the pending mode, reporting MODE_NORMAL when nothing valid is stored.
# A missing or damaged request must never keep the device out of the shell.
def read_mode(root_dir):
    path = request_path(root_dir)
    try:
        with open(path, "r", encoding="utf-8") as stream:
            value = stream.read().strip()
    except OSError:
        return MODE_NORMAL
    return value if value in VALID_MODES else MODE_NORMAL


# Store a boot mode request, reporting whether it was written.
def request_mode(root_dir, mode):
    if mode not in VALID_MODES:
        return False
    path = request_path(root_dir)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as stream:
            stream.write(mode)
    except OSError:
        return False
    return True


# Drop any pending request, so the next boot goes to the system again.
def clear_mode(root_dir):
    path = request_path(root_dir)
    try:
        if os.path.islink(path):
            return
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


# Report whether the next boot must land in fastboot.
def wants_fastboot(root_dir):
    return read_mode(root_dir) == MODE_FASTBOOT
