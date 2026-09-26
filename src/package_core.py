'''
 *
 *      package_core.py
 *      Loader that makes pkg.py the implementation of this module.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import importlib.util
import os
import sys

_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pkg.py")
_spec = importlib.util.spec_from_file_location("_pyspos_package_core", _path)
if _spec is None or _spec.loader is None:
    raise ImportError("无法加载包管理核心")
_module = importlib.util.module_from_spec(_spec)
sys.modules[__name__] = _module
_spec.loader.exec_module(_module)
