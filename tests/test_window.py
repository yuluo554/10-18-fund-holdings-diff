import pytest

from funddiff import window

import pathlib

DATA_DIR = pathlib.Path(__file__).resolve().parents[1] / "data"


@pytest.fixture(scope="module")
def cfg():
    from funddiff import config as config_module
    return config_module.load_config(DATA_DIR)


@pytest.mark.parametrize("as_of,expected", [
    ("2026-10-18", "2026Q3"),
    ("2026-09-30", "2026Q3"),
    ("2026-09-29", "2026Q2"),
    ("2026-06-30", "2026Q2"),
    ("2026-01-05", "2025Q4"),
    ("2025-12-31", "2025Q4"),
])
def test_period_for_date(cfg, as_of, expected):
    assert window.resolve_window(cfg, as_of)[0]["report_period"] == expected


def test_window_bounds(cfg):
    info, as_of = window.resolve_window(cfg, "2026-10-18")
    assert info["period_start"] == "2026-07-01"
    assert info["period_end"] == "2026-09-30"
    assert info["as_of"] == "2026-10-18"
    assert as_of.isoformat() == "2026-10-18"


def test_deadlines_follow_workday_rule(cfg):
    expected = {
        "2025Q1": "2025-04-22",
        "2025Q2": "2025-07-21",
        "2025Q3": "2025-10-28",
        "2025Q4": "2026-01-22",
        "2026Q1": "2026-04-22",
        "2026Q2": "2026-07-21",
        "2026Q3": "2026-10-27",
    }
    for period, deadline in expected.items():
        info = window.window_for_period(cfg, period)
        assert info["disclosure_deadline"] == deadline, period
        assert info["unverified"] is False
        assert info["deadline_rule"] == "workdays_after_period_end"
        assert info["deadline_count"] == cfg["disclosure_rule"]["count"]


def test_missing_calendar_is_not_approximated(cfg):
    q4 = window.window_for_period(cfg, "2026Q4")
    assert q4["disclosure_deadline"] is None
    assert q4["unverified"] is True
    assert q4["unverified_reason"] == "calendar_missing:2027"
    assert q4["calendar_years"] == []


def test_deadline_rolls_into_next_year(cfg):
    q4 = window.window_for_period(cfg, "2025Q4")
    assert q4["disclosure_deadline"] == "2026-01-22"
    assert q4["calendar_years"] == ["2026"]


def test_past_deadline_flag(cfg):
    early, _ = window.resolve_window(cfg, "2026-10-01")
    late, _ = window.resolve_window(cfg, "2026-11-02")
    assert early["past_deadline"] is False
    assert late["past_deadline"] is True


def test_previous_period():
    assert window.previous_period("2026Q3") == "2026Q2"
    assert window.previous_period("2026Q1") == "2025Q4"


def test_no_system_clock_when_as_of_given(cfg, monkeypatch):
    """把 today() 换成炸弹，验证传 --as-of 时业务逻辑完全不读系统时钟。"""

    class FakeDatetime(object):
        date = window.datetime.date
        timedelta = window.datetime.timedelta

        @staticmethod
        def today():
            raise AssertionError("business logic must not read today()")

    monkeypatch.setattr(window, "datetime", FakeDatetime)
    info, _ = window.resolve_window(cfg, "2026-10-18")
    assert info["report_period"] == "2026Q3"


@pytest.mark.parametrize("bad", ["2026-13-01", "2026-1-1", "20261018", "", "2026-02-30"])
def test_invalid_dates_rejected(cfg, bad):
    with pytest.raises(window.WindowError):
        window.resolve_window(cfg, bad)


@pytest.mark.parametrize("bad", ["2026Q5", "26Q3", "2026-Q3", ""])
def test_invalid_periods_rejected(bad):
    with pytest.raises(window.WindowError):
        window.split_period(bad)


def test_disclosure_three_states():
    reports = [{"fundcode": "990001", "report_period": "2026Q3"}]
    assert window.disclosure_status(True, reports, "990001", "2026Q3") == window.STATUS_DISCLOSED
    assert window.disclosure_status(True, reports, "990002", "2026Q3") == window.STATUS_PENDING
    assert window.disclosure_status(False, reports, "990001", "2026Q3") == window.STATUS_NO_DATA


def test_summarize_counts_all_three():
    counts = window.summarize([window.STATUS_DISCLOSED, window.STATUS_PENDING,
                               window.STATUS_NO_DATA, window.STATUS_NO_DATA])
    assert counts == {"已披露": 1, "待披露": 1, "无数据": 2}


def test_workday_rule_holiday_and_makeup():
    import datetime

    entry = {
        "holidays": ["2025-10-01", "2025-10-02"],
        "makeup_workdays": ["2025-09-28"],
    }
    assert window._is_workday(entry, datetime.date(2025, 9, 28)) is True  # 周日调休上班
    assert window._is_workday(entry, datetime.date(2025, 10, 1)) is False  # 法定假日
    assert window._is_workday(entry, datetime.date(2025, 10, 4)) is False  # 周六
    assert window._is_workday(entry, datetime.date(2025, 10, 9)) is True  # 普通周四


def test_disclosure_as_of_replays_history():
    reports = [{
        "fundcode": "990001",
        "report_period": "2026Q3",
        "report_send_date": "2026-10-20",
    }]
    assert window.disclosure_status(
        True, reports, "990001", "2026Q3", as_of="2026-10-19") == window.STATUS_PENDING
    assert window.disclosure_status(
        True, reports, "990001", "2026Q3", as_of="2026-10-20") == window.STATUS_DISCLOSED
    # 快照存在但发送日缺失：历史时点不能证明已披露
    undated = [{"fundcode": "990001", "report_period": "2026Q3"}]
    assert window.disclosure_status(
        True, undated, "990001", "2026Q3", as_of="2026-12-31") == window.STATUS_PENDING
