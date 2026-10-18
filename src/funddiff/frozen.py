"""冻结文件清单：SHA256 计算、MANIFEST 构建与校验。

配置包与合成 fixtures 共用这一份实现，避免"工具一套、自检另一套"。
本模块只读文件、不写盘；写盘仍走 serialize.write_json。
"""

import hashlib
from pathlib import Path

MANIFEST_NAME = "MANIFEST.json"


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(65536)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def iter_payload_files(root, exclude=(MANIFEST_NAME,)):
    """按 POSIX 相对路径升序列出冻结文件（排除清单自身）。"""
    root = Path(root)
    excluded = set(exclude)
    files = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative in excluded:
            continue
        files.append(relative)
    return sorted(files)


def build_manifest(root, schema, extra=None):
    root = Path(root)
    payload = {
        "schema": schema,
        "files": {},
    }
    if extra:
        for key in sorted(extra):
            payload[key] = extra[key]
    for relative in iter_payload_files(root):
        path = root / relative
        payload["files"][relative] = {
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }
    return payload


def verify_manifest(root, manifest, schema):
    """返回问题列表；空列表表示逐文件一致且没有多余文件。"""
    problems = []
    if not isinstance(manifest, dict):
        return ["MANIFEST 不是对象"]
    if manifest.get("schema") != schema:
        problems.append("MANIFEST schema 不符：%r" % (manifest.get("schema"),))
        return problems
    recorded = manifest.get("files")
    if not isinstance(recorded, dict):
        return ["MANIFEST 缺少 files 对象"]

    root = Path(root)
    actual = set(iter_payload_files(root))
    listed = set(recorded)
    for missing in sorted(listed - actual):
        problems.append("清单登记但文件缺失：%s" % missing)
    for extra in sorted(actual - listed):
        problems.append("文件存在但清单未登记：%s" % extra)

    for relative in sorted(listed & actual):
        expected = recorded.get(relative)
        if not isinstance(expected, dict):
            problems.append("清单条目不是对象：%s" % relative)
            continue
        path = root / relative
        digest = sha256_file(path)
        if digest != expected.get("sha256"):
            problems.append("SHA256 不符：%s" % relative)
        if path.stat().st_size != expected.get("bytes"):
            problems.append("字节数不符：%s" % relative)
    return problems


def compare_tree(expected_root, actual_root, exclude=(MANIFEST_NAME,)):
    """逐字节比较两棵目录树；返回差异列表。"""
    expected_root = Path(expected_root)
    actual_root = Path(actual_root)
    expected_files = iter_payload_files(expected_root, exclude=exclude)
    actual_files = iter_payload_files(actual_root, exclude=exclude)
    problems = []
    for missing in sorted(set(expected_files) - set(actual_files)):
        problems.append("重生成缺少文件：%s" % missing)
    for extra in sorted(set(actual_files) - set(expected_files)):
        problems.append("重生成多出文件：%s" % extra)
    for relative in sorted(set(expected_files) & set(actual_files)):
        if (expected_root / relative).read_bytes() != (actual_root / relative).read_bytes():
            problems.append("重生成字节不一致：%s" % relative)
    return problems
