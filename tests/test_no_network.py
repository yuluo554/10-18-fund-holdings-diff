"""零网络门禁：只有 funddiff/net/ 可以 import 网络库。

用 AST 覆盖两种容易漏判的形态：
- `import socket` / `import urllib.request`
- `from urllib import request` / `from . import x`（相对导入 module 为 None）
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "funddiff"
NET_DIR = SRC / "net"

FORBIDDEN_ROOTS = {"socket", "urllib", "http", "ssl", "requests", "httpx", "aiohttp", "ftplib"}


def iter_python_files():
    for path in sorted(SRC.rglob("*.py")):
        yield path


def imported_roots(tree):
    """返回该模块引用到的顶层包名集合（绝对导入 + from-import + 相对导入的绝对落点）。"""
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                roots.add(node.module.split(".")[0])
            else:
                # `from . import x`：x 可能是子模块名，按原名收集
                for alias in node.names:
                    roots.add(alias.name.split(".")[0])
    return roots


def test_scan_surface_is_not_empty():
    files = list(iter_python_files())
    assert len(files) >= 10, "扫描面异常（%d 个文件）" % len(files)


def test_no_network_imports_outside_net_package():
    offenders = []
    for path in iter_python_files():
        if NET_DIR in path.parents:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        hits = imported_roots(tree) & FORBIDDEN_ROOTS
        if hits:
            offenders.append((str(path.relative_to(ROOT)), sorted(hits)))
    assert not offenders, "net/ 之外出现网络 import：%s" % offenders


def test_net_package_is_the_only_network_owner():
    net_files = [path for path in NET_DIR.rglob("*.py")]
    assert net_files, "net/ 目录缺失"


def test_gate_detects_injected_network_import(tmp_path, monkeypatch):
    """自证：把同样的 AST 逻辑喂一个含网络 import 的模块，必须检出。"""
    sample = tmp_path / "probe.py"
    sample.write_text("import urllib.request\nfrom socket import socket\n", encoding="utf-8")
    tree = ast.parse(sample.read_text(encoding="utf-8"), filename=str(sample))
    assert imported_roots(tree) & FORBIDDEN_ROOTS == {"urllib", "socket"}


def test_gate_detects_relative_from_import():
    tree = ast.parse("from . import socket\n", filename="<probe>")
    assert "socket" in imported_roots(tree)
