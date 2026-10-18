"""规模变动（M4）：`gmbd` 六字段解析 + 缺失/零值区分 + `scale@1` 产物。

口径（plan/03 §5.2、HANDOFF-M4）：
- 六字段：报告期 / 期间申购 / 期间赎回 / 期末份额 / 期末净资产 / 份额变动率；
- 单位一律读表头原样记录，不做代码内换算（万元不拍脑袋变亿元）；
- K3：缺失是 null，真实 0 是 "0.00"，二者必须可区分；
- 新成立基金无上季 → baseline=no_prev_baseline，流量字段必须为 null（不得补 0）；
- `scale@1` 从 events 台账读取，并校验单位、baseline 与数值类型；漂移 → exit 5。
"""

import datetime
import hashlib
import html as html_module
import re
from decimal import Decimal, InvalidOperation

from . import events, window

SCHEMA = "funddiff/scale@1"

BASELINE_AVAILABLE = "available"
BASELINE_NO_PREV = "no_prev_baseline"
BASELINES = (BASELINE_AVAILABLE, BASELINE_NO_PREV)

SOURCE = "gmbd"

SCALE_KEYS = ("report_period", "subscribe", "redeem", "shares", "net_assets",
              "share_change_rate", "baseline", "units_from_header", "source",
              "raw_sha256")
FLOW_KEYS = ("subscribe", "redeem", "share_change_rate")

_TAG_RE = re.compile(r"<[^>]+>")
_ROW_RE = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.S | re.I)
_TABLE_RE = re.compile(r"<table\b[^>]*>.*?</table>", re.S | re.I)
_APIDATA_RE = re.compile(
    r'var\s+apidata\s*=\s*\{\s*content\s*:\s*"(.*?)"\s*[,}]', re.S)
_DATE_RE = re.compile(r"^(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})日?$")
_UNIT_RE = re.compile(r"[（(]\s*([^（）()]+?)\s*[）)]")
_MISSING = ("", "—", "-", "--", "暂无", "无", "N/A", "n/a")
_THOUSANDS_RE = re.compile(r"^-?\d{1,3}(,\d{3})+(\.\d+)?$")


class ScaleError(Exception):
    """events 台账缺失/清单为空等门禁失败（exit 1）。"""


class ScaleParseError(Exception):
    """`gmbd` 响应结构无法解析（不猜单位、不猜数值）。"""

    def __init__(self, message, raw_text=""):
        Exception.__init__(self, message)
        self.raw_text = raw_text or ""


def _text(fragment):
    if fragment is None:
        return ""
    plain = html_module.unescape(_TAG_RE.sub(" ", fragment))
    return re.sub(r"\s+", " ", plain).strip()


def normalize_date(value):
    text = _text(value)
    match = _DATE_RE.match(text)
    if not match:
        return None
    try:
        return datetime.date(int(match.group(1)), int(match.group(2)),
                             int(match.group(3))).isoformat()
    except ValueError:
        return None


def _cells(row_html):
    return re.findall(r"<td\b[^>]*>(.*?)</td>", row_html, re.S | re.I)


def clean_value(value):
    """单元格 → 字符串或 None。

    - 空/破折号/暂无 → None（缺失，不是 0）；
    - 千分位逗号去除（纯格式，不改数值）；
    - 其余原样保留（含 "0.00" 与百分号），由校验层判断类型。
    """
    text = _text(value)
    if text in _MISSING:
        return None
    if _THOUSANDS_RE.match(text):
        text = text.replace(",", "")
    return text


def _decimal_or_none(value, where):
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ScaleParseError("%s 不是十进制数值：%r" % (where, value))


def _unit_from_header(header):
    match = _UNIT_RE.search(header)
    if not match:
        return None
    unit = match.group(1).strip()
    return unit or None


def _column(headers, keywords):
    for index, text in enumerate(headers):
        for keyword in keywords:
            if keyword in text:
                return index
    return None


