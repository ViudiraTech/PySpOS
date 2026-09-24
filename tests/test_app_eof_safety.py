"""apps 的 EOF/中断安全：stdin 关闭不得导致真子进程空转吃 CPU。

背景：apps 从 in-process exec 改成了 fork 出来的真子进程后，
任何「input() 抛 EOFError → 通用 except → continue」的循环都会
永久占用一个 CPU 核。这里用 AST 静态检查每个 app 的循环体，
并跑真实子进程做行为验证。
"""

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


def _handles_eof(handler_names, source_lines):
    """判断 except 子句是否覆盖 EOFError/KeyboardInterrupt。"""
    for n in handler_names:
        if n in EOLF:
            return True
        if n in ("BaseException", "Exception") and any(
                "EOFError" in ln or "KeyboardInterrupt" in ln
                for ln in source_lines):
            return True
    return False


def test_no_app_loops_swallow_eof():
    """任何含 input() 的 while 循环都必须显式处理 EOF。"""
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


def test_child_process_has_eof_safety_net():
    """forkexec 子进程入口必须有 EOF 兜底（apps 漏写时的最后防线）。"""
    src = FORKEXEC.read_text(encoding="utf-8")
    assert "except EOFError" in src
    tree = ast.parse(src)
    found = any(
        isinstance(n, ast.ExceptHandler) and isinstance(n.type, ast.Name)
        and n.type.id == "EOFError" for n in ast.walk(tree))
    assert found, "forkexec._child_main 缺少 EOFError 兜底"


def test_zzlsb_exits_on_eof():
    """真实跑一次：stdin 立即 EOF 时必须快速退出，不刷屏。"""
    import subprocess
    src = (APPS / "zzlsb.py").resolve()
    p = subprocess.run([sys.executable, str(src)], input="", timeout=30,
                       capture_output=True, text=True,
                       env={**os.environ, "PYTHONPATH": f"{REPO / 'src'}{os.pathsep}{REPO / 'src' / 'apps'}"})
    out = p.stdout + p.stderr
    assert "EOF when reading a line" not in out, "仍在打印 EOF 错误"
    assert out.count("输入你猜的数字") <= 1, "EOF 后仍在循环刷屏"


def test_zzlsb_guessed_number_terminates():
    """正常交互路径：猜中后应退出。"""
    import re
    import subprocess
    src = (APPS / "zzlsb.py").read_text(encoding="utf-8")
    assert re.search(r"secret_number = random\.randint\(0,\s*\d+\)", src)
    # 让答案恒为 0，且用 __exec__ 触发守卫（与 shell fork 路径一致）
    patched = src.replace("secret_number = random.randint(0, 100)",
                          "secret_number = 0")
    patched = patched.replace('if __name__ == "__exec__":',
                              'if __name__ == "__exec__":')
    p = subprocess.run([sys.executable, "-c",
                        f'__name__="__exec__"\n{patched}'],
                       input="0\n", timeout=30, capture_output=True,
                       text=True,
                       env={**os.environ, "PYTHONPATH": f"{REPO / 'src'}{os.pathsep}{REPO / 'src' / 'apps'}"})
    assert "恭喜" in p.stdout, p.stdout + p.stderr
    assert p.returncode == 0
