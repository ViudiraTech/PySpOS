#
#   logk.py
#   日志处理和打印
#
#   2026/1/23 By GoutouStdio
#   @2022~2026 GoutouStdio. Open all rights.

import time
import os
from typing import Optional

# 日志级别（2026-09-24 新增，printl 保持兼容，默认 INFO）。
_LEVELS = {"DEBUG": 10, "INFO": 20, "WARN": 30, "ERROR": 40}
_current_level = _LEVELS.get(os.environ.get("PYSPOS_LOG_LEVEL", "INFO").upper(), 20)

def set_level(level: str) -> None:
    global _current_level
    _current_level = _LEVELS.get(str(level).upper(), 20)

def _allowed(level: str) -> bool:
    return _LEVELS.get(level, 20) >= _current_level

# 格式化时间戳
def _format_timestamp(elapsed: float) -> str:
    return f"{elapsed:10.6f}"

# 获取启动时间
def get_boot_time() -> float:
    return time.time()

# 打印一条日志
def printl(
    module: str,
    message: str,
    boot_time: Optional[float] = None
) -> None:
    # 初始化基准时间
    if boot_time is None:
        boot_time = time.time()
    
    # 计算流逝时间并格式化时间戳
    elapsed = time.time() - boot_time
    timestamp = _format_timestamp(elapsed)
    
    # 拼接并打印最终日志行
    log_line = f"[{timestamp}] {module}: {message}"
    print(log_line)


def debug(module: str, message: str, boot_time: Optional[float] = None) -> None:
    if _allowed("DEBUG"):
        printl(module, f"DEBUG: {message}", boot_time)


def info(module: str, message: str, boot_time: Optional[float] = None) -> None:
    if _allowed("INFO"):
        printl(module, message, boot_time)


def warn(module: str, message: str, boot_time: Optional[float] = None) -> None:
    if _allowed("WARN"):
        printl(module, f"WARN: {message}", boot_time)


def error(module: str, message: str, boot_time: Optional[float] = None) -> None:
    if _allowed("ERROR"):
        printl(module, f"ERROR: {message}", boot_time)