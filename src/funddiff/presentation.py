# -*- coding: utf-8 -*-
"""报告模型组装（M5）：diff / managers / scale 的产物判定 → funddiff/report@1。

纪律：
- 判定全部在这里完成；report.py 只做零判定渲染（plan/03 §6.5）；
- K3：数值保持字符串十进制，缺失 null ≠ 0，渲染前不做换算；
- K10：来源标注、页脚、披露状态标签全部来自冻结配置；
- K2：时间字段固定取当天日期（window.today_iso），同日双跑字节一致。
"""

import datetime

from . import diff as diff_module
from . import eid, events, managers as managers_module
from . import report as report_module
from . import scale as scale_module
from . import serialize, store, window

SCHEMA = report_module.REPORT_JSON_SCHEMA

SECTION_DISCLOSURE = "披露状态"
SECTION_CHANGES = "变动摘要"
SECTION_DETAILS = "变动明细"
SECTION_MANAGERS = "经理变更"
SECTION_SCALE = "规模变动"
SECTION_CONFLICTS = "口径冲突"

DISCLOSURE_KEYS = ("已披露", "待披露", "无数据")


class ReportError(Exception):
    """报告组装阶段的门禁类失败（清单空/快照缺失/上期报告目录不合法），退出码 1。"""


def _labels(config):
    labels = config["diff"]["status_labels"]
    return {
        "new": labels[0],
        "exit": labels[1],
        "increase": labels[2],
        "decrease": labels[3],
        "unchanged": labels[4],
        "pending": config["diff"]["pending_label"],
    }


def _status_text(diff_status, status_labels):
    """diff 状态 → 报告文案；未知状态返回原文（不猜、不合并）。"""
    mapping = {
        diff_module.STATUS_NEW: "新进",
        diff_module.STATUS_EXIT: "退出",
        diff_module.STATUS_INCREASE: "加仓",
        diff_module.STATUS_DECREASE: "减仓",
        diff_module.STATUS_UNCHANGED: "不变",
    }
    return mapping.get(diff_status, diff_status)


def _disclosure_counts(states):
    counts = {key: 0 for key in DISCLOSURE_KEYS}
    for state in states:
        counts[state] = counts.get(state, 0) + 1
    return counts


def assemble(data_dir, config, codes, period, as_of, prev_report_dir=None):
    """组装 funddiff/report@1 模型（只组装，不渲染、不落盘）。

    抛 ReportError（清单/快照门禁）、ValueError（内部一致性）。
    """
    window.parse_period(period)
    info = window.window_for_period(config, period)

    diff_payload = diff_module.build(data_dir, config, codes, period,
                                     config["diff"]["mode"])
    managers_payload = managers_module.build(data_dir, config, codes, period)
    scale_payload = scale_module.build(data_dir, config, codes, period)

    by_code_managers = {fund["fund_code"]: fund for fund in managers_payload["funds"]}
    by_code_scale = {fund["fund_code"]: fund for fund in scale_payload["funds"]}

    disclosure = eid.load_disclosure(data_dir, period=period)
    labels = _labels(config)
    source_label = config["sources"]["eastmoney_position_json"]["label"]
    manager_source_label = config["sources"]["eastmoney_managers"]["label"]
    scale_source_label = config["sources"]["eastmoney_scale"]["label"]

    prev_summary = _load_prev_report(prev_report_dir, period)

    funds = []
    states = []
    changes = {}
    for fund in diff_payload["funds"]:
        code = fund["fund_code"]
        state = window.disclosure_status(
            disclosure["available"], disclosure["reports"], code, period,
            as_of=as_of)
        states.append(state)

        sections = []
        sections.append(_disclosure_section(state, info))
        changes_section, counts = _changes_section(fund, labels)
        for key, value in counts.items():
            changes[key] = changes.get(key, 0) + value
        sections.append(changes_section)
        if fund["status"] == diff_module.FUND_INSUFFICIENT:
            sections.append(_insufficient_section())
        else:
            sections.append(_details_section(fund, source_label))
        sections.append(_managers_section(
            by_code_managers.get(code), manager_source_label))
        sections.append(_scale_section(by_code_scale.get(code), scale_source_label))
        if fund.get("anomalies"):
            pass  # 行内异常已并入明细行的最后一列，不另设段
        sections.append(_conflicts_section(diff_payload["conflicts"], code))

        prev_note = None
        if prev_summary is not None:
            prev_note = _prev_report_note(code, prev_summary, counts)

        funds.append({
            "fund_code": code,
            "name": fund.get("fund_name"),
            "disclosure": state,
            "sections": sections,
            "prev_report_note": prev_note,
        })

    funds.sort(key=lambda fund: fund["fund_code"])
    disclosure_counts = _disclosure_counts(states)
    generated_fields = [
        "meta.diff_mode", "meta.threshold", "meta.report_period",
        "meta.period_start", "meta.period_end", "meta.as_of", "meta.fetched_at",
        "funds[].disclosure", "funds[].sections", "totals",
        "compliance.hits",
    ]
    model = {
        "schema": SCHEMA,
        "meta": {
            "diff_mode": config["diff"]["mode"],
            "threshold": config["diff"]["threshold"],
            "report_period": period,
            "period_start": info["period_start"],
            "period_end": info["period_end"],
            "as_of": as_of,
            "fetched_at": window.today_iso(),
            "data_notes": [
                "持仓数据来自两份季度报告快照的 Q/Q 对比；缺失值显示为 null，不参与增减判断。",
                "diff 口径由配置冻结（diff.mode），--mode 可覆盖但必须显式选择。",
            ],
            "generated_fields": generated_fields,
        },
        "funds": funds,
        "totals": {
            "funds": len(funds),
            "disclosed": disclosure_counts["已披露"],
            "pending": disclosure_counts["待披露"],
            "no_data": disclosure_counts["无数据"],
            "changes": changes,
        },
        "compliance": {"scanned": True, "hits": []},
        "footer": config["compliance"]["footer"],
    }
    return model


