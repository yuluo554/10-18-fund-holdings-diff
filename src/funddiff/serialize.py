"""唯一写盘出口（K1）。

全项目所有 JSON 产物都必须经 write_json()：
- sort_keys=True / ensure_ascii=False / indent=2
- UTF-8 显式编码、newline="\\n"、结尾换行
- 写临时文件后 os.replace 原子替换

不在各子命令里各写各的 open()+json.dump()。
"""

import json
import os
import tempfile
from pathlib import Path

JSON_KWARGS = {"sort_keys": True, "ensure_ascii": False, "indent": 2}


def dumps(data):
    """规范化 JSON 文本（含结尾换行）。"""
    return json.dumps(data, **JSON_KWARGS) + "\n"


def write_text(path, text):
    """原子写文本：同目录临时文件 + os.replace。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        dir=str(path.parent),
        prefix=path.name + ".",
        suffix=".tmp",
        delete=False,
    )
    try:
        with handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(handle.name, str(path))
    except Exception:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise
    return path


def write_json(path, data):
    return write_text(path, dumps(data))


def read_json(path):
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def read_text(path):
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        return handle.read()
