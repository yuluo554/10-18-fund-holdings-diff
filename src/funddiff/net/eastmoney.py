"""东财持仓抓取（M2）：JSON 通道优先，jjcc 页面通道回落。

纪律：
- endpoint 一律来自配置 sources（K10 同源纪律），代码里不写第二份 URL；
- JSON 通道（FundMNInverstPosition）字段齐全即用；
- JSON 通道不可用 / 字段缺失 → 页面通道（jjcc，GBK + 内嵌 JS 正则）回落，
  回落必须留痕 `source.fallback_reason`；
- GBK 严格解码（strict），失败保存原始字节 + `error_kind=decode_error`，
  禁止 errors="ignore"（K 同源：坏数据宁可失败，不许悄悄变形）；
- 解析失败的响应保存原始字节并落 `error_kind=parse_error`；
- 本模块输出与合成快照同形：funddiff/holdings@1 schema。
"""

import hashlib
import json
import re

from . import http as http_module
from .http import FetchError

JSON_ENDPOINT_KEY = "eastmoney_position_json"
PAGE_ENDPOINT_KEY = "eastmoney_position_page"

JSON_CHANNEL = "json"
PAGE_CHANNEL = "page"

# JSON 通道输出的字段名（东财缩写）。
FIELD_GPDM = "GPDM"    # 股票代码
FIELD_GPJC = "GPJC"    # 股票简称
FIELD_JZBL = "JZBL"    # 净值占比（%）
FIELD_CHANGE_TYPE = "PCTNVCHGTYPE"  # 变动方向（1 增持 / 2 减持 / 3 不变 / 0 新进）
FIELD_CHANGE_PCT = "PCTNVCHG"       # 占净值比变动（百分点）
FIELD_INDEXNAME = "INDEXNAME"       # 所属行业

_CHANGE_TYPE_MAP = {
    "1": "增持",
    "2": "减持",
    "3": "不变",
    "0": "新进",
}

# JSON 通道输出必须齐备的字段；缺任何一个视为"JSON 通道不完整"→ 回落页面通道。
_REQUIRED_JSON_FIELDS = (FIELD_GPDM, FIELD_GPJC, FIELD_JZBL)

_PAGE_ROW_RE = re.compile(r"<tr>(.*?)</tr>", re.S)
_PAGE_CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_APIDATA_RE = re.compile(r'var\s+apidata\s*=\s*\{\s*content\s*:\s*"(.*?)"\s*[,}]', re.S)


class FetchFailure(Exception):
    """单只基金抓取/解析失败，携带台账字段（失败隔离的单位）。"""

    def __init__(self, error_kind, channel, endpoint, detail, raw=None,
                 fallback_reason=None):
        Exception.__init__(self, detail)
        self.error_kind = error_kind
        self.channel = channel
        self.endpoint = endpoint
        self.detail = detail
        self.raw = raw
        self.fallback_reason = fallback_reason


def _raw_sha256(raw):
    if raw is None:
        return None
    return hashlib.sha256(raw).hexdigest()


def _json_endpoint(config):
    return config["sources"][JSON_ENDPOINT_KEY]["endpoint"]


def _page_endpoint(config, fund_code):
    endpoint = config["sources"][PAGE_ENDPOINT_KEY]["endpoint"]
    return endpoint.replace("{code}", fund_code)


def _iso_period(report_period):
    """2026Q3 -> 2026-09-30 由调用方传 period_end；这里只做年季拆分。"""
    match = re.match(r"^(\d{4})Q([1-4])$", str(report_period or ""))
    if not match:
        raise ValueError("report_period 必须是 YYYYQn，实际为 %r" % (report_period,))
    return match.group(1), match.group(2)


