#   calculate_zip_info.py
#   弃用垫片（2026-09-24）：历史上与根目录 build_update.py 功能重复。
#   为保持兼容保留本文件，但不再维护逻辑；直接转发到根目录 build_update.main()。
#   请统一使用：python build_update.py
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from build_update import main
except ImportError as e:
    raise RuntimeError(
        "无法加载根目录 build_update.py，请在项目根目录运行 python build_update.py"
    ) from e

if __name__ == "__main__":
    print("提示：src/calculate_zip_info.py 已弃用，已转发到根目录 build_update.py")
    main()
else:
    # 被 import 时不抛异常（历史行为是抛 RuntimeError，已修正为兼容模式）
    pass
