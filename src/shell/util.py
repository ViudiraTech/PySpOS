#
#   shell/util.py
#   路径/文件名 helpers（由 main.py 拆分而来，行为保持不变）。
#

import os
import re


# 获取应用路径
def get_app_path(app_name: str) -> str:
    # 使用当前工作目录的apps目录
    return os.path.join(os.getcwd(), "apps", app_name)

# 获取spf应用路径
def get_spf_path(app_name: str) -> str:
    # 使用当前工作目录的spfapps目录
    return os.path.join(os.getcwd(), "spfapps", app_name)

# 验证文件名安全性
def is_safe_filename(filename: str) -> bool:
    return not (re.search(r'\.\./', filename) or os.path.isabs(filename))

