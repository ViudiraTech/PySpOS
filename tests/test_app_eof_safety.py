'''
 *
 *      test_app_eof_safety.py
 *      Apps must handle EOF: a closed stdin may not leave a forked child spinning on a core.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import ast
import os
import pathlib
import sys

sys._launcher_detected = True
sys.path.insert(0, "src")
sys.path.insert(0, "src/apps")

REPO = pathlib.Path(__file__).resolve().parent.parent
APPS = REPO / "src" / "apps"
FORKEXEC = REPO / "src" / "forkexec.py"

EOLF = {"EOFError", "KeyboardInterrupt"}


# Tell whether these except handler names really cover EOFError/KeyboardInterrupt, including via a broad clause that names them.
def _handles_eof(handler_names, source_lines):
    for n in handler_names:
        if n in EOLF:
            return True
        if n in ("BaseException", "Exception") and any(
                "EOFError" in ln or "KeyboardInterrupt" in ln
                for ln in source_lines):
            return True
    return False


# Every while loop calling input() must handle EOF explicitly, or a forked child spins on a core forever.
def test_no_app_loops_swallow_eof():
    offenders = []
    for py in sorted(APPS.glob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.While,)):
                continue
            uses_input = any(
                isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "input" for n in ast.walk(node))
            if not uses_input:
                continue
            for h in ast.walk(node):
                if not isinstance(h, ast.Try):
                    continue
                names = []
                for t in h.handlers:
                    exc = t.type
                    if isinstance(exc, ast.Name):
                        names.append(exc.id)
                    elif isinstance(exc, ast.Tuple):
                        names.extend(e.id for e in exc.elts
                                     if isinstance(e, ast.Name))
                src = (ast.get_source_segment(
                    py.read_text(encoding="utf-8"), h) or "")
                if not _handles_eof(names, src.splitlines()):
                    offenders.append(f"{py.name}:{h.lineno}")
    assert not offenders, f"以下循环未处理 EOF（会空转吃 CPU）: {offenders}"


# Regression lock: the forkexec child entry keeps an EOFError net as the last line of defence when an app forgets one.
def test_child_process_has_eof_safety_net():
    src = FORKEXEC.read_text(encoding="utf-8")
    assert "except EOFError" in src
    tree = ast.parse(src)
    found = any(
        isinstance(n, ast.ExceptHandler) and isinstance(n.type, ast.Name)
        and n.type.id == "EOFError" for n in ast.walk(tree))
    assert found, "forkexec._child_main 缺少 EOFError 兜底"


# Run it for real: with stdin at immediate EOF the app must exit 0 quickly, print no EOF traceback and not repeat the prompt.
def test_zzlsb_exits_on_eof():
    import subprocess
    src = (APPS / "zzlsb.py").read_text(encoding="utf-8")
    # Run it as __exec__, the name the shell's fork gives the child. Executing the
    # file directly only trips the "do not run me" guard, so the game never started
    # and this test asserted nothing about EOF at all.
    p = subprocess.run([sys.executable, "-c",
                        f'__name__="__exec__"\n{src}'],
                       input="", timeout=30, capture_output=True, text=True,
                       env={**os.environ, "PYTHONPATH": f"{REPO / 'src'}{os.pathsep}{REPO / 'src' / 'apps'}"})
    out = p.stdout + p.stderr
    assert "简单猜数字游戏" in out, f"游戏根本没运行: {out}"
    assert p.returncode == 0, f"EOF 后应以 0 退出，实际 {p.returncode}: {out}"
    assert "输入已结束" in out, f"EOF 后没有走退出分支: {out}"
    assert "EOF when reading a line" not in out, "仍在打印 EOF 错误"
    assert out.count("输入你猜的数字") <= 1, "EOF 后仍在循环刷屏"


# The normal interactive path still ends: answering correctly prints the win message and exits 0.
def test_zzlsb_guessed_number_terminates():
    import re
    import subprocess
    src = (APPS / "zzlsb.py").read_text(encoding="utf-8")
    assert re.search(r"secret_number = random\.randint\(0,\s*\d+\)", src)
    # Pin the answer to 0 so the single guess below is the right one
    patched = src.replace("secret_number = random.randint(0, 100)",
                          "secret_number = 0")
    p = subprocess.run([sys.executable, "-c",
                        f'__name__="__exec__"\n{patched}'],
                       input="0\n", timeout=30, capture_output=True,
                       text=True,
                       env={**os.environ, "PYTHONPATH": f"{REPO / 'src'}{os.pathsep}{REPO / 'src' / 'apps'}"})
    assert "恭喜" in p.stdout, p.stdout + p.stderr
    assert p.returncode == 0
