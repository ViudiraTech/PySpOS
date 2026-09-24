#
#   common/audit.py
#   轻量审计日志：记录 root/lock 等敏感操作。失败时静默忽略，绝不阻塞主流程。
#
import os
import time

AUDIT_FILENAME = os.path.join("etc", "audit.log")


def _audit_path(root_dir: str) -> str:
    return os.path.join(root_dir, AUDIT_FILENAME)


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