def fetch_position_json(config, fund_code, report_period, fetcher=None,
                        fetched_at=None):
    """JSON 通道抓取。成功返回 (rows, raw_sha256)；不完整/失败抛 FetchFailure。"""
    fetcher = fetcher or http_module.Fetcher(config)
    year, quarter = _iso_period(report_period)
    endpoint = _json_endpoint(config)
    # F10 数据接口按页取季度：pageIndex 从 1 开始（配置只存 endpoint，参数在代码里）
    url = "%s?FCODE=%s&pageIndex=1&pageSize=200&year=%s&topline=10&month=%s&deviceid=Wap" % (
        endpoint, fund_code, year, {"1": "3", "2": "6", "3": "9", "4": "12"}[quarter])
    try:
        _status, body, _final = fetcher.get(url)
    except FetchError as exc:
        raise FetchFailure(exc.kind, JSON_CHANNEL, endpoint, str(exc), raw=exc.raw)
    try:
        payload = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise FetchFailure("parse_error", JSON_CHANNEL, endpoint,
                           "JSON 响应解析失败：%s" % exc, raw=body)
    if not isinstance(payload, dict):
        raise FetchFailure("parse_error", JSON_CHANNEL, endpoint,
                           "JSON 响应根不是对象", raw=body)
    rows = payload.get("Datas") or payload.get("datas") or []
    if not isinstance(rows, list) or not rows:
        raise FetchFailure("empty_result", JSON_CHANNEL, endpoint,
                           "JSON 通道无数据", raw=body)
    if any(not isinstance(row, dict) or any(field not in row for field in _REQUIRED_JSON_FIELDS)
           for row in rows):
        raise FetchFailure("json_missing_fields", JSON_CHANNEL, endpoint,
                           "JSON 通道字段不齐：%s" % ",".join(_REQUIRED_JSON_FIELDS),
                           raw=body)
    normalized = []
    for row in rows:
        normalized.append(_row_from_json(row, fund_code))
    return normalized, _raw_sha256(body), endpoint


def _row_from_json(row, fund_code):
    change_type = _CHANGE_TYPE_MAP.get(str(row.get(FIELD_CHANGE_TYPE, "")).strip())
    change_pct = row.get(FIELD_CHANGE_PCT)
    ratio = row.get(FIELD_JZBL)
    industry = row.get(FIELD_INDEXNAME)
    raw = {
        "ratio": ratio,
        "change_type": row.get(FIELD_CHANGE_TYPE),
        "change_pct": change_pct,
    }
    from .. import normalize
    return normalize.normalize_row(
        stock_code=str(row.get(FIELD_GPDM, "")).strip(),
        stock_name=normalize.clean_name(row.get(FIELD_GPJC)),
        ratio=normalize.strip_percent(ratio),
        change_type=change_type,
        change_pct=normalize.strip_change_pct(change_pct),
        industry=normalize.clean_name(industry),
        raw=raw,
    )


def fetch_position_page(config, fund_code, report_period, fetcher=None,
                        fetched_at=None):
    """页面通道（jjcc，GBK）。成功返回 (rows, raw_sha256)；失败抛 FetchFailure。"""
    fetcher = fetcher or http_module.Fetcher(config)
    year, quarter = _iso_period(report_period)
    endpoint = _page_endpoint(config, fund_code)
    url = "%s?type=jjcc&code=%s&topline=10&year=%s&month=%s" % (
        endpoint, fund_code, year, {"1": "3", "2": "6", "3": "9", "4": "12"}[quarter])
    try:
        _status, body, _final = fetcher.get(url)
    except FetchError as exc:
        raise FetchFailure(exc.kind, PAGE_CHANNEL, endpoint, str(exc), raw=exc.raw)
    # GBK 严格解码：失败保存原始字节，绝不 errors="ignore"。
    try:
        text = body.decode("gbk")
    except UnicodeDecodeError as exc:
        raise FetchFailure("decode_error", PAGE_CHANNEL, endpoint,
                           "GBK 严格解码失败：%s" % exc, raw=body)
    match = _APIDATA_RE.search(text)
    if not match:
        raise FetchFailure("parse_error", PAGE_CHANNEL, endpoint,
                           "页面未找到 var apidata 内嵌数据", raw=body)
    content = match.group(1)
    rows = _parse_apidata(content)
    if not rows:
        raise FetchFailure("empty_result", PAGE_CHANNEL, endpoint,
                           "apidata 内容无持仓行", raw=body)
    return rows, _raw_sha256(body), endpoint


