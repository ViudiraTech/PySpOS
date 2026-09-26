'''
 *
 *      conftest.py
 *      pytest bootstrap: launcher startup marker and the repo paths on sys.path.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

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


# Restore the working directory after each test, so a case that chdirs cannot break the ones that use absolute paths.
@pytest.fixture(autouse=True)
def _keep_cwd_at_repo_root():
    root = os.getcwd()
    yield
    try:
        os.chdir(root)
    except OSError:
        pass
