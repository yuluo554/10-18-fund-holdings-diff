"""证监会 eid 元数据快照读取（离线优先）。

M1：读本地快照（聚合或按季度目录），三态判定所需的最小解析；在线抓取留 M2。
快照形状见 plan/04 §2.2：
  data/fixtures/disclosure.json                  # 聚合
  data/fixtures/q<period>/disclosure.json        # 按季快照
"""

import os
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
    period = record.get("report_period") or parse_report_period(
        record.get("title") or record.get("newString"))
    return {
        "fundcode": record.get("fundcode"),
        "report_period": period,
        "report_send_date": record.get("report_send_date") or record.get("reportSendDate"),
        "title": record.get("title") or record.get("newString"),
    }


def _snapshot_candidates(data_dir, period):
    fixture_dir = os.path.join(str(data_dir), "fixtures")
    candidates = []
    if period:
        candidates.append(os.path.join(fixture_dir, "q" + period.lower(), "disclosure.json"))
    candidates.append(os.path.join(fixture_dir, "disclosure.json"))
    return candidates


def load_disclosure(data_dir, path=None, period=None):
    """读取披露元数据快照。

    返回 {"available": bool, "reports": [...], "reason": str|None, "snapshot": str|None}。
    - path 显式给出时只读该文件；
    - period 给出时优先读按季快照，缺失才回落到聚合快照；
    - 快照缺失或损坏 → available=False，调用方落"无数据"，不抛到 CLI 之外。
    """
    if path is not None:
        candidates = [str(path)]
    else:
        candidates = _snapshot_candidates(data_dir, period)

    target = None
    for candidate in candidates:
        if os.path.isfile(candidate):
            target = candidate
            break
    if target is None:
        return {"available": False, "reports": [], "reason": "snapshot_missing",
                "snapshot": None}

    try:
        raw = serialize.read_json(target)
    except (OSError, ValueError):
        return {"available": False, "reports": [], "reason": "snapshot_unreadable",
                "snapshot": target}

    if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
        return {"available": False, "reports": [], "reason": "schema_mismatch",
                "snapshot": target}
    if raw.get("available") is False:
        reason = raw.get("reason") or "upstream_unavailable"
        return {"available": False, "reports": [], "reason": reason, "snapshot": target}
    records = raw.get("reports")
    if not isinstance(records, list):
        return {"available": False, "reports": [], "reason": "reports_not_list",
                "snapshot": target}

    reports = [normalize_report(item) for item in records if isinstance(item, dict)]
    reports = [item for item in reports if item["fundcode"] and item["report_period"]]
    reports.sort(key=lambda item: (item["report_period"], item["fundcode"]))
    return {"available": True, "reports": reports, "reason": None, "snapshot": target}
