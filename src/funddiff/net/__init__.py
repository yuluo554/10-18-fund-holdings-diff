"""网络访问层（M2 落地）。

**全项目唯一允许 import 网络库的位置**（K6）。
其它模块出现 socket / urllib / http / ssl / requests 即测试失败。

M0 只落结构与契约；实际抓取在 M2 填充。
"""

from .http import Fetcher, FetchError  # noqa: F401

__all__ = ["Fetcher", "FetchError"]
