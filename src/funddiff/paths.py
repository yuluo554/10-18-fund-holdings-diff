"""数据目录解析。

配置包（data/config/app.json）不在 wheel 内：非 editable 安装时必须用
--data-dir 或 FUNDDIFF_DATA_DIR 显式指向仓库的 data/ 目录。
"""

import os
from pathlib import Path


class DataDirError(Exception):
    """数据目录不可用（缺失 / 缺配置）。对应退出码 2。"""


def _is_data_dir(path):
    return (Path(path) / "config" / "app.json").is_file()


def resolve_data_dir(explicit=None, cwd=None, package_file=None):
    """按固定优先级解析数据目录。

    1. explicit（--data-dir）
    2. 环境变量 FUNDDIFF_DATA_DIR
    3. 当前工作目录下的 data/
    4. 包文件向上查找得到的 data/
    """
    if explicit:
        path = Path(explicit)
        if not _is_data_dir(path):
            raise DataDirError(
                "数据目录不可用：%s（缺少 config/app.json）" % path
            )
        return path

    env_value = os.environ.get("FUNDDIFF_DATA_DIR")
    if env_value:
        path = Path(env_value)
        if not _is_data_dir(path):
            raise DataDirError(
                "FUNDDIFF_DATA_DIR 指向的目录不可用：%s（缺少 config/app.json）" % path
            )
        return path

    base = Path(cwd) if cwd else Path.cwd()
    candidate = base / "data"
    if _is_data_dir(candidate):
        return candidate

    if package_file is None:
        package_file = __file__
    here = Path(package_file).resolve()
    for parent in here.parents:
        candidate = parent / "data"
        if _is_data_dir(candidate):
            return candidate

    raise DataDirError(
        "找不到数据目录。请用 --data-dir 指向仓库的 data/ 目录，"
        "或设置环境变量 FUNDDIFF_DATA_DIR。"
    )


def store_path(explicit=None, cwd=None, default_relative="local_data/watchlist.json"):
    """自选清单路径：显式优先，否则相对当前工作目录的默认值。"""
    if explicit:
        return Path(explicit)
    base = Path(cwd) if cwd else Path.cwd()
    return base / default_relative
