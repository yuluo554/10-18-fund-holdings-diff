"""持仓字段归一（M2）。

纪律：
- ratio / change_pct：去 `%`、去全角/普通空白、千分位逗号，保留正负号；
  字符串十进制（与配置同口径），缺失是 null，绝不与 0 混同（K3）；
- 名称只做空白清洗（全角空格折成空格、去首尾），不改字；
- industry 缺失 → null；
- ETF 联接基金：页面上没有持仓，是结构性差异 → status=empty + structural_note，
  不与"抓取失败"混同；
- 解析不到的结构性信息不猜：宁可 null / failed，不编造。
"""

import re

SCHEMA = "funddiff/holdings@1"

STATUS_OK = "ok"
STATUS_EMPTY = "empty"
STATUS_FAILED = "failed"

VALID_CHANGE_TYPES = ("增持", "减持", "不变", "新进")

_WS_RE = re.compile(r"[\s\u3000]+")
_PERCENT_RE = re.compile(r"^[+-]?\d+(\.\d+)?$")
_CODE_RE = re.compile(r"^\d{6}$")

ETF_NOTE = "ETF 联接基金：持公募基金而非股票，持仓表结构性为空"


def clean_text(value):
    """通用清洗：空白折叠 + 去首尾。None 进 None 出。"""
    if value is None:
        return None
    text = _WS_RE.sub(" ", str(value)).strip()
    return text or None


def clean_name(value):
    """名称清洗：只做空白处理，不做任何语义改写。"""
    return clean_text(value)


def _clean_number_text(text):
    """去 %、去空白、去千分位逗号；全角百分号也一并去掉。"""
    if text is None:
        return None
    text = str(text)
    for mark in ("%", "％"):
        text = text.replace(mark, "")
    text = _WS_RE.sub("", text).replace(",", "")
    return text or None


def strip_percent(value):
    """净值占比：'8.54%' -> '8.54'；缺失/空 -> None；非法文本原样返回由调用方判定。"""
    text = _clean_number_text(value)
    if text is None:
        return None
    return text


def strip_change_pct(value):
    """变动百分点：'-0.50%' -> '-0.50'；'+0.50' 保留符号；'--' / 空 -> None。"""
    text = _clean_number_text(value)
    if text is None:
        return None
    if text in ("--", "-", "—"):
        return None
    if _PERCENT_RE.match(text):
        return text
    return text


def is_valid_code(value):
    return isinstance(value, str) and bool(_CODE_RE.match(value))


def normalize_row(stock_code, stock_name, ratio, change_type=None,
                  change_pct=None, industry=None, raw=None):
    """一行持仓的归一产物，形状与合成快照 rows 完全一致。"""
    return {
        "stock_code": stock_code,
        "stock_name": stock_name,
        "ratio": ratio,
        "change_type": change_type if change_type in VALID_CHANGE_TYPES else None,
        "change_pct": change_pct,
        "industry": industry,
        "raw": raw or {},
    }


def is_etf_feeder(fund_name, fund_type=None):
    """识别 ETF 联接基金（名称含"联接"，或类型标注 ETF 联接）。"""
    name = clean_text(fund_name) or ""
    if "联接" in name:
        return True
    type_text = clean_text(fund_type) or ""
    return "联接" in type_text


def empty_holdings(fund_code, report_period, fund_name=None, fund_type=None,
                   note=ETF_NOTE):
    """结构性为空的持仓 payload（ETF 联接等）。"""
    return {
        "schema": SCHEMA,
        "fund_code": fund_code,
        "fund_name": clean_name(fund_name),
        "fund_type": clean_name(fund_type),
        "report_period": report_period,
        "period_end": None,
        "rows": [],
        "status": STATUS_EMPTY,
        "error_kind": None,
        "structural_note": note,
        "sample": None,
        "source": {"channel": None, "endpoint": None,
                   "fetched_at": None, "raw_sha256": None},
    }


def failure_record(fund_code, report_period, error_kind, channel=None,
                   endpoint=None, fallback_reason=None, fund_name=None,
                   fund_type=None, period_end=None, raw=None, raw_sha256=None):
    """失败台账条目：与 holdings payload 同形，status=failed。"""
    source = {
        "channel": channel,
        "endpoint": endpoint,
        "fetched_at": None,
        "raw_sha256": raw_sha256,
    }
    if channel == "json" or (channel is None and fallback_reason is None):
        source["error_kind"] = error_kind
    if fallback_reason:
        source["fallback_reason"] = fallback_reason
    if raw is not None and raw_sha256 is None:
        import hashlib
        source["raw_sha256"] = hashlib.sha256(raw).hexdigest()
    return {
        "schema": SCHEMA,
        "fund_code": fund_code,
        "fund_name": clean_name(fund_name),
        "fund_type": clean_name(fund_type),
        "report_period": report_period,
        "period_end": period_end,
        "rows": [],
        "status": STATUS_FAILED,
        "error_kind": error_kind,
        "structural_note": None,
        "sample": None,
        "source": source,
    }
