"""报告期与披露窗口（M1，纯本地，零网络）。

纪律：
- 业务逻辑不读系统时钟（K4）：窗口由 --as-of 决定；缺省时才取当天并打印；
- 披露状态三态严格区分：已披露 / 待披露 / 无数据；
- 季度窗口值来自配置；未按法规原文核对的季度保留 unverified 标记并原样透出。
"""

import datetime
import re

from .config import ConfigError

QUARTER_ORDER = ("Q1", "Q2", "Q3", "Q4")

STATUS_DISCLOSED = "已披露"
STATUS_PENDING = "待披露"
STATUS_NO_DATA = "无数据"

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class WindowError(Exception):
    """日期或窗口参数非法。对应退出码 2。"""


def parse_date(value):
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise WindowError("日期必须是 YYYY-MM-DD，实际为 %r" % (value,))
    try:
        return datetime.date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError as exc:
        raise WindowError("日期非法：%r（%s）" % (value, exc))


def _month_day(config, quarter):
    entry = config["quarters"][quarter]
    month_text, day_text = entry["period_end"].split("-")
    return int(month_text), int(day_text)


def _quarter_end(config, year, quarter):
    month, day = _month_day(config, quarter)
    return datetime.date(year, month, day)


def period_for_date(config, day):
    """返回该日期所属的（最近一个已结束的）报告期，如 2026Q3。"""
    for quarter in reversed(QUARTER_ORDER):
        end = _quarter_end(config, day.year, quarter)
        if day >= end:
            return "%d%s" % (day.year, quarter)
    return "%dQ4" % (day.year - 1)


def split_period(period):
    if not isinstance(period, str) or len(period) != 6:
        raise WindowError("报告期格式必须是 YYYYQn，实际为 %r" % (period,))
    year_text, quarter = period[:4], period[4:]
    if quarter not in QUARTER_ORDER or not year_text.isdigit():
        raise WindowError("报告期格式必须是 YYYYQn，实际为 %r" % (period,))
    return int(year_text), quarter


def previous_period(period):
    year, quarter = split_period(period)
    index = QUARTER_ORDER.index(quarter)
    if index == 0:
        return "%dQ4" % (year - 1)
    return "%d%s" % (year, QUARTER_ORDER[index - 1])


def window_for_period(config, period):
    year, quarter = split_period(period)
    period_end = _quarter_end(config, year, quarter)
    prev_end = _quarter_end(config, *_split_year_quarter(previous_period(period)))
    period_start = prev_end + datetime.timedelta(days=1)

    entry = config["quarters"][quarter]
    deadline_month, deadline_day = [int(part) for part in entry["disclosure_deadline"].split("-")]
    deadline_year = year + 1 if deadline_month < period_end.month else year
    deadline = datetime.date(deadline_year, deadline_month, deadline_day)

    return {
        "report_period": period,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "disclosure_deadline": deadline.isoformat(),
        "unverified": bool(entry.get("unverified", True)),
    }


def _split_year_quarter(period):
    year, quarter = split_period(period)
    return year, quarter


def resolve_window(config, as_of=None):
    """把 --as-of 解析成本期窗口。返回 (window, as_of_date)。"""
    if as_of is None:
        as_of_date = datetime.date.today()
    else:
        as_of_date = parse_date(as_of)
    period = period_for_date(config, as_of_date)
    window = window_for_period(config, period)
    window["as_of"] = as_of_date.isoformat()
    window["past_deadline"] = as_of_date > parse_date(window["disclosure_deadline"])
    return window, as_of_date


def disclosure_status(reports_available, reports, fund_code, period):
    """三态判定。

    reports_available=False 表示官方元数据不可用 → 无数据（不得与"待披露"合并）。
    """
    if not reports_available:
        return STATUS_NO_DATA
    for report in reports:
        if report.get("fundcode") == fund_code and report.get("report_period") == period:
            return STATUS_DISCLOSED
    return STATUS_PENDING


def summarize(states):
    counts = {STATUS_DISCLOSED: 0, STATUS_PENDING: 0, STATUS_NO_DATA: 0}
    for state in states:
        counts[state] = counts.get(state, 0) + 1
    return counts


def require_period(config, period):
    """校验报告期字符串并返回窗口（供 M3/M5 复用）。"""
    split_period(period)  # 非法即抛 WindowError
    return window_for_period(config, period)
