"""生成合成两季快照、真值与覆盖矩阵（M1）。

纪律：
- 自研 splitmix64；禁止 stdlib random / set 迭代序 / 系统时钟；
- 固定 seed，产物无时间戳，两次运行逐字节一致；
- 真值只记录"输入指针 + 期望状态 + 期望计数"，禁止 observed_* 字段；
- 所有文件写 "sample": "synthetic"；
- --check 做两层校验：MANIFEST 与冻结文件一致 + 临时重生成逐字节一致。

用法：
  py -3.12 -X utf8 tools/gen_fixtures.py
  py -3.12 -X utf8 tools/gen_fixtures.py --check
  py -3.12 -X utf8 tools/gen_fixtures.py --out /tmp/fixtures
"""

import argparse
import json
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from funddiff import frozen, serialize  # noqa: E402

SCHEMA = "funddiff/fixtures-manifest@1"
GENERATOR = "tools/gen_fixtures.py"
GENERATOR_VERSION = "1"
SEED = 20261018
RNG_NAME = "splitmix64"

Q2 = "2026Q2"
Q3 = "2026Q3"
PERIOD_END = {Q2: "2026-06-30", Q3: "2026-09-30"}
PERIOD_START = {Q2: "2026-04-01", Q3: "2026-07-01"}
PREVIOUS_START = {Q2: "2026-01-01", Q3: "2026-04-01"}
PREVIOUS_END = {Q2: "2026-03-31", Q3: "2026-06-30"}

INDUSTRIES = ("电子", "医药生物", "机械设备", "食品饮料", "计算机", "电力设备")

MASK = (1 << 64) - 1


class SplitMix64(object):
    def __init__(self, seed):
        self.state = seed & MASK

    def next_u64(self):
        self.state = (self.state + 0x9E3779B97F4A7C15) & MASK
        z = self.state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK
        return z ^ (z >> 31)

    def below(self, bound):
        if bound <= 0:
            raise ValueError("bound must be positive")
        return self.next_u64() % bound


