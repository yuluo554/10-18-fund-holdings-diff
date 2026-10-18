"""证监会 eid 元数据快照读取（离线优先）。

M0：只实现"读本地快照 + 三态判定所需的最小解析"。
M1：接入在线抓取（net/csrc.py）并把结果冻结成快照；在线失败时仍可回放快照。

快照形状见 plan/04 §2.2：data/fixtures/disclosure.json
"""

import re

from . import serialize

SCHEMA = "funddiff/disclosure@1"

_PERIOD_RE = re.compile(r"(\d{4})\s*年\s*第\s*([1-4])\s*季度报告")


def parse_report_period(title):
    """从"…2026年第3季度报告"提取 2026Q3；解析不到返回 None。"""
    if not isinstance(title, str):
        return None
    match = _PERIOD_RE.search(title)
    if not match:
        return None
    return "%sQ%s" % (match.group(1), match.group(2))


def normalize_report(record):
    """把一条元数据归一为 {fundcode, report_period, report_send_date, title}。"""
    period = record.get("report_period") or parse_report_period(record.get("title") or record.get("newString"))
    return {
        "fundcode": record.get("fundcode"),
        "report_period": period,
        "report_send_date": record.get("report_send_date") or record.get("reportSendDate"),
        "title": record.get("title") or record.get("newString"),
    }


def load_disclosure(data_dir, path=None):
    """读取披露元数据快照。

    返回 {"available": bool, "reports": [...], "reason": str|None}。
    快照缺失或损坏 → available=False，调用方落"无数据"，不抛到 CLI 之外。
    """
    target = path
    if target is None:
        target = str(data_dir) + "/fixtures/disclosure.json"
    try:
        raw = serialize.read_json(target)
    except (OSError, ValueError):
        return {"available": False, "reports": [], "reason": "snapshot_missing"}

    if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
        return {"available": False, "reports": [], "reason": "schema_mismatch"}
    records = raw.get("reports")
    if not isinstance(records, list):
        return {"available": False, "reports": [], "reason": "reports_not_list"}

    reports = [normalize_report(item) for item in records if isinstance(item, dict)]
    reports = [item for item in reports if item["fundcode"] and item["report_period"]]
    reports.sort(key=lambda item: (item["report_period"], item["fundcode"]))
    return {"available": True, "reports": reports, "reason": None}
