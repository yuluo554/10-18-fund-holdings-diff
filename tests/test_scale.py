"""M4 规模变动：真值对齐、六字段、单位读表头、0 vs null、CLI。

全部走合成 fixtures（data/fixtures），零网络、零真实快照依赖。
"""

import json
import pathlib

import pytest

from funddiff import cli, scale, serialize

DATA_DIR = pathlib.Path(__file__).resolve().parents[1] / "data"
FIXTURES = DATA_DIR / "fixtures"
ALL_CODES = ["99000%d" % i for i in range(1, 9)]


def _config():
    return json.loads((DATA_DIR / "config" / "app.json").read_text(encoding="utf-8"))


def _read(path):
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def _build(codes=ALL_CODES, period="2026Q3", data_dir=DATA_DIR, config=None):
    return scale.build(str(data_dir), config or _config(), codes, period)


def _gmbd_html(rows, headers=None):
    headers = headers or [
        "报告期", "期间申购（亿份）", "期间赎回（亿份）",
        "期末份额（亿份）", "期末净资产（亿元）", "份额变动率"]
    head = "".join("<th>%s</th>" % item for item in headers)
    body = "".join(
        "<tr>%s</tr>" % "".join("<td>%s</td>" % cell for cell in row)
        for row in rows)
    return (
        "<html><body><script>var apidata={ content:\""
        "<div class='box'><table class='w782 comm tzxq'><thead><tr>%s</tr></thead>"
        "<tbody>%s</tbody></table></div>\"};</script></body></html>" % (head, body)
    )


def test_output_aligns_with_events_truth():
    truth = _read(FIXTURES / "truth" / "events_truth.json")
    result = _build()
    assert result["schema"] == "funddiff/scale@1"
    actual = {fund["fund_code"]: fund for fund in result["funds"]}
    for tfund in truth["funds"]:
        got = actual[tfund["fund_code"]]["scale"]
        for key, value in tfund["scale"].items():
            assert got[key] == value, (tfund["fund_code"], key)


def test_zero_flow_is_not_null_and_null_is_not_zero():
    """K3：真实 0.00 必须保留；缺失必须是 null（no_prev_baseline）。"""
    funds = {fund["fund_code"]: fund["scale"] for fund in _build()["funds"]}
    zero = funds["990004"]
    assert zero["subscribe"] == "0.00"
    assert zero["redeem"] == "0.00"
    assert zero["share_change_rate"] == "0.00%"
    assert zero["baseline"] == "available"

    missing = funds["990003"]
    assert missing["baseline"] == "no_prev_baseline"
    assert missing["subscribe"] is None
    assert missing["redeem"] is None
    assert missing["share_change_rate"] is None
    assert missing["shares"] == "5.00"  # 期末存量仍可知道

    result = _build()
    assert result["totals"]["zero_flow"] == 1
    assert result["totals"]["no_prev_baseline"] == 2


def test_parse_gmbd_six_fields_and_units_from_header():
    text = _gmbd_html([
        ("2026-06-30", "2.87", "2.89", "14.55", "26.12", "-3.69%"),
        ("2026-09-30", "1.49", "3.36", "24.06", "39.38", "48.93%"),
    ])
    parsed = scale.parse_scale_html(text, _config(), "2026Q3")
    assert parsed["report_period"] == "2026Q3"
    assert parsed["subscribe"] == "1.49"
    assert parsed["redeem"] == "3.36"
    assert parsed["shares"] == "24.06"
    assert parsed["net_assets"] == "39.38"
    assert parsed["share_change_rate"] == "48.93%"
    assert parsed["baseline"] == "available"
    assert parsed["units_from_header"] == {
        "subscribe": "亿份", "redeem": "亿份",
        "shares": "亿份", "net_assets": "亿元"}
    assert parsed["source"] == "gmbd"


def test_units_are_read_not_converted():
    """表头是万元就原样记录，不做代码内换算。"""
    text = _gmbd_html(
        [("2026-09-30", "14900.00", "100.00", "2406.00", "3938.00", "1.00%")],
        ["报告期", "期间申购（万元）", "期间赎回（万元）",
         "期末份额（万份）", "期末净资产（万元）", "份额变动率"])
    parsed = scale.parse_scale_html(text, _config(), "2026Q3")
    assert parsed["subscribe"] == "14900.00"  # 不除以 10000
    assert parsed["net_assets"] == "3938.00"
    assert parsed["units_from_header"]["subscribe"] == "万元"
    assert parsed["units_from_header"]["net_assets"] == "万元"
    assert parsed["units_from_header"]["shares"] == "万份"


def test_parse_zero_flow_keeps_real_zero():
    text = _gmbd_html([("2026-09-30", "0.00", "0.00", "10.00", "12.00", "0.00%")])
    parsed = scale.parse_scale_html(text, _config(), "2026Q3")
    assert parsed["baseline"] == "available"
    assert parsed["subscribe"] == "0.00"
    assert parsed["redeem"] == "0.00"
    assert scale.is_zero_flow(parsed) is True


def test_parse_no_prev_baseline_is_null_not_zero():
    text = _gmbd_html([("2026-09-30", "—", "—", "5.00", "6.20", "—")])
    parsed = scale.parse_scale_html(text, _config(), "2026Q3")
    assert parsed["baseline"] == "no_prev_baseline"
    assert parsed["subscribe"] is None
    assert parsed["redeem"] is None
    assert parsed["share_change_rate"] is None
    assert parsed["shares"] == "5.00"
    assert scale.is_zero_flow(parsed) is False


def test_parse_selects_requested_period():
    text = _gmbd_html([
        ("2025-12-31", "9.99", "9.99", "9.99", "9.99", "9.99%"),
        ("2026-03-31", "3.00", "2.00", "20.00", "30.00", "1.00%"),
        ("2026-09-30", "1.49", "3.36", "24.06", "39.38", "48.93%"),
    ])
    parsed = scale.parse_scale_html(text, _config(), "2026Q3")
    assert parsed["subscribe"] == "1.49"


def test_parse_missing_period_row_raises():
    text = _gmbd_html([("2026-06-30", "2.87", "2.89", "14.55", "26.12", "-3.69%")])
    with pytest.raises(scale.ScaleParseError):
        scale.parse_scale_html(text, _config(), "2026Q3")


def test_parse_missing_unit_raises():
    text = _gmbd_html(
        [("2026-09-30", "1.49", "3.36", "24.06", "39.38", "48.93%")],
        ["报告期", "期间申购", "期间赎回", "期末份额", "期末净资产", "份额变动率"])
    with pytest.raises(scale.ScaleParseError):
        scale.parse_scale_html(text, _config(), "2026Q3")


def test_parse_records_supplied_page_hash():
    text = _gmbd_html([("2026-09-30", "1.49", "3.36", "24.06", "39.38", "48.93%")])
    digest = "a" * 64
    parsed = scale.parse_scale_html(text, _config(), "2026Q3", raw_sha256=digest)
    assert parsed["raw_sha256"] == digest


def test_product_rejects_zero_where_baseline_is_missing():
    """K3 门禁：no_prev_baseline 时流量字段不得写成 0。"""
    scale_payload = _read(FIXTURES / "q2026q3" / "events" / "990003.json")["scale"]
    assert scale_payload["baseline"] == "no_prev_baseline"
    scale_payload["subscribe"] = "0.00"
    with pytest.raises(ValueError) as exc:
        scale._validate_scale(scale_payload, "2026Q3", "990003")
    assert "不得补 0" in str(exc.value)


def test_product_rejects_missing_units():
    scale_payload = _read(FIXTURES / "q2026q3" / "events" / "990001.json")["scale"]
    scale_payload["units_from_header"] = {"subscribe": "亿份"}
    with pytest.raises(ValueError) as exc:
        scale._validate_scale(scale_payload, "2026Q3", "990001")
    assert "net_assets 单位" in str(exc.value)


def test_deterministic_double_build():
    first = serialize.dumps(_build())
    second = serialize.dumps(_build())
    assert first == second
    parsed = json.loads(first)
    assert [fund["fund_code"] for fund in parsed["funds"]] == sorted(ALL_CODES)


def test_missing_events_is_gate_error():
    with pytest.raises(scale.ScaleError):
        _build(codes=["990001"], period="2026Q1")
    with pytest.raises(scale.ScaleError):
        _build(codes=[])


def test_cli_scale_runs_and_writes_product(capsys, tmp_path):
    store_file = str(tmp_path / "watchlist.json")
    for code in ALL_CODES:
        cli.main(["--store", store_file, "--data-dir", str(DATA_DIR),
                  "watch", "add", code])
    capsys.readouterr()
    code = cli.main(["--store", store_file, "--data-dir", str(DATA_DIR),
                     "scale", "--period", "2026Q3", "--json"])
    captured = capsys.readouterr()
    assert code == cli.EXIT_OK
    payload = json.loads(captured.out)
    assert payload["schema"] == "funddiff/scale@1"
    by_code = {fund["fund_code"]: fund for fund in payload["funds"]}
    assert by_code["990004"]["scale"]["subscribe"] == "0.00"
    assert by_code["990003"]["scale"]["subscribe"] is None

    out_file = pathlib.Path(__file__).resolve().parents[1] / "snapshots" / (
        "q2026q3") / "scale.json"
    assert out_file.is_file()
    assert json.loads(out_file.read_text(encoding="utf-8"))["schema"] == payload["schema"]


def test_cli_scale_exit_codes(capsys, tmp_path):
    store_file = str(tmp_path / "watchlist.json")
    code = cli.main(["--store", store_file, "--data-dir", str(DATA_DIR), "scale"])
    assert code == cli.EXIT_GATE_FAILED
    assert "清单为空" in capsys.readouterr().err

    cli.main(["--store", store_file, "--data-dir", str(DATA_DIR),
              "watch", "add", "990001"])
    capsys.readouterr()
    code = cli.main(["--store", store_file, "--data-dir", str(DATA_DIR),
                     "scale", "--fund", "999999"])
    assert code == cli.EXIT_GATE_FAILED
    assert "未在清单中" in capsys.readouterr().err

    code = cli.main(["--store", store_file, "--data-dir", str(DATA_DIR),
                     "scale", "--period", "2026Q9"])
    assert code == cli.EXIT_USAGE

    code = cli.main(["--store", store_file, "--data-dir", str(DATA_DIR),
                     "scale", "--period", "2026Q1"])
    assert code == cli.EXIT_GATE_FAILED
    assert "缺少事件快照" in capsys.readouterr().err
