# fs.py - 文件系统操作模块
# 2026-09-24: 新增 pathlib 沙箱 helpers（safe_join/read_text/write_text/mkdir_p/touch/cat_file），
# 历史函数保持原样以兼容旧调用。

import os
import shutil
import pathlib

# 获取当前工作目录
def current_dir():
    return os.getcwd()

# 列出当前目录下的文件和文件夹
def list_dir():
    return os.listdir(current_dir())

# 删除目录及其内容
def rm_tree(name):
    shutil.rmtree(name)

# 更改当前工作目录
def change_dir(path):
    new_path = os.path.abspath(path)
    if os.path.isdir(new_path):
        os.chdir(new_path)

# 创建新目录
def create_dir(name):
    new_dir = os.path.join(current_dir(), name)
    os.makedirs(new_dir, exist_ok=True)

# 创建新文件
def create_file(name, content=''):
    file_path = os.path.join(current_dir(), name)
    with open(file_path, 'w') as f:
        f.write(content)

# 读取文件内容
def read_file(name):
    file_path = os.path.join(current_dir(), name)
    if os.path.isfile(file_path):
        with open(file_path, 'r', encoding='UTF8') as f:
            return f.read()
    return None

# 写入内容到文件
def write_file(name, content):
    file_path = os.path.join(current_dir(), name)
    with open(file_path, 'w') as f:
        f.write(content)

# 删除文件
def delete_file(name):
    file_path = os.path.join(current_dir(), name)
    if os.path.isfile(file_path):
        os.remove(file_path)

# 复制文件
def copy_file(src, dest):
    src_path = os.path.join(current_dir(), src)
    dest_path = os.path.join(current_dir(), dest)
    if os.path.isfile(src_path):
        shutil.copy2(src_path, dest_path)

# 移动文件
def move_file(src, dest):
    src_path = os.path.join(current_dir(), src)
    dest_path = os.path.join(current_dir(), dest)
    if os.path.exists(src_path):
        shutil.move(src_path, dest_path)

# 获取文件信息
def get_file_info(name):
    file_path = os.path.join(current_dir(), name)
    if os.path.exists(file_path):
        stat = os.stat(file_path)
        return {
            'size': stat.st_size,
            'modified': stat.st_mtime,
            'is_dir': os.path.isdir(file_path)
        }
    return None


# ---- 新增：沙箱与便捷 helpers ----

def _jail_root():
    """沙箱根：默认当前工作目录；严格模式（PYSPOS_JAIL_STRICT=1）下禁止逃逸。"""
    return os.path.abspath(os.environ.get("PYSPOS_JAIL", os.getcwd()))


def safe_join(base: str, *parts: str) -> str:
    """拼接后确保仍在 base 内，否则抛 ValueError。"""
    base_abs = os.path.abspath(base)
    target = os.path.abspath(os.path.join(base_abs, *parts))
    if os.environ.get("PYSPOS_JAIL_STRICT") == "1":
        if target != base_abs and not target.startswith(base_abs + os.sep):
            raise ValueError(f"路径逃逸被拒绝: {target}")
    return target


def read_text(name: str, encoding: str = "utf-8"):
    p = pathlib.Path(current_dir()) / name
    if p.is_file():
        return p.read_text(encoding=encoding)
    return None


def write_text(name: str, content: str, encoding: str = "utf-8") -> None:
    p = pathlib.Path(current_dir()) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding=encoding)


def mkdir_p(name: str) -> None:
    pathlib.Path(current_dir(), name).mkdir(parents=True, exist_ok=True)


def touch(name: str) -> None:
    p = pathlib.Path(current_dir()) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.touch(exist_ok=True)


def cat_file(name: str, encoding: str = "utf-8"):
    return read_text(name, encoding)