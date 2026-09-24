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
