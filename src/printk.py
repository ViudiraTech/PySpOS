# printk.py - 打印信息模块

# 颜色定义
RED_COLOR = "\033[91m"
GREEN_COLOR = "\033[92m"
RESET_COLOR = "\033[0m"
YELLOW_COLOR = "\033[93m"

# 打印带有 [ OK ] 前缀的字符串
def ok(message: str) -> None:
    print(f"[{GREEN_COLOR} OK {RESET_COLOR}] {message}")

# 打印带有 [ ERROR ] 前缀的字符串
def error(message: str) -> None:
    print(f"[{RED_COLOR} ERROR {RESET_COLOR}] {message}")

# 打印带有 [ WARN ] 前缀的字符串
def warn(message: str) -> None:
    print(f"[{YELLOW_COLOR} WARN {RESET_COLOR}] {message}")

# 打印带有 [ INFO ] 前缀的字符串
def info(message: str) -> None:
    print(f"[ INFO ] {message}")

def confirm(prompt: str, default: bool = False, max_retries: int = 5) -> bool:
    """y/n 确认。空输入取 default；连续无效达上限返回 default，避免坏终端死循环。

    默认 default=False（保守语义：拿不准就当拒绝），max_retries=5。
    历史调用 confirm(prompt) 行为不变，只是多了防呆上限。
    """
    import ttyutil
    for _ in range(max_retries + 1):
        try:
            user_input = ttyutil.read_line(f"{prompt}(y/n): ").lower()
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