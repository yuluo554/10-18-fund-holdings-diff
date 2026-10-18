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


def test_q3_is_verified_others_flagged(cfg):
    q3 = window.window_for_period(cfg, "2026Q3")
    assert q3["unverified"] is False
    q1 = window.window_for_period(cfg, "2026Q1")
    assert q1["unverified"] is True


def test_deadline_rolls_into_next_year(cfg):
    q4 = window.window_for_period(cfg, "2026Q4")
    assert q4["disclosure_deadline"] == "2027-01-31"


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