def _bp_text(value):
    sign = "-" if value < 0 else ""
    value = abs(value)
    return "%s%d.%02d" % (sign, value // 100, value % 100)


def _next_bp(rng, low, high):
    return low + rng.below(high - low + 1)


# 每个基金的持仓意图。状态由"生成时的注入意图"直接记录，不调用 diff 引擎。
FUNDS = (
    {
        "code": "990001",
        "name": "样例稳健股票",
        "type": "股票型",
        "manager": None,
        "status": {Q2: "ok", Q3: "ok"},
        "rows": [
            {"stock_code": "600001", "status": "加仓", "change_bp": 50},
            {"stock_code": "600002", "status": "减仓", "change_bp": -50},
            {"stock_code": "600003", "status": "不变"},
            {"stock_code": "600004", "status": "退出"},
            {"stock_code": "600005", "status": "新进"},
        ],
    },
    {
        "code": "990002",
        "name": "样例平衡混合",
        "type": "混合型",
        "manager": {"kind": "change", "date": "2026-08-15",
                    "name": "样例经理甲", "start": "2020-03-01"},
        "status": {Q2: "ok", Q3: "ok"},
        "rows": [
            {"stock_code": "600010", "status": "加仓", "change_bp": 20},
            {"stock_code": "600011", "status": "不变"},
            {"stock_code": "600012", "status": "新进"},
            {"stock_code": "600013", "status": "退出"},
        ],
    },
    {
        "code": "990003",
        "name": "样例 ETF 联接",
        "type": "ETF联接",
        "manager": None,
        "status": {Q2: "empty", Q3: "empty"},
        "rows": [],
    },
    {
        "code": "990004",
        "name": "样例海外 QDII",
        "type": "QDII",
        "manager": {"kind": "change", "date": "2026-05-20",
                    "name": "样例经理乙", "start": "2018-07-01"},
        "status": {Q2: "ok", Q3: "ok"},
        "rows": [
            {"stock_code": "600030", "status": "加仓", "change_bp": 30},
            {"stock_code": "600031", "status": "不变"},
        ],
    },
    {
        "code": "990005",
        "name": "样例异常股票",
        "type": "股票型",
        "manager": {"kind": "unparsed"},
        "status": {Q2: "ok", Q3: "ok"},
        "rows": [
            {"stock_code": "600020", "status": "加仓", "change_bp": 10},
            {"stock_code": "600021", "status": "待确认", "prev_ratio_null": True,
             "anomaly": "ratio_null"},
            {"stock_code": "ABC123", "status": "新进",
             "anomaly": "invalid_stock_code"},
            {"stock_code": "600022", "status": "不变",
             "anomaly": "change_type_missing"},
        ],
    },
    {
        "code": "990006",
        "name": "样例解析失败",
        "type": "混合型",
        "manager": None,
        "status": {Q2: "ok", Q3: "failed:parse_error"},
        "rows": [
            {"stock_code": "600040", "status": "不变"},
            {"stock_code": "600041", "status": "新进"},
        ],
    },
    {
        "code": "990007",
        "name": "样例网络失败",
        "type": "QDII",
        "manager": None,
        "status": {Q2: "ok", Q3: "failed:timeout"},
        "rows": [
            {"stock_code": "600050", "status": "不变"},
            {"stock_code": "600051", "status": "加仓", "change_bp": 40},
        ],
    },
    {
        "code": "990008",
        "name": "样例待披露",
        "type": "股票型",
        "manager": None,
        "status": {Q2: "ok", Q3: "ok"},
        "rows": [
            {"stock_code": "600060", "status": "加仓", "change_bp": 25},
            {"stock_code": "600061", "status": "不变"},
        ],
    },
)

SCALE_Q3 = {
    "990001": {"baseline": "available", "subscribe": "1.20", "redeem": "0.80",
               "shares": "30.00", "net_assets": "45.00", "share_change_rate": "1.35%"},
    "990002": {"baseline": "available", "subscribe": "1.49", "redeem": "3.36",
               "shares": "24.06", "net_assets": "39.38", "share_change_rate": "-7.24%"},
    "990003": {"baseline": "no_prev_baseline", "subscribe": None, "redeem": None,
               "shares": "5.00", "net_assets": "6.20", "share_change_rate": None},
    "990004": {"baseline": "available", "subscribe": "0.00", "redeem": "0.00",
               "shares": "10.00", "net_assets": "12.00", "share_change_rate": "0.00%"},
    "990005": {"baseline": "available", "subscribe": "0.50", "redeem": "0.40",
               "shares": "8.00", "net_assets": "11.00", "share_change_rate": "1.27%"},
    "990006": {"baseline": "available", "subscribe": "0.20", "redeem": "0.10",
               "shares": "6.00", "net_assets": "9.00", "share_change_rate": "1.69%"},
    "990007": {"baseline": "no_prev_baseline", "subscribe": None, "redeem": None,
               "shares": "4.00", "net_assets": "5.50", "share_change_rate": None},
    "990008": {"baseline": "available", "subscribe": "0.30", "redeem": "0.20",
               "shares": "7.00", "net_assets": "10.50", "share_change_rate": "1.44%"},
}

SEND_DATES_Q2 = {
    "990001": "2026-07-15", "990002": "2026-07-16", "990003": "2026-07-17",
    "990004": "2026-07-20", "990005": "2026-07-18", "990006": "2026-07-20",
    "990007": "2026-07-21", "990008": "2026-07-15",
}

SEND_DATES_Q3 = {
    "990001": "2026-10-20", "990002": "2026-10-20", "990003": "2026-10-21",
    "990004": "2026-10-22", "990005": "2026-10-21", "990006": "2026-10-23",
    "990007": "2026-10-23",
}


def _fund(code):
    for fund in FUNDS:
        if fund["code"] == code:
            return fund
    raise KeyError(code)


def _identity_map(fund, rng):
    codes = sorted({item["stock_code"] for item in fund["rows"]})
    identities = {}
    for code in codes:
        if fund["type"] == "QDII":
            industry = None
        else:
            industry = INDUSTRIES[rng.below(len(INDUSTRIES))]
        identities[code] = {"stock_name": "样例股票" + code, "industry": industry}
    return identities


def _make_row(identity, ratio, change_type, change_pct):
    return {
        "stock_code": None,  # 由调用方补齐
        "stock_name": identity["stock_name"],
        "ratio": ratio,
        "change_type": change_type,
        "change_pct": change_pct,
        "industry": identity["industry"],
        "raw": {
            "ratio": None if ratio is None else ratio + "%",
            "change_type": change_type,
            "change_pct": change_pct,
        },
    }


def _sort_rows(rows):
    return sorted(
        rows,
        key=lambda row: (
            row["ratio"] is None,
            -Decimal(row["ratio"]) if row["ratio"] is not None else Decimal("0"),
            row["stock_code"],
        ),
    )


def _build_pair(fund, rng):
    """返回 (prev_rows, cur_rows, truth_entries)。"""
    identities = _identity_map(fund, rng)
    prev_rows = []
    cur_rows = []
    entries = []

    for intent in fund["rows"]:
        code = intent["stock_code"]
        status = intent["status"]
        identity = identities[code]
        anomaly = intent.get("anomaly")

        if status == "新进":
            cur_bp = _next_bp(rng, 150, 950)
            cur_ratio = _bp_text(cur_bp)
            row = _make_row(identity, cur_ratio, None, None)
            row["stock_code"] = code
            cur_rows.append(row)
            entry = {
                "stock_code": code,
                "prev_ratio": None,
                "cur_ratio": cur_ratio,
                "delta": None,
                "status": "新进",
                "basis": "computed",
            }
            if anomaly:
                entry["anomaly"] = anomaly
            entries.append(entry)
            continue

        prev_bp = _next_bp(rng, 150, 950)
        prev_ratio = None if intent.get("prev_ratio_null") else _bp_text(prev_bp)
        prev_row = _make_row(identity, prev_ratio, None, None)
        prev_row["stock_code"] = code
        prev_rows.append(prev_row)

        if status == "退出":
            entries.append({
                "stock_code": code,
                "prev_ratio": prev_ratio,
                "cur_ratio": None,
                "delta": None,
                "status": "退出",
                "basis": "computed",
            })
            continue

        if prev_ratio is None:
            cur_bp = _next_bp(rng, 150, 950)
            cur_ratio = _bp_text(cur_bp)
            delta_text = None
            entry = {
                "stock_code": code,
                "prev_ratio": None,
                "cur_ratio": cur_ratio,
                "delta": None,
                "status": "待确认",
                "basis": "insufficient_data",
            }
            change_type = None
            change_pct = None
        else:
            change_bp = intent.get("change_bp", 0)
            cur_bp = prev_bp + change_bp
            cur_ratio = _bp_text(cur_bp)
            delta_text = _bp_text(change_bp)
            if status == "加仓":
                change_type, change_pct = "增持", delta_text
            elif status == "减仓":
                change_type, change_pct = "减持", delta_text
            elif status == "不变":
                change_type, change_pct = "不变", "0.00"
            else:
                change_type, change_pct = None, None
            entry = {
                "stock_code": code,
                "prev_ratio": prev_ratio,
                "cur_ratio": cur_ratio,
                "delta": delta_text,
                "status": status,
                "basis": "computed",
            }
        if anomaly == "change_type_missing":
            change_type = None
        if anomaly:
            entry["anomaly"] = anomaly
        entries.append(entry)

        cur_row = _make_row(identity, cur_ratio, change_type, change_pct)
        cur_row["stock_code"] = code
        cur_rows.append(cur_row)

    return _sort_rows(prev_rows), _sort_rows(cur_rows), _sort_entries(entries)


def _sort_entries(entries):
    return sorted(
        entries,
        key=lambda entry: (
            entry["cur_ratio"] is None,
            -Decimal(entry["cur_ratio"]) if entry["cur_ratio"] is not None else Decimal("0"),
            entry["stock_code"],
        ),
    )


def _holdings_payload(fund, period, rows):
    status = fund["status"][period]
    payload = {
        "schema": "funddiff/holdings@1",
        "sample": "synthetic",
        "fund_code": fund["code"],
        "fund_name": fund["name"],
        "fund_type": fund["type"],
        "report_period": period,
        "period_end": PERIOD_END[period],
        "source": {
            "channel": "json",
            "endpoint": "FundMNInverstPosition",
            "fetched_at": None,
            "raw_sha256": None,
        },
        "rows": rows,
        "structural_note": None,
        "status": status.split(":", 1)[0],
    }
    if status == "empty":
        payload["structural_note"] = "ETF 联接基金，结构上无股票持仓"
        payload["source"] = {
            "channel": "json",
            "endpoint": "FundMNInverstPosition",
            "fetched_at": None,
            "raw_sha256": None,
            "fallback_reason": "no_stock_holdings",
        }
    elif status.startswith("failed:"):
        error_kind = status.split(":", 1)[1]
        payload["rows"] = []
        payload["error_kind"] = error_kind
        if error_kind == "parse_error":
            payload["source"]["channel"] = "page"
            payload["source"]["endpoint"] = "jjcc"
            payload["source"]["fallback_reason"] = "json_missing_fields"
        else:
            payload["source"]["error_kind"] = error_kind
    return payload


def _manager_class(spec, period):
    if spec is None:
        return "none", None
    if spec["kind"] == "unparsed":
        return "unparsed", None
    change_date = spec["date"]
    if PERIOD_START[period] <= change_date <= PERIOD_END[period]:
        return "in_period", change_date
    if PREVIOUS_START[period] <= change_date <= PREVIOUS_END[period]:
        return "prior_period", change_date
    return "none", None


def _managers_payload(fund, period):
    spec = fund["manager"]
    if spec is None:
        return []
    change_class, change_date = _manager_class(spec, period)
    if change_class == "none":
        return []
    if change_class == "unparsed":
        return [{
            "name": None,
            "start": None,
            "end": None,
            "change_date": None,
            "in_period": None,
            "change_class": "unparsed",
            "source": "jjjl",
            "raw_text": "合成页面片段：无法解析的基金经理变动表",
        }]
    return [{
        "name": spec["name"],
        "start": spec["start"],
        "end": None,
        "change_date": change_date,
        "in_period": change_class == "in_period",
        "change_class": change_class,
        "source": "jjjl",
        "raw_text": "合成页面：基金经理变动一览",
    }]


def _scale_payload(fund, period, rng):
    if period == Q3:
        values = SCALE_Q3[fund["code"]]
    else:
        if fund["code"] in ("990003",):
            values = {
                "baseline": "no_prev_baseline",
                "subscribe": None,
                "redeem": None,
                "shares": _bp_text(_next_bp(rng, 300, 900)),
                "net_assets": _bp_text(_next_bp(rng, 400, 1200)),
                "share_change_rate": None,
            }
        else:
            values = {
                "baseline": "available",
                "subscribe": _bp_text(_next_bp(rng, 0, 300)),
                "redeem": _bp_text(_next_bp(rng, 0, 300)),
                "shares": _bp_text(_next_bp(rng, 1000, 5000)),
                "net_assets": _bp_text(_next_bp(rng, 1500, 7000)),
                "share_change_rate": "%s%%" % _bp_text(_next_bp(rng, -500, 500)),
            }
    return {
        "report_period": period,
        "subscribe": values["subscribe"],
        "redeem": values["redeem"],
        "shares": values["shares"],
        "net_assets": values["net_assets"],
        "share_change_rate": values["share_change_rate"],
        "baseline": values["baseline"],
        "units_from_header": {"subscribe": "亿份", "net_assets": "亿元"},
        "source": "gmbd",
        "raw_sha256": None,
    }


def _events_payload(fund, period, rng):
    return {
        "schema": "funddiff/events@1",
        "sample": "synthetic",
        "fund_code": fund["code"],
        "fund_name": fund["name"],
        "report_period": period,
        "managers": _managers_payload(fund, period),
        "scale": _scale_payload(fund, period, rng),
    }


def _disclosure_payload(period, send_dates):
    reports = []
    for fund in FUNDS:
        if fund["code"] not in send_dates:
            continue
        record = {
            "fundcode": fund["code"],
            "report_send_date": send_dates[fund["code"]],
            "title": "%s%s年第%s季度报告" % (
                fund["name"], period[:4], period[5]),
        }
        # 故意留一条只靠标题解析报告期，守 parse_report_period。
        if not (period == Q3 and fund["code"] == "990001"):
            record["report_period"] = period
        reports.append(record)
    return {
        "schema": "funddiff/disclosure@1",
        "sample": "synthetic",
        "available": True,
        "reason": None,
        "reports": reports,
    }


def _truth_entry_summary(entries):
    summary = {"新进": 0, "退出": 0, "加仓": 0, "减仓": 0, "不变": 0, "待确认": 0}
    for entry in entries:
        summary[entry["status"]] += 1
    return summary


def build_payloads():
    """返回 {相对路径: JSON 数据}。调用顺序固定，保证 RNG 流稳定。"""
    rng = SplitMix64(SEED)
    payloads = {}
    pairs = {}

    for fund in FUNDS:
        pairs[fund["code"]] = _build_pair(fund, rng)

    for fund in FUNDS:
        code = fund["code"]
        prev_rows, cur_rows, entries = pairs[code]
        for period, rows in ((Q2, prev_rows), (Q3, cur_rows)):
            payloads["q%s/holdings/%s.json" % (period.lower(), code)] = _holdings_payload(
                fund, period, rows)

    for fund in FUNDS:
        for period in (Q2, Q3):
            payloads["q%s/events/%s.json" % (period.lower(), fund["code"])] = _events_payload(
                fund, period, rng)

    q2_disclosure = _disclosure_payload(Q2, SEND_DATES_Q2)
    q3_disclosure = _disclosure_payload(Q3, SEND_DATES_Q3)
    payloads["q%s/disclosure.json" % Q2.lower()] = q2_disclosure
    payloads["q%s/disclosure.json" % Q3.lower()] = q3_disclosure

    aggregate = {
        "schema": "funddiff/disclosure@1",
        "sample": "synthetic",
        "available": True,
        "reason": None,
        "note": "两季披露元数据聚合快照；由 tools/gen_fixtures.py 生成。",
        "reports": sorted(
            q2_disclosure["reports"] + q3_disclosure["reports"],
            key=lambda item: (item["report_send_date"], item["fundcode"]),
        ),
    }
    payloads["disclosure.json"] = aggregate
    payloads["disclosure_unavailable.json"] = {
        "schema": "funddiff/disclosure@1",
        "sample": "synthetic",
        "available": False,
        "reason": "synthetic_network_failure",
        "reports": [],
    }

    truth_funds = []
    for fund in FUNDS:
        code = fund["code"]
        status = fund["status"][Q3].split(":", 1)[0]
        entries = pairs[code][2] if status == "ok" else []
        truth_funds.append({
            "fund_code": code,
            "fund_name": fund["name"],
            "expected_holdings_status": status,
            "inputs": {
                "prev": "q%s/holdings/%s.json" % (Q2.lower(), code),
                "cur": "q%s/holdings/%s.json" % (Q3.lower(), code),
            },
            "entries": entries,
            "summary": _truth_entry_summary(entries),
        })
    payloads["truth/diff_truth.json"] = {
        "schema": "funddiff/diff-truth@1",
        "sample": "synthetic",
        "prev_period": Q2,
        "report_period": Q3,
        "threshold": "0.10",
        "funds": truth_funds,
    }

    events_funds = []
    for fund in FUNDS:
        change_class, change_date = _manager_class(fund["manager"], Q3)
        managers = []
        if change_class != "none":
            item = {"change_class": change_class}
            if change_date is not None:
                item["change_date"] = change_date
            managers.append(item)
        scale = SCALE_Q3[fund["code"]]
        events_funds.append({
            "fund_code": fund["code"],
            "inputs": {
                "events": "q%s/events/%s.json" % (Q3.lower(), fund["code"]),
            },
            "managers": managers,
            "scale": {
                "baseline": scale["baseline"],
                "subscribe": scale["subscribe"],
                "redeem": scale["redeem"],
                "shares": scale["shares"],
                "net_assets": scale["net_assets"],
                "share_change_rate": scale["share_change_rate"],
            },
        })
    payloads["truth/events_truth.json"] = {
        "schema": "funddiff/events-truth@1",
        "sample": "synthetic",
        "report_period": Q3,
        "funds": events_funds,
    }

    payloads["truth/coverage.json"] = _coverage(payloads["truth/diff_truth.json"],
                                                payloads["truth/events_truth.json"],
                                                q3_disclosure)
    return payloads


def _dimension(items, note="抽样覆盖、非穷举"):
    return {
        "note": note,
        "total": len(items),
        "sampled": len(items),
        "items": {
            key: {"total": count, "sampled": count}
            for key, count in sorted(items.items())
        },
    }


def _count(values):
    counts = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


def _coverage(diff_truth, events_truth, q3_disclosure):
    holding_states = []
    anomalies = []
    for fund in diff_truth["funds"]:
        for entry in fund["entries"]:
            holding_states.append(entry["status"])
            if "anomaly" in entry:
                anomalies.append(entry["anomaly"])
        if fund["expected_holdings_status"] == "failed":
            error_kind = _fund(fund["fund_code"])["status"][Q3].split(":", 1)[1]
            anomalies.append("page_parse_failed" if error_kind == "parse_error"
                             else "network_failed")

    manager_states = []
    scale_states = []
    for fund in events_truth["funds"]:
        classes = [item["change_class"] for item in fund["managers"]]
        manager_states.append(classes[0] if classes else "none")
        baseline = fund["scale"]["baseline"]
        if baseline == "no_prev_baseline":
            scale_states.append("no_prev_baseline")
        elif (fund["scale"]["subscribe"] == "0.00"
              and fund["scale"]["redeem"] == "0.00"):
            scale_states.append("零申赎")
        else:
            scale_states.append("正常变动")

    fund_types = [fund["type"] for fund in FUNDS]
    disclosed = len(q3_disclosure["reports"])
    pending = len(FUNDS) - disclosed
    disclosure_items = {"已披露": disclosed, "待披露": pending, "无数据": 1}
    holding_counts = _count(holding_states)
    holding_counts.pop("待确认", None)  # 待确认不是第六态，只在 summary 计数
    for label in ("新进", "退出", "加仓", "减仓", "不变"):
        holding_counts.setdefault(label, 0)

    return {
        "schema": "funddiff/coverage@1",
        "sample": "synthetic",
        "note": "抽样覆盖、非穷举",
        "dimensions": {
            "holding_change": _dimension(holding_counts),
            "manager": _dimension(_count(manager_states)),
            "scale": _dimension(_count(scale_states)),
            "fund_type": _dimension(_count(fund_types)),
            "anomaly": _dimension(_count(anomalies)),
            "disclosure": _dimension(
                disclosure_items,
                note="抽样覆盖、非穷举；无数据由 disclosure_unavailable.json 单独覆盖",
            ),
        },
    }


def _manifest_extra():
    return {
        "sample": "synthetic",
        "generator": GENERATOR,
        "generator_version": GENERATOR_VERSION,
        "seed": SEED,
        "rng": RNG_NAME,
    }


def generate(out_dir):
    out_dir = Path(out_dir)
    payloads = build_payloads()
    for relative in sorted(payloads):
        serialize.write_json(out_dir / relative, payloads[relative])
    manifest = frozen.build_manifest(out_dir, SCHEMA, extra=_manifest_extra())
    serialize.write_json(out_dir / frozen.MANIFEST_NAME, manifest)
    return len(payloads) + 1


def check(fixture_dir):
    fixture_dir = Path(fixture_dir)
    manifest_path = fixture_dir / frozen.MANIFEST_NAME
    if not manifest_path.is_file():
        return ["MANIFEST 不存在：%s（先运行 tools/gen_fixtures.py）" % manifest_path]
    try:
        with manifest_path.open("r", encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, ValueError) as exc:
        return ["MANIFEST 无法读取：%s" % exc]

    problems = frozen.verify_manifest(fixture_dir, manifest, SCHEMA)
    for key, value in _manifest_extra().items():
        if manifest.get(key) != value:
            problems.append("MANIFEST.%s 不符：清单 %r / 期望 %r" % (
                key, manifest.get(key), value))

    with tempfile.TemporaryDirectory() as tmp:
        generate(tmp)
        problems.extend(frozen.compare_tree(fixture_dir, tmp, exclude=()))
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description="合成 fixtures 生成与校验")
    parser.add_argument("--data-dir", default=str(ROOT / "data"),
                        help="数据目录（默认仓库 data/）")
    parser.add_argument("--out", default=None, help="输出目录（默认 <data-dir>/fixtures）")
    parser.add_argument("--check", action="store_true", help="校验冻结产物与重生成字节一致")
    args = parser.parse_args(argv)

    data_dir = Path(args.data_dir)
    fixture_dir = Path(args.out) if args.out else data_dir / "fixtures"
    try:
        if args.check:
            problems = check(fixture_dir)
        else:
            count = generate(fixture_dir)
            print("gen_fixtures: 已写入 %d 个文件到 %s" % (count, fixture_dir))
            return 0
    except (OSError, ValueError) as exc:
        print("gen_fixtures: %s" % exc, file=sys.stderr)
        return 2

    if problems:
        for problem in problems:
            print("[FAIL] %s" % problem, file=sys.stderr)
        print("gen_fixtures: FAIL（%d 处不一致）" % len(problems), file=sys.stderr)
        return 1
    print("gen_fixtures: PASS（MANIFEST + 重生成逐字节一致）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