def _disclosure_section(state, info):
    rows = [["披露状态", state]]
    notes = ["披露截止：%s（自季度结束次日起算 %d 个工作日）" % (
        info["disclosure_deadline"] or "null", info["deadline_count"])]
    return {"title": SECTION_DISCLOSURE, "rows": rows, "notes": notes}


def _changes_section(fund, labels):
    if fund["status"] == diff_module.FUND_INSUFFICIENT:
        return {
            "title": SECTION_CHANGES,
            "rows": [["数据不足", "任一季抓取失败，不与空仓混淆"]],
            "notes": [],
        }, {}
    summary = fund["summary"]
    counts = {label: summary[label] for label in
              list(labels.values())}
    rows = [[label, str(counts[label])] for label in sorted(counts)]
    return {"title": SECTION_CHANGES, "rows": rows, "notes": []}, counts


def _insufficient_section():
    return {
        "title": SECTION_DETAILS,
        "rows": [["insufficient_data", "任一季快照失败；不与空仓混淆"]],
        "notes": [],
    }


def _details_section(fund, source_label):
    rows = []
    for entry in fund["entries"]:
        rows.append([
            entry["stock_code"],
            entry.get("stock_name"),
            entry["status"],
            _display_ratio(entry["prev_ratio"]),
            _display_ratio(entry["cur_ratio"]),
            entry["delta"] if entry["delta"] is not None else "null",
            ("异常:" + ",".join(entry["anomalies"])) if entry["anomalies"] else "",
        ])
    return {
        "title": SECTION_DETAILS,
        "rows": rows,
        "notes": [source_label] if rows else [],
    }


def _display(value):
    return "null" if value is None else str(value)


def _display_ratio(value):
    return "null" if value is None else str(value)


def _managers_section(fund_payload, source_label):
    rows = []
    for record in (fund_payload or {}).get("managers") or []:
        rows.append([
            record.get("name") or "null",
            record["change_class"],
            record.get("change_date") or "null",
            record.get("start") or "null",
        ])
    notes = [source_label] if rows else []
    summary = (fund_payload or {}).get("summary")
    if summary and summary.get("unparsed"):
        notes.append("存在未解析记录：页面快照已留证（见 managers 产物）。")
    if not rows and summary and summary.get("none"):
        notes.append("本报告期内无经理变更。")
    return {"title": SECTION_MANAGERS, "rows": rows, "notes": notes}


