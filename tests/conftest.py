"""pytest 引导：模拟 launcher 启动标记，保证 import main 行为与真实启动一致。"""
import os
import sys

sys._launcher_detected = True

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
APPS = os.path.join(SRC, "apps")
for p in (SRC, APPS):
    if p not in sys.path:
        sys.path.insert(0, p)


import pytest


@pytest.fixture(autouse=True)
def _keep_cwd_at_repo_root():
    """测试不应依赖 CWD：前面的用例改了目录时，后续用绝对路径的用例仍要正常。"""
    root = os.getcwd()
    yield
    try:
        os.chdir(root)
    except OSError:
        pass
