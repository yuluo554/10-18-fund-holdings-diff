"""报告期与披露窗口（M1，纯本地，零网络）。

纪律：
- 业务逻辑不读系统时钟（K4）：窗口由 --as-of 决定；缺省时才取当天并打印；
- 披露状态三态严格区分：已披露 / 待披露 / 无数据；
- 披露截止日由法规规则 + 国务院节假日日历推导，配置不写死具体日期；
- 所需年份的日历未登记时，截止日记 null + unverified，禁止近似冒充。
"""

import datetime
import re

QUARTER_ORDER = ("Q1", "Q2", "Q3", "Q4")

STATUS_DISCLOSED = "已披露"
STATUS_PENDING = "待披露"
STATUS_NO_DATA = "无数据"

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# 防御性上限：15 个工作日绝不会越过一年；越过即说明配置或日历异常。
_MAX_SPAN_DAYS = 366


class WindowError(Exception):
    """日期或窗口参数非法。对应退出码 2。"""


def parse_date(value):
    if isinstance(value, datetime.date):
        return value
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
    try:
        return datetime.date(year, month, day)
    except ValueError as exc:
        raise WindowError("quarters.%s.period_end 非法：%s" % (quarter, exc))


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


def _is_workday(entry, day):
    """调休上班日优先（周末也可上班）；法定假日与周末不计。"""
    text = day.isoformat()
    if text in entry.get("makeup_workdays", []):
        return True
    if text in entry.get("holidays", []):
        return False
    return day.weekday() < 5


def _deadline(config, period_end):
    """按法规规则推导截止日；日历缺年份时返回不可计算。"""
    rule = config["disclosure_rule"]
    count = rule["count"]
    calendar = rule["calendar"]

    day = period_end + datetime.timedelta(days=1)
    remaining = count
    used_years = []
    while remaining > 0:
        year_key = "%04d" % day.year
        entry = calendar.get(year_key)
        if entry is None:
            return {
                "disclosure_deadline": None,
                "unverified": True,
                "unverified_reason": "calendar_missing:%s" % year_key,
                "calendar_years": used_years,
            }
        if year_key not in used_years:
            used_years.append(year_key)
        if _is_workday(entry, day):
            remaining -= 1
            if remaining == 0:
                return {
                    "disclosure_deadline": day.isoformat(),
                    "unverified": False,
                    "unverified_reason": None,
                    "calendar_years": used_years,
                }
        day += datetime.timedelta(days=1)
        if (day - period_end).days > _MAX_SPAN_DAYS:
            return {
                "disclosure_deadline": None,
                "unverified": True,
                "unverified_reason": "deadline_out_of_range",
                "calendar_years": used_years,
            }
    raise AssertionError("unreachable")


def window_for_period(config, period):
    year, quarter = split_period(period)
    period_end = _quarter_end(config, year, quarter)
    prev_end = _quarter_end(config, *_split_year_quarter(previous_period(period)))
    period_start = prev_end + datetime.timedelta(days=1)

    deadline = _deadline(config, period_end)
    rule = config["disclosure_rule"]
    return {
        "report_period": period,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "disclosure_deadline": deadline["disclosure_deadline"],
        "unverified": deadline["unverified"],
        "unverified_reason": deadline["unverified_reason"],
        "deadline_rule": rule["kind"],
        "deadline_count": rule["count"],
        "deadline_basis": "自季度结束次日起算；周末与法定节假日不计，调休上班日计入。",
        "calendar_years": deadline["calendar_years"],
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
    if window["disclosure_deadline"] is None:
        window["past_deadline"] = None
    else:
        window["past_deadline"] = as_of_date > parse_date(window["disclosure_deadline"])
    return window, as_of_date


def disclosure_status(reports_available, reports, fund_code, period, as_of=None):
    """三态判定。

    reports_available=False 表示官方元数据不可用 → 无数据（不得与"待披露"合并）。
    as_of 给出时按历史时点回放：只有 report_send_date <= as_of 才算已披露；
    发送日缺失或非法时不能证明当时已披露，按"待披露"处理。
    """
    if not reports_available:
        return STATUS_NO_DATA
    cutoff = parse_date(as_of) if as_of is not None else None
    for report in reports:
        if report.get("fundcode") != fund_code or report.get("report_period") != period:
            continue
        if cutoff is None:
            return STATUS_DISCLOSED
        send_date = report.get("report_send_date")
        try:
            sent = parse_date(send_date)
        except WindowError:
            continue
        if sent <= cutoff:
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
