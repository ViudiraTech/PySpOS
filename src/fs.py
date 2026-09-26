'''
 *
 *      fs.py
 *      File system helpers, including the pathlib sandbox ones.
 *
 *      2026/9/25 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import os
import shutil
import pathlib

# Return the current working directory.
def current_dir():
    return os.getcwd()

# List the entries of the current directory.
def list_dir():
    return os.listdir(current_dir())

# Remove a directory and everything inside it.
def rm_tree(name):
    shutil.rmtree(name)

# Change into path when it is an existing directory, otherwise do nothing.
def change_dir(path):
    new_path = os.path.abspath(path)
    if os.path.isdir(new_path):
        os.chdir(new_path)

# Create a directory under the current one, parents included.
def create_dir(name):
    new_dir = os.path.join(current_dir(), name)
    os.makedirs(new_dir, exist_ok=True)

# Create a file under the current directory, overwriting existing content.
def create_file(name, content=''):
    file_path = os.path.join(current_dir(), name)
    with open(file_path, 'w') as f:
        f.write(content)

# Return the text of a file under the current directory, or None.
def read_file(name):
    file_path = os.path.join(current_dir(), name)
    if os.path.isfile(file_path):
        with open(file_path, 'r', encoding='UTF8') as f:
            return f.read()
    return None

# Write text to a file under the current directory, overwriting it.
def write_file(name, content):
    file_path = os.path.join(current_dir(), name)
    with open(file_path, 'w') as f:
        f.write(content)

# Delete a file under the current directory when it exists.
def delete_file(name):
    file_path = os.path.join(current_dir(), name)
    if os.path.isfile(file_path):
        os.remove(file_path)

# Copy a file inside the current directory, preserving metadata.
def copy_file(src, dest):
    src_path = os.path.join(current_dir(), src)
    dest_path = os.path.join(current_dir(), dest)
    if os.path.isfile(src_path):
        shutil.copy2(src_path, dest_path)

# Move a file inside the current directory when the source exists.
def move_file(src, dest):
    src_path = os.path.join(current_dir(), src)
    dest_path = os.path.join(current_dir(), dest)
    if os.path.exists(src_path):
        shutil.move(src_path, dest_path)

# Return size, mtime and the directory flag, or None when the path is gone.
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


# ---- added: sandbox and convenience helpers ----

# Return the sandbox root: the working directory by default.
# PYSPOS_JAIL picks another root and PYSPOS_JAIL_STRICT=1 forbids escaping it.
def _jail_root():
    return os.path.abspath(os.environ.get("PYSPOS_JAIL", os.getcwd()))


# Join a path and make sure it stays under base, raising ValueError otherwise.
def safe_join(base: str, *parts: str) -> str:
    base_abs = os.path.abspath(base)
    target = os.path.abspath(os.path.join(base_abs, *parts))
    if os.environ.get("PYSPOS_JAIL_STRICT") == "1":
        if target != base_abs and not target.startswith(base_abs + os.sep):
            raise ValueError(f"路径逃逸被拒绝: {target}")
    return target


# Return the text of a file under the current directory, or None.
def read_text(name: str, encoding: str = "utf-8"):
    p = pathlib.Path(current_dir()) / name
    if p.is_file():
        return p.read_text(encoding=encoding)
    return None


# Write text to a file under the current directory, creating parents as needed.
def write_text(name: str, content: str, encoding: str = "utf-8") -> None:
    p = pathlib.Path(current_dir()) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding=encoding)


# Create a directory under the current one, parents included.
def mkdir_p(name: str) -> None:
    pathlib.Path(current_dir(), name).mkdir(parents=True, exist_ok=True)


# Create an empty file under the current directory, parents included.
def touch(name: str) -> None:
    p = pathlib.Path(current_dir()) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.touch(exist_ok=True)


# Return the text of a file under the current directory, or None.
def cat_file(name: str, encoding: str = "utf-8"):
    return read_text(name, encoding)
