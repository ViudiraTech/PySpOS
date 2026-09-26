'''
 *
 *      audit.py
 *      Lightweight append-only audit log.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import os
import time

AUDIT_FILENAME = os.path.join("etc", "audit.log")


# Absolute path of the audit log for one root directory.
def _audit_path(root_dir: str) -> str:
    return os.path.join(root_dir, AUDIT_FILENAME)


# Append one audit record. Never raises, so logging cannot break the caller.
def audit(root_dir: str, actor: str, action: str, detail: str = "") -> None:
    try:
        path = _audit_path(root_dir)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        line = f"{ts} actor={actor} action={action} {detail}\n"
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass
