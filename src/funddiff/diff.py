"""Q/Q 持仓 diff（M3）：五态状态机 + provider/computed 双口径 + 冲突清单。

既定口径（动了会打挂测试，见 plan/HANDOFF-M1/M2/M3 §三）：
- K3：ratio/change_pct 是字符串十进制，一律 Decimal 运算，禁二进制浮点；缺失 null ≠ 0。
- K2：确定性——同输入双跑字节一致（排序键来自冻结配置 ordering.ledger；
  generated_at 取当天日期，同日双跑稳定）。
- K10：状态标签、阈值、排序键全部来自冻结配置 diff.* / ordering.*，代码零硬编码。

五态判定（computed 口径，与 data/fixtures/truth/diff_truth.json 逐条对齐）：
  新进   cur 有、prev 无该 stock_code
  退出   prev 有、cur 无该 stock_code
  加仓/减仓/不变  两侧都有：|cur-prev| < threshold → 不变；>0 加仓；<0 减仓
  待确认 两侧都有但任一侧 ratio 为 null（insufficient_data，与空仓/失败严格区分）

provider 口径：直接吃上游本期 PCTNVCHGTYPE（增持→加仓、减持→减仓、新进/退出/不变 原样），
delta 用上游 change_pct；computed 口径由两季 ratio 自算。
两口径结论不一致的条目进冲突清单（不静默合并、不猜谁对）。

失败季处理：任一季 status=failed → 该基金整体标 insufficient_data、entries 置空，
不得与"空仓"（status=empty，可正常算退出/新进）混淆。
"""

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

from . import serialize, window

SCHEMA = "funddiff/diff@1"

STATUS_NEW = "新进"
STATUS_EXIT = "退出"
STATUS_INCREASE = "加仓"
STATUS_DECREASE = "减仓"
STATUS_UNCHANGED = "不变"
STATUS_PENDING = "待确认"

BASIS_PROVIDER = "provider"
BASIS_COMPUTED = "computed"
BASIS_INSUFFICIENT = "insufficient_data"

FUND_INSUFFICIENT = "insufficient_data"

# 上游变动标识 → 五态标签（provider 口径与 computed 对齐用）。
PROVIDER_LABELS = {"增持": STATUS_INCREASE, "减持": STATUS_DECREASE}


class DiffError(Exception):
    """diff 阶段的门禁类失败（清单空/基金不在清单/快照缺失），退出码 1。"""


def parse_ratio(value, where):
    """K3：字符串十进制 → Decimal；缺失返回 None（null ≠ 0）；非法即抛内部一致性。"""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("内部一致性：非十进制数值 %r（%s）" % (value, where))


def format_delta(value):
    """差额统一两位小数字符串（与 fixtures 真值、显示精度一致）。"""
    return str(value.quantize(Decimal("0.01")))


def detect_anomaly(row):
    """逐行异常标记（与 fixtures 覆盖矩阵同名）：ratio_null / invalid_stock_code / change_type_missing。"""
    anomalies = []
    if row.get("ratio") is None:
        anomalies.append("ratio_null")
    if not row.get("stock_code") or not str(row["stock_code"]).isdigit():
        anomalies.append("invalid_stock_code")
    if row.get("change_type") is None:
        anomalies.append("change_type_missing")
    return anomalies


def provider_status(row):
    """上游变动标识 → 五态标签；识别不了返回 None（交给 computed 口径）。"""
    change_type = row.get("change_type")
    if change_type is None:
        return None
    if change_type in PROVIDER_LABELS:
        return PROVIDER_LABELS[change_type]
    if change_type in (STATUS_NEW, STATUS_EXIT, STATUS_UNCHANGED):
        return change_type
    return None


def load_holdings(data_dir, period, fund_code):
    """读单只基金单季快照（fetch 产物同形，funddiff/holdings@1）；缺失返回 None。"""
    path = Path(data_dir) / "fixtures" / ("q" + period.lower()) / "holdings" / (
        fund_code + ".json")
    if not path.is_file():
        return None
    return json.loads(serialize.read_text(path))


def _ratio_desc_key(entry):
    """排序键：cur_ratio 降序（null 永远最后），NULL 排在前表示"更大"。"""
    ratio = entry.get("cur_ratio")
    # None（缺失/null）排最后；其余按 cur_ratio 降序
    return (1, Decimal(0)) if ratio is None else (0, -Decimal(str(ratio)))


def sort_entries(entries, config):
    """确定性排序（K2）：键序来自冻结配置 ordering.ledger（fund_code/cur_ratio_desc/stock_code）。"""
    keys = config["ordering"]["ledger"]
    if keys != ["fund_code", "cur_ratio_desc", "stock_code"]:
        raise ValueError("内部一致性：未知排序键序 %r" % (keys,))
    return sorted(entries, key=lambda entry: (_ratio_desc_key(entry), entry["stock_code"]))


def diff_fund(prev_payload, cur_payload, config, fund_name=None, mode=None):
    """对单只基金做 Q/Q diff。

    返回 (fund_result, conflicts)：
    fund_result 含 status / entries / summary；conflicts 是 provider vs computed
    结论不一致的冲突条目列表（空列表 = 无冲突）。
    """
    threshold = parse_ratio(config["diff"]["threshold"], "diff.threshold")
    labels = config["diff"]["status_labels"]
    expected_labels = [STATUS_NEW, STATUS_EXIT, STATUS_INCREASE,
                       STATUS_DECREASE, STATUS_UNCHANGED]
    if sorted(labels) != sorted(expected_labels):
        raise ValueError("内部一致性：diff.status_labels 与既定五态不符 %r" % (labels,))
    pending_label = config["diff"]["pending_label"]
    if pending_label != STATUS_PENDING:
        raise ValueError("内部一致性：diff.pending_label 与既定口径不符 %r" % pending_label)

    prev_status = (prev_payload or {}).get("status")
    cur_status = (cur_payload or {}).get("status")

    # 失败季：任一季 failed → 整体 insufficient_data，与空仓（empty）严格区分。
    if prev_status == "failed" or cur_status == "failed":
        return {
            "status": FUND_INSUFFICIENT,
            "entries": [],
            "summary": _empty_summary(labels, pending_label),
        }, []

    prev_rows = {row["stock_code"]: row for row in (prev_payload or {}).get("rows") or []}
    cur_rows = {row["stock_code"]: row for row in (cur_payload or {}).get("rows") or []}

    entries = []
    conflicts = []
    for code in sorted(set(prev_rows) | set(cur_rows)):
        prev_row = prev_rows.get(code)
        cur_row = cur_rows.get(code)
        prev_ratio = prev_row.get("ratio") if prev_row else None
        cur_ratio = cur_row.get("ratio") if cur_row else None

        if prev_row is None and cur_row is not None:
            status, delta, basis = STATUS_NEW, None, BASIS_COMPUTED
            anomalies = detect_anomaly(cur_row)
        elif cur_row is None and prev_row is not None:
            status, delta, basis = STATUS_EXIT, None, BASIS_COMPUTED
            anomalies = detect_anomaly(prev_row)
        elif prev_ratio is None or cur_ratio is None:
            # K3：缺失 null ≠ 0。任一侧缺失 → 待确认（insufficient_data），不参与增减判断。
            status, delta, basis = pending_label, None, BASIS_INSUFFICIENT
            anomalies = detect_anomaly(prev_row or {}) + detect_anomaly(cur_row or {})
        else:
            difference = Decimal(str(cur_ratio)) - Decimal(str(prev_ratio))
            if abs(difference) < threshold:
                status = STATUS_UNCHANGED
            elif difference > 0:
                status = STATUS_INCREASE
            else:
                status = STATUS_DECREASE
            delta, basis = format_delta(difference), BASIS_COMPUTED
            anomalies = detect_anomaly(cur_row)
            if mode == BASIS_PROVIDER:
                provider_label = provider_status(cur_row)
                if provider_label is not None:
                    # provider 口径：直接采信上游变动标识，delta 用上游 change_pct。
                    status = provider_label
                    basis = BASIS_PROVIDER
                    delta = cur_row.get("change_pct")

        entry = {
            "stock_code": code,
            "stock_name": (cur_row or prev_row or {}).get("stock_name"),
            "industry": (cur_row or prev_row or {}).get("industry"),
            "prev_ratio": prev_ratio,
            "cur_ratio": cur_ratio,
            "delta": delta,
            "status": status,
            "basis": basis,
            "anomalies": anomalies,
            "source_quarters": {
                "prev": (prev_payload or {}).get("report_period"),
                "cur": (cur_payload or {}).get("report_period"),
            },
        }
        entries.append(entry)

        # 双口径冲突检测：provider（上游变动标识）与 computed（两季 ratio 自算）
        # 结论不一致 → 进冲突清单，不静默合并、不猜谁对。
        if cur_row is not None and prev_row is not None \
                and prev_ratio is not None and cur_ratio is not None:
            provider_label = provider_status(cur_row)
            if provider_label is not None and provider_label != status:
                conflicts.append({
                    "fund_code": (cur_payload or {}).get("fund_code"),
                    "stock_code": code,
                    "provider_status": provider_label,
                    "provider_change_pct": cur_row.get("change_pct"),
                    "computed_status": STATUS_UNCHANGED
                    if abs(Decimal(str(cur_ratio)) - Decimal(str(prev_ratio))) < threshold
                    else (STATUS_INCREASE
                          if Decimal(str(cur_ratio)) > Decimal(str(prev_ratio))
                          else STATUS_DECREASE),
                    "computed_delta": format_delta(
                        Decimal(str(cur_ratio)) - Decimal(str(prev_ratio))),
                    "prev_ratio": prev_ratio,
                    "cur_ratio": cur_ratio,
                })

    return {
        "status": "ok",
        "entries": sort_entries(entries, config),
        "summary": _summarize(entries, labels, pending_label),
    }, conflicts