def parse_scale_html(text, config, period, raw_sha256=None):
    """解析 `gmbd` 响应（已解码文本），返回 events.scale 同形对象。

    - 表头列名或单位缺失 → ScaleParseError（不猜）；
    - 找不到请求报告期 → ScaleParseError；
    - 单位原样写入 units_from_header，代码不做换算。
    """
    content = text or ""
    api = _APIDATA_RE.search(content)
    if api:
        content = api.group(1)
    table_match = _TABLE_RE.search(content)
    if not table_match:
        raise ScaleParseError("gmbd 响应未找到表格", content[:2000])
    table = table_match.group(0)

    header_cells = []
    for row in _ROW_RE.findall(table):
        if re.search(r"<th\b", row, re.I):
            cells = re.findall(r"<th\b[^>]*>(.*?)</th>", row, re.S | re.I)
            header_cells = [_text(cell) for cell in cells]
            break
    if not header_cells:
        raise ScaleParseError("gmbd 表格缺少表头", table[:2000])

    date_index = _column(header_cells, ("报告期", "日期"))
    subscribe_index = _column(header_cells, ("申购",))
    redeem_index = _column(header_cells, ("赎回",))
    # 「期末份额」优先；退而求其次时排除「份额变动率」。
    shares_index = _column(header_cells, ("期末份额",))
    if shares_index is None:
        for index, text in enumerate(header_cells):
            if "份额" in text and "变动率" not in text:
                shares_index = index
                break
    assets_index = _column(header_cells, ("净资产",))
    rate_index = _column(header_cells, ("变动率",))
    required = (date_index, subscribe_index, redeem_index, shares_index,
                assets_index, rate_index)
    if any(index is None for index in required):
        raise ScaleParseError(
            "gmbd 表头缺少必需列：%s" % " | ".join(header_cells), table[:2000])

    units = {}
    for key, index in (("subscribe", subscribe_index),
                       ("redeem", redeem_index),
                       ("shares", shares_index),
                       ("net_assets", assets_index)):
        unit = _unit_from_header(header_cells[index])
        if unit:
            units[key] = unit
    # 申购份额与净资产必须有单位，否则"单位读表头"无法成立。
    for key in ("subscribe", "net_assets"):
        if key not in units:
            raise ScaleParseError(
                "gmbd 表头缺少 %s 单位：%s" % (
                    key, " | ".join(header_cells)), table[:2000])

    period_end = window.period_end_of(config, period)
    selected = None
    for row_html in _ROW_RE.findall(table):
        if re.search(r"<th\b", row_html, re.I):
            continue
        cells = [_text(cell) for cell in _cells(row_html)]
        if len(cells) <= max(required):
            continue
        row_date = normalize_date(cells[date_index])
        if row_date == period_end:
            selected = cells
            break
    if selected is None:
        raise ScaleParseError(
            "gmbd 未找到报告期 %s（期末 %s）的规模记录" % (period, period_end),
            table[:2000])

    values = {
        "subscribe": clean_value(selected[subscribe_index]),
        "redeem": clean_value(selected[redeem_index]),
        "shares": clean_value(selected[shares_index]),
        "net_assets": clean_value(selected[assets_index]),
        "share_change_rate": clean_value(selected[rate_index]),
    }
    for key in ("subscribe", "redeem", "shares", "net_assets"):
        _decimal_or_none(values[key], key)

    rate = values["share_change_rate"]
    if rate is not None and not re.match(r"^-?\d+(\.\d+)?%$", rate):
        raise ScaleParseError("份额变动率格式非法：%r" % rate)

    # 三个流量字段全缺失 = 无上季基准；此时金额必须是 null，不能补 0。
    no_baseline = (values["subscribe"] is None and values["redeem"] is None
                   and values["share_change_rate"] is None)

    return {
        "report_period": period,
        "subscribe": values["subscribe"],
        "redeem": values["redeem"],
        "shares": values["shares"],
        "net_assets": values["net_assets"],
        "share_change_rate": values["share_change_rate"],
        "baseline": BASELINE_NO_PREV if no_baseline else BASELINE_AVAILABLE,
        "units_from_header": units,
        "source": SOURCE,
        "raw_sha256": raw_sha256,
    }


