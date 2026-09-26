'''
 *
 *      logk.py
 *      Timestamped log lines with severity levels.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import time
import os
from typing import Optional

# log levels, added on 2026-09-24; printl stays compatible and the default is INFO.
_LEVELS = {"DEBUG": 10, "INFO": 20, "WARN": 30, "ERROR": 40}
_current_level = _LEVELS.get(os.environ.get("PYSPOS_LOG_LEVEL", "INFO").upper(), 20)

# The shared boot reference, captured once at import. A default taken per call
# would restart the clock on every line and report every line as 0.000000s
# elapsed; the caller that really knows the boot time still passes it in.
_BOOT_TIME = time.time()

# Set the global severity threshold; an unknown name falls back to INFO.
def set_level(level: str) -> None:
    global _current_level
    _current_level = _LEVELS.get(str(level).upper(), 20)

# Report whether a severity is at or above the current threshold.
def _allowed(level: str) -> bool:
    return _LEVELS.get(level, 20) >= _current_level

# Format an elapsed time as a fixed-width seconds column.
def _format_timestamp(elapsed: float) -> str:
    return f"{elapsed:10.6f}"

# Return the current time, to be used as the boot reference.
def get_boot_time() -> float:
    return time.time()

# Print one log line prefixed with the elapsed time and the module name.
def printl(
    module: str,
    message: str,
    boot_time: Optional[float] = None
) -> None:
    # default the reference time
    if boot_time is None:
        boot_time = _BOOT_TIME
    
    # compute the elapsed time and format the timestamp
    elapsed = time.time() - boot_time
    timestamp = _format_timestamp(elapsed)
    
    # join and print the final log line
    log_line = f"[{timestamp}] {module}: {message}"
    print(log_line)


# Print a DEBUG line when DEBUG is enabled.
def debug(module: str, message: str, boot_time: Optional[float] = None) -> None:
    if _allowed("DEBUG"):
        printl(module, f"DEBUG: {message}", boot_time)


# Print an INFO line when INFO is enabled.
def info(module: str, message: str, boot_time: Optional[float] = None) -> None:
    if _allowed("INFO"):
        printl(module, message, boot_time)


# Print a WARN line when WARN is enabled.
def warn(module: str, message: str, boot_time: Optional[float] = None) -> None:
    if _allowed("WARN"):
        printl(module, f"WARN: {message}", boot_time)


# Print an ERROR line when ERROR is enabled.
def error(module: str, message: str, boot_time: Optional[float] = None) -> None:
    if _allowed("ERROR"):
        printl(module, f"ERROR: {message}", boot_time)
