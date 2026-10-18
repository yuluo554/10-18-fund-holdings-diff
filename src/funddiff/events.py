"""事件台账读取（M4）：`q<period>/events/<code>.json` 的统一入口。

设计同 M3 `diff.load_holdings`：
- 只读合成 fixtures；缺失返回 None，由 managers/scale 转成门禁失败（exit 1）；
- schema / 报告期 / 基金代码不一致 → ValueError（内部一致性，exit 5）；
- 本模块不做任何业务判定，只做加载与结构校验，保证两个子命令读同一份台账。
"""

import json
from pathlib import Path

from . import serialize

SCHEMA = "funddiff/events@1"


def events_path(data_dir, period, fund_code):
    return Path(data_dir) / "fixtures" / ("q" + period.lower()) / "events" / (
        fund_code + ".json")


def input_pointer(period, fund_code):
    """产物里的输入指针（相对 fixtures 根，POSIX 分隔符）。"""
    return "q%s/events/%s.json" % (period.lower(), fund_code)


def load_events(data_dir, period, fund_code):
    path = events_path(data_dir, period, fund_code)
    if not path.is_file():
        return None
    return json.loads(serialize.read_text(path))


def validate_events(payload, period, fund_code):
    if not isinstance(payload, dict):
        raise ValueError("内部一致性：events 台账根不是对象（%s）" % fund_code)
    if payload.get("schema") != SCHEMA:
        raise ValueError("内部一致性：events schema 不符：%r（%s）" % (
            payload.get("schema"), fund_code))
    if payload.get("report_period") != period:
        raise ValueError("内部一致性：events 报告期 %r 与请求 %r 不一致（%s）" % (
            payload.get("report_period"), period, fund_code))
    if payload.get("fund_code") != fund_code:
        raise ValueError("内部一致性：events 基金代码 %r 与请求 %r 不一致" % (
            payload.get("fund_code"), fund_code))
    if not isinstance(payload.get("managers"), list):
        raise ValueError("内部一致性：events.managers 必须是列表（%s）" % fund_code)
    if not isinstance(payload.get("scale"), dict):
        raise ValueError("内部一致性：events.scale 必须是对象（%s）" % fund_code)
    return payload