def _validate_scale(scale, period, fund_code):
    if not isinstance(scale, dict):
        raise ValueError("内部一致性：events.scale 不是对象（%s）" % fund_code)
    missing = [key for key in SCALE_KEYS if key not in scale]
    if missing:
        raise ValueError("内部一致性：scale 缺少字段 %s（%s）" % (
            ", ".join(missing), fund_code))
    if scale["report_period"] != period:
        raise ValueError("内部一致性：scale 报告期 %r 与请求 %r 不一致（%s）" % (
            scale["report_period"], period, fund_code))
    baseline = scale["baseline"]
    if baseline not in BASELINES:
        raise ValueError("内部一致性：未知 baseline %r（%s）" % (
            baseline, fund_code))
    if scale["source"] != SOURCE:
        raise ValueError("内部一致性：scale.source 必须是 gmbd，实际 %r（%s）" % (
            scale["source"], fund_code))
    raw_sha = scale["raw_sha256"]
    if raw_sha is not None and not re.match(r"^[0-9a-f]{64}$", str(raw_sha)):
        raise ValueError("内部一致性：scale.raw_sha256 必须是 64 位小写十六进制（%s）"
                         % fund_code)

    units = scale["units_from_header"]
    if not isinstance(units, dict):
        raise ValueError("内部一致性：units_from_header 必须是对象（%s）" % fund_code)
    for key in ("subscribe", "net_assets"):
        if not units.get(key):
            raise ValueError(
                "内部一致性：units_from_header 缺少 %s 单位（%s）" % (key, fund_code))

    for key in ("subscribe", "redeem", "shares", "net_assets"):
        value = scale[key]
        if value is not None:
            try:
                Decimal(str(value))
            except (InvalidOperation, ValueError):
                raise ValueError("内部一致性：%s 不是十进制数值：%r（%s）" % (
                    key, value, fund_code))
    rate = scale["share_change_rate"]
    if rate is not None and not re.match(r"^-?\d+(\.\d+)?%$", str(rate)):
        raise ValueError("内部一致性：share_change_rate 格式非法 %r（%s）" % (
            rate, fund_code))

    # K3 延伸：no_prev_baseline 时不得把缺失写成 0。
    if baseline == BASELINE_NO_PREV:
        for key in FLOW_KEYS:
            if scale[key] is not None:
                raise ValueError(
                    "内部一致性：baseline=no_prev_baseline 时 %s 必须为 null，"
                    "不得补 0 或填入数值（%s）" % (key, fund_code))


def is_zero_flow(scale):
    """真实零申赎：baseline 可用且申购、赎回都恰为 0（不是 null）。"""
    if scale["baseline"] != BASELINE_AVAILABLE:
        return False
    subscribe = scale["subscribe"]
    redeem = scale["redeem"]
    if subscribe is None or redeem is None:
        return False
    return Decimal(str(subscribe)) == 0 and Decimal(str(redeem)) == 0


def build(data_dir, config, codes, period):
    """生成 `funddiff/scale@1` 产物；基金代码升序。"""
    if period is None:
        raise ScaleError(
            "缺少报告期：先 watch/window 确定报告期，或显式传 --period YYYYQn")
    window.parse_period(period)
    if not codes:
        raise ScaleError("清单为空。用 `funddiff watch add <code>` 添加。")

    info = window.window_for_period(config, period)
    funds = []
    totals = {BASELINE_AVAILABLE: 0, BASELINE_NO_PREV: 0, "zero_flow": 0}
    for code in sorted(codes):
        payload = events.load_events(data_dir, period, code)
        if payload is None:
            raise ScaleError(
                "缺少事件快照：%s（先具备 %s 的 events 台账）" % (code, period))
        events.validate_events(payload, period, code)
        scale = payload["scale"]
        _validate_scale(scale, period, code)
        funds.append({
            "fund_code": code,
            "fund_name": payload.get("fund_name"),
            "inputs": {"events": events.input_pointer(period, code)},
            "scale": scale,
        })
        totals[scale["baseline"]] = totals[scale["baseline"]] + 1
        if is_zero_flow(scale):
            totals["zero_flow"] = totals["zero_flow"] + 1

    return {
        "schema": SCHEMA,
        "report_period": period,
        "period_start": info["period_start"],
        "period_end": info["period_end"],
        "generated_at": window.today_iso(),
        "funds": funds,
        "totals": totals,
    }