def _scale_section(fund_payload, source_label):
    scale = (fund_payload or {}).get("scale")
    if not scale:
        return {"title": SECTION_SCALE, "rows": [], "notes": []}
    units = scale["units_from_header"]
    rows = [
        ["申购", _display(scale["subscribe"]),
         units.get("subscribe") or "null"],
        ["赎回", _display(scale["redeem"]), ""],
        ["期末份额", _display(scale["shares"]), ""],
        ["期末净资产", _display(scale["net_assets"]),
         units.get("net_assets") or "null"],
        ["份额变动率", _display(scale["share_change_rate"]), ""],
        ["baseline", scale["baseline"], ""],
    ]
    notes = [source_label]
    if scale["baseline"] == scale_module.BASELINE_NO_PREV:
        notes.append("无上季基准：缺失记 null，不补 0。")
    return {"title": SECTION_SCALE, "rows": rows, "notes": notes}


def _conflicts_section(conflicts, fund_code):
    rows = []
    for item in conflicts:
        if item["fund_code"] != fund_code:
            continue
        rows.append([
            item["stock_code"],
            "provider=%s" % item["provider_status"],
            "provider_change_pct=%s" % (item["provider_change_pct"] or "null"),
            "computed=%s" % item["computed_status"],
            "computed_delta=%s" % item["computed_delta"],
        ])
    notes = ["双口径结论不一致：不合并、不裁决，留待人工核对。"] if rows else []
    return {"title": SECTION_CONFLICTS, "rows": rows, "notes": notes}


def _load_prev_report(prev_report_dir, period):
    if prev_report_dir is None:
        return None
    path = _prev_report_json(prev_report_dir)
    if not path.is_file():
        raise ReportError(
            "上期报告不存在：%s（应含 report_data.json）" % path)
    try:
        payload = serialize.read_json(path)
    except (OSError, ValueError) as exc:
        raise ReportError("上期报告无法读取：%s（%s）" % (path, exc))
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        raise ReportError(
            "上期报告 schema 不符：%r（期望 %s）"
            % (payload.get("schema") if isinstance(payload, dict) else type(payload).__name__,
               SCHEMA))
    prev_period = payload["meta"]["report_period"]
    if prev_period == period:
        raise ReportError(
            "上期报告与本期报告期相同：%s（--prev-report 应指向上一个报告期的产物目录）"
            % period)
    expected_prev = window.previous_period(period)
    if prev_period != expected_prev:
        raise ReportError(
            "上期报告期 %s 与本期的上一报告期 %s 不一致" % (prev_period, expected_prev))
    return payload


def _prev_report_json(prev_report_dir):
    from pathlib import Path
    return Path(prev_report_dir) / "report_data.json"


def _prev_report_note(code, prev_payload, cur_counts):
    prev_by_code = {fund["fund_code"]: fund for fund in prev_payload["funds"]}
    if code not in prev_by_code:
        return "上期报告中未出现，本期新增。"
    prev_counts = {}
    for section in prev_by_code[code]["sections"]:
        if section["title"] == SECTION_CHANGES:
            for row in section["rows"]:
                prev_counts[row[0]] = int(row[1])
    diffs = []
    for label in sorted(set(prev_counts) | set(cur_counts)):
        before = prev_counts.get(label, 0)
        after = cur_counts.get(label, 0)
        if before != after:
            diffs.append("%s %d→%d" % (label, before, after))
    if diffs:
        return "较上期：%s。" % "，".join(diffs)
    return "较上期：无变动。"


def run_compliance_scan(model_text_files, terms):
    """对 {文件名: 文本} 做合规扫描，返回 {文件名: [hits]}。"""
    from . import compliance
    results = {}
    for name in sorted(model_text_files):
        hits = compliance.scan_text(model_text_files[name], terms)
        if hits:
            results[name] = hits
    return results


def check_only(data_dir, config, store_file, period, as_of):
    """--check-compliance：不生成产物。返回 hits 计数（0 = 通过）。

    复用上次 run 的产物不现实（可能不存在），所以这里对**当前输入**在内存里
    组装并渲染，扫描后丢弃，不写任何文件。
    """
    entries = store.Watchlist(store_file).list_all()
    codes = [entry["code"] for entry in entries]
    model = assemble(data_dir, config, codes, period, as_of)
    products = report_module.build_report_products(model)
    terms = config["compliance"]["forbidden_terms"]
    results = run_compliance_scan(products, terms)
    return results
