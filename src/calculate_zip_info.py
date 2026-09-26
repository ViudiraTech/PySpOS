'''
 *
 *      calculate_zip_info.py
 *      Deprecated shim forwarding to the top-level build_update.py.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

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
    # being imported must not raise; it used to raise RuntimeError and is now in compatibility mode
    pass