def _summarize(entries, labels, pending_label):
    summary = {label: 0 for label in labels}
    summary[pending_label] = 0
    for entry in entries:
        summary[entry["status"]] = summary[entry["status"]] + 1
    return summary


def _empty_summary(labels, pending_label):
    summary = {label: 0 for label in labels}
    summary[pending_label] = 0
    return summary


def build(data_dir, config, codes, period, mode, prev_period=None):
    """对一组基金代码做 diff，返回完整 funddiff/diff@1 产物（含冲突清单）。

    抛 DiffError（清单/快照门禁）与 ValueError（配置一致性）。
    """
    if period is None:
        raise DiffError("缺少报告期：先 watch/window 确定报告期，或显式传 --period YYYYQn")
    window.parse_period(period)
    if prev_period is None:
        prev_period = window.previous_period(period)
    window.parse_period(prev_period)

    if not codes:
        raise DiffError("清单为空。用 `funddiff watch add <code>` 添加。")

    funds = []
    conflicts = []
    for code in codes:
        cur_payload = load_holdings(data_dir, period, code)
        prev_payload = load_holdings(data_dir, prev_period, code)
        if cur_payload is None and prev_payload is None:
            raise DiffError(
                "缺少两季持仓快照：%s（先 fetch %s/%s）" % (code, prev_period, period))
        if cur_payload is None or prev_payload is None:
            missing = period if cur_payload is None else prev_period
            raise DiffError("缺少 %s 季持仓快照：%s（先 fetch %s）" % (missing, code, missing))

        fund_result, fund_conflicts = diff_fund(
            prev_payload, cur_payload, config, fund_name=cur_payload.get("fund_name"),
            mode=mode)
        funds.append({
            "fund_code": code,
            "fund_name": cur_payload.get("fund_name"),
            "status": fund_result["status"],
            "entries": fund_result["entries"],
            "summary": fund_result["summary"],
            "inputs": {
                "prev": "q%s/holdings/%s.json" % (prev_period.lower(), code),
                "cur": "q%s/holdings/%s.json" % (period.lower(), code),
            },
        })
        conflicts.extend(fund_conflicts)

    funds.sort(key=lambda fund: fund["fund_code"])
    totals = {}
    for label in config["diff"]["status_labels"] + [config["diff"]["pending_label"]]:
        totals[label] = sum(fund["summary"][label] for fund in funds)

    return {
        "schema": SCHEMA,
        "mode": mode,
        "threshold": config["diff"]["threshold"],
        "report_period": period,
        "prev_period": prev_period,
        "generated_at": window.today_iso(),
        "conflicts": conflicts,
        "funds": funds,
        "totals": totals,
    }
