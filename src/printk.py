'''
 *
 *      printk.py
 *      Coloured console output helpers.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

RED_COLOR = "\033[91m"
GREEN_COLOR = "\033[92m"
RESET_COLOR = "\033[0m"
YELLOW_COLOR = "\033[93m"

# Print a message with a green [ OK ] prefix.
def ok(message: str) -> None:
    print(f"[{GREEN_COLOR} OK {RESET_COLOR}] {message}")

# Print a message with a red [ ERROR ] prefix.
def error(message: str) -> None:
    print(f"[{RED_COLOR} ERROR {RESET_COLOR}] {message}")

# Print a message with a yellow [ WARN ] prefix.
def warn(message: str) -> None:
    print(f"[{YELLOW_COLOR} WARN {RESET_COLOR}] {message}")

# Print a message with a plain [ INFO ] prefix.
def info(message: str) -> None:
    print(f"[ INFO ] {message}")

# Ask a y/n question; an empty answer takes the default.
# Too many invalid answers returns the default too, so a broken terminal cannot spin forever.
# The default is False, the conservative reading of an unsure answer, and max_retries is 5.
# Calling confirm(prompt) behaves as it always did; it only gained that ceiling.
def confirm(prompt: str, default: bool = False, max_retries: int = 5) -> bool:
    try:
        import ttyutil
    except ImportError:
        ttyutil = None
    for _ in range(max_retries + 1):
        try:
            question = f"{prompt}(y/n): "
            user_input = (ttyutil.read_line(question) if ttyutil is not None
                          else input(question)).lower()
        except (EOFError, KeyboardInterrupt):
            raise
        if not user_input:
            return default
        if user_input in ["y", "yes", "是", "好"]:
            return True
        if user_input in ["n", "no", "否"]:
            return False
        print(f"\033[33m无效输入：{user_input}，请输入 y 或 n\033[0m")
    print(f"\033[33m多次输入无效，按默认（{'y' if default else 'n'}）继续\033[0m")
    return default
