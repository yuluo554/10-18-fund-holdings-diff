"""自选清单存储（M1，纯本地，零网络）。

- 唯一键 code；重复添加 = 幂等更新，added_on 保留首次值；
- 全表按 code 升序；
- 文件不存在视为空清单，读取不创建目录；写入时才建目录。
"""

import datetime
import re
from pathlib import Path

from . import serialize

SCHEMA = "funddiff/watchlist@1"
CODE_RE = re.compile(r"^\d{6}$")


class StoreError(Exception):
    """清单操作非法输入。对应退出码 2。"""


def validate_code(code):
    if not isinstance(code, str) or not CODE_RE.match(code):
        raise StoreError("基金代码必须是 6 位数字，实际为 %r" % (code,))
    return code


class Watchlist(object):
    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        if not self.path.is_file():
            return {"schema": SCHEMA, "funds": []}
        try:
            data = serialize.read_json(self.path)
        except ValueError as exc:
            raise StoreError("清单文件损坏：%s（%s）" % (self.path, exc))
        if not isinstance(data, dict) or data.get("schema") != SCHEMA:
            raise StoreError("清单文件 schema 不符：%s" % self.path)
        funds = data.get("funds")
        if not isinstance(funds, list):
            raise StoreError("清单文件 funds 必须是列表：%s" % self.path)
        return data

    def save(self, data):
        funds = sorted(data.get("funds", []), key=lambda item: item["code"])
        payload = {"schema": SCHEMA, "funds": funds}
        serialize.write_json(self.path, payload)
        return payload

    def add(self, code, name=None, note=None, today=None):
        """幂等添加。返回 (action, entry)，action ∈ created / updated / unchanged。"""
        code = validate_code(code)
        data = self.load()
        existing = None
        for entry in data["funds"]:
            if entry["code"] == code:
                existing = entry
                break

        if existing is None:
            existing = {
                "code": code,
                "name": name,
                "added_on": today or datetime.date.today().isoformat(),
                "note": note,
            }
            data["funds"].append(existing)
            self.save(data)
            return "created", existing

        changed = False
        if name is not None and existing.get("name") != name:
            existing["name"] = name
            changed = True
        if note is not None and existing.get("note") != note:
            existing["note"] = note
            changed = True
        if changed:
            self.save(data)
            return "updated", existing
        return "unchanged", existing

    def remove(self, code):
        code = validate_code(code)
        data = self.load()
        remaining = [entry for entry in data["funds"] if entry["code"] != code]
        if len(remaining) == len(data["funds"]):
            return False
        data["funds"] = remaining
        self.save(data)
        return True

    def list_all(self):
        """只读：返回按代码升序的副本，不写盘、不建目录。"""
        funds = self.load()["funds"]
        return sorted((dict(entry) for entry in funds), key=lambda item: item["code"])