def _parse_apidata(content):
    """解析内嵌 HTML 表格：每行 <tr>，单元格依次为序号/代码/名称/净值占比…。"""
    rows = []
    from .. import normalize
    for tr in _PAGE_ROW_RE.findall(content):
        cells = [_TAG_RE.sub("", cell).strip() for cell in _PAGE_CELL_RE.findall(tr)]
        # 过滤表头（第一格是序号）
        if len(cells) < 4 or not cells[1]:
            continue
        if not re.match(r"^\d{6}$", cells[1]):
            continue
        ratio = normalize.strip_percent(cells[3]) if len(cells) > 3 else None
        change_type = cells[4] if len(cells) > 4 else None
        change_pct = normalize.strip_change_pct(cells[5]) if len(cells) > 5 else None
        industry = cells[6] if len(cells) > 6 else None
        rows.append(normalize.normalize_row(
            stock_code=cells[1],
            stock_name=normalize.clean_name(cells[2]),
            ratio=ratio,
            change_type=change_type,
            change_pct=change_pct,
            industry=normalize.clean_name(industry) if industry else None,
            raw={
                "ratio": cells[3] if len(cells) > 3 else None,
                "change_type": change_type,
                "change_pct": cells[5] if len(cells) > 5 else None,
            },
        ))
    return rows


def fetch_holdings(config, fund_code, report_period, fetcher=None, fetched_at=None,
                   fund_name=None, fund_type=None, period_end=None):
    """双通道编排：JSON 优先，页面回落并留痕。

    返回 dict：funddiff/holdings@1 的 payload（status ok）；
    两条通道都失败时抛最后一个 FetchFailure（调用方落失败台账）。
    """
    if fetcher is None:
        fetcher = http_module.Fetcher(config)
    try:
        rows, sha, endpoint = fetch_position_json(
            config, fund_code, report_period, fetcher=fetcher, fetched_at=fetched_at)
    except FetchFailure as json_failure:
        # 空结果不算"通道坏了"，是数据本身为空：直接成功返回空 rows。
        if json_failure.error_kind == "empty_result":
            return _payload(fund_code, report_period, JSON_CHANNEL,
                            json_failure.endpoint, [],
                            fetched_at=fetched_at, fund_name=fund_name,
                            fund_type=fund_type, period_end=period_end)
        try:
            rows, sha, endpoint = fetch_position_page(
                config, fund_code, report_period, fetcher=fetcher,
                fetched_at=fetched_at)
        except FetchFailure as page_failure:
            raise FetchFailure(
                page_failure.error_kind, page_failure.channel,
                page_failure.endpoint, page_failure.detail,
                raw=page_failure.raw,
                fallback_reason=json_failure.error_kind)
        return _payload(fund_code, report_period, PAGE_CHANNEL, endpoint, rows,
                        raw_sha256=sha, fetched_at=fetched_at,
                        fund_name=fund_name, fund_type=fund_type,
                        period_end=period_end,
                        fallback_reason=json_failure.error_kind)
    return _payload(fund_code, report_period, JSON_CHANNEL, endpoint, rows,
                    raw_sha256=sha, fetched_at=fetched_at,
                    fund_name=fund_name, fund_type=fund_type,
                    period_end=period_end)


def _payload(fund_code, report_period, channel, endpoint, rows,
             fetched_at=None, raw_sha256=None, fallback_reason=None,
             fund_name=None, fund_type=None, period_end=None):
    from .. import normalize
    return {
        "schema": "funddiff/holdings@1",
        "fund_code": fund_code,
        "fund_name": normalize.clean_name(fund_name),
        "fund_type": normalize.clean_name(fund_type),
        "report_period": report_period,
        "period_end": period_end,
        "rows": rows,
        "status": "ok",
        "error_kind": None,
        "structural_note": None,
        "sample": None,
        "source": {
            "channel": channel,
            "endpoint": endpoint,
            "fetched_at": fetched_at,
            "raw_sha256": raw_sha256,
            **({"fallback_reason": fallback_reason} if fallback_reason else {}),
        },
    }
