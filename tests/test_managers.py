"""M4 经理变更：真值对齐、四类判定、区间来自配置、jjjl 解析、快照留证、CLI。

全部走合成 fixtures（data/fixtures），零网络、零真实快照依赖。
"""

import copy
import hashlib
import json
import pathlib
import shutil

import pytest

from funddiff import cli, managers, serialize

DATA_DIR = pathlib.Path(__file__).resolve().parents[1] / "data"
FIXTURES = DATA_DIR / "fixtures"
ALL_CODES = ["99000%d" % i for i in range(1, 9)]


def _config():
    return json.loads((DATA_DIR / "config" / "app.json").read_text(encoding="utf-8"))


def _read(path):
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def _build(codes=ALL_CODES, period="2026Q3", data_dir=DATA_DIR, config=None):
    return managers.build(str(data_dir), config or _config(), codes, period)


def _html(rows, profile=None):
    body = "".join(
        "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % row
        for row in rows)
    profiles = profile or ""
    return (
        "<html><body>"
        "<div class='boxitem'><h4 class='t'>基金经理变动一览</h4>"
        "<table class='w782 comm jloff'><thead><tr>"
        "<th>起始期</th><th>截止期</th><th>基金经理</th>"
        "<th>任职期间</th><th>任职回报</th></tr></thead>"
        "<tbody>%s</tbody></table></div>"
        "<div class='boxitem'><h4 class='t'>现任基金经理简介</h4>%s</div>"
        "</body></html>" % (body, profiles))


def _profile(name, start):
    return ("<div class='jl_office'><h4><a href='/x'>%s</a></h4>"
            "<p class='jl_intro'>上任日期：%s</p></div>" % (name, start))


def test_output_aligns_with_events_truth():
    """DoD：managers 引擎输出与 events_truth.json 逐条对齐。"""
    truth = _read(FIXTURES / "truth" / "events_truth.json")
    result = _build()
    assert result["schema"] == "funddiff/managers@1"
    assert result["report_period"] == truth["report_period"]
    actual = {fund["fund_code"]: fund for fund in result["funds"]}

    for tfund in truth["funds"]:
        fund = actual[tfund["fund_code"]]
        expected = tfund["managers"]
        got = fund["managers"]
        assert [item["change_class"] for item in got] == [
            item["change_class"] for item in expected], tfund["fund_code"]
        for exp, act in zip(expected, got):
            if "change_date" in exp:
                assert act["change_date"] == exp["change_date"], tfund["fund_code"]
        if not expected:
            assert fund["summary"]["none"] == 1, tfund["fund_code"]
        else:
            assert fund["summary"]["none"] == 0, tfund["fund_code"]


def test_four_classes_are_all_covered():
    result = _build()
    funds = {fund["fund_code"]: fund for fund in result["funds"]}
    assert funds["990002"]["managers"][0]["change_class"] == "in_period"
    assert funds["990004"]["managers"][0]["change_class"] == "prior_period"
    assert funds["990005"]["managers"][0]["change_class"] == "unparsed"
    assert funds["990001"]["managers"] == []
    assert result["totals"] == {
        "in_period": 1, "prior_period": 1, "none": 5, "unparsed": 1}


def test_classification_interval_comes_from_frozen_config():
    """K10：区间由 quarters.*.period_end 推导；改配置必改行为。"""
    config = _config()
    assert managers.classify_change("2026-07-01", "2026Q3", config) == "in_period"
    assert managers.classify_change("2026-09-30", "2026Q3", config) == "in_period"
    assert managers.classify_change("2026-06-30", "2026Q3", config) == "prior_period"
    assert managers.classify_change("2026-08-15", "2026Q3", config) == "in_period"

    mutated = copy.deepcopy(config)
    mutated["quarters"]["Q3"]["period_end"] = "08-01"
    assert managers.classify_change("2026-08-15", "2026Q3", mutated) is None

    mutated2 = copy.deepcopy(config)
    mutated2["quarters"]["Q2"]["period_end"] = "05-31"
    # Q3 起点随上季末变为 06-01：06-30 从"上季"落入"本季"。
    assert managers.classify_change("2026-06-30", "2026Q3", mutated2) == "in_period"


def test_parse_jjjl_change_row_and_profile_start():
    text = _html(
        [("2026-08-15", "至今", "<a href='/m'>样例经理甲</a>", "64天", "1.23%")],
        _profile("样例经理甲", "2020-03-01"))
    records = managers.parse_managers_html(text, _config(), "2026Q3")
    assert len(records) == 1
    record = records[0]
    assert record["name"] == "样例经理甲"
    assert record["start"] == "2020-03-01"  # 上任日期来自简介
    assert record["change_date"] == "2026-08-15"  # 变更日来自变动一览
    assert record["end"] is None
    assert record["change_class"] == "in_period"
    assert record["in_period"] is True
    assert record["source"] == "jjjl"


def test_parse_multiple_names_in_one_change_row():
    text = _html(
        [("2026-08-15", "至今", "张坤 彭珂", "64天", "1.23%")],
        _profile("张坤", "2012-09-28") + _profile("彭珂", "2021-06-01"))
    records = managers.parse_managers_html(text, _config(), "2026Q3")
    assert [(item["name"], item["start"]) for item in records] == [
        ("张坤", "2012-09-28"), ("彭珂", "2021-06-01")]


def test_parse_prior_period_and_no_change():
    text = _html(
        [("2026-05-20", "至今", "样例经理乙", "100天", "2.00%")],
        _profile("样例经理乙", "2018-07-01"))
    record = managers.parse_managers_html(text, _config(), "2026Q3")[0]
    assert record["change_class"] == "prior_period"
    assert record["in_period"] is False

    # 只有历史记录（早于上一报告期）→ 本报告无变更，不是 unparsed。
    old = _html([("2019-01-01", "2020-01-01", "旧经理", "365天", "1.00%")])
    assert managers.parse_managers_html(old, _config(), "2026Q3") == []

    # 表头完整、表体为空 → 无变更记录。
    empty = _html([])
    assert managers.parse_managers_html(empty, _config(), "2026Q3") == []


def test_parse_unparsed_row_keeps_page_snapshot():
    text = _html([("2026-13-40", "至今", "样例经理甲", "1天", "0.00%")])
    records = managers.parse_managers_html(text, _config(), "2026Q3")
    assert len(records) == 1
    record = records[0]
    assert record["change_class"] == "unparsed"
    assert record["name"] is None and record["change_date"] is None
    assert "2026-13-40" in record["raw_text"]
    assert record["snapshot"]["sha256"] == hashlib.sha256(
        record["raw_text"].encode("utf-8")).hexdigest()


def test_parse_missing_table_raises_with_evidence():
    text = "<html><body><h4>基金经理变动一览</h4><p>页面结构变了</p></body></html>"
    with pytest.raises(managers.ManagerParseError) as exc:
        managers.parse_managers_html(text, _config(), "2026Q3")
    assert "表格" in str(exc.value)
    assert exc.value.raw_text
    assert len(exc.value.raw_sha256) == 64


def test_unparsed_product_entry_carries_snapshot():
    result = _build(codes=["990005"])
    record = result["funds"][0]["managers"][0]
    assert record["change_class"] == "unparsed"
    assert record["snapshot"]["kind"] == "page_text"
    assert record["snapshot"]["raw_text"] == record["raw_text"]
    assert record["snapshot"]["sha256"] == hashlib.sha256(
        record["raw_text"].encode("utf-8")).hexdigest()
    assert record["name"] is None and record["change_date"] is None


def test_deterministic_double_build():
    first = serialize.dumps(_build())
    second = serialize.dumps(_build())
    assert first == second
    parsed = json.loads(first)
    assert [fund["fund_code"] for fund in parsed["funds"]] == sorted(ALL_CODES)


def test_missing_events_is_gate_error():
    with pytest.raises(managers.ManagerError):
        _build(codes=["990001"], period="2026Q1")
    with pytest.raises(managers.ManagerError):
        _build(codes=[])


def test_label_drift_is_internal_consistency_error(tmp_path):
    """台账 label 与配置区间重算不一致 → 内部一致性错误（exit 5），不静默采信。"""
    data_dir = tmp_path / "data"
    (data_dir / "config").mkdir(parents=True)
    shutil.copyfile(DATA_DIR / "config" / "app.json", data_dir / "config" / "app.json")
    target = data_dir / "fixtures" / "q2026q3" / "events"
    target.mkdir(parents=True)
    payload = _read(FIXTURES / "q2026q3" / "events" / "990002.json")
    payload["managers"][0]["change_class"] = "prior_period"  # 08-15 实际应为本季内
    (target / "990002.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        managers.build(str(data_dir), _config(), ["990002"], "2026Q3")
    assert "配置区间重算" in str(exc.value)


def test_cli_managers_runs_and_writes_product(capsys, tmp_path):
    store_file = str(tmp_path / "watchlist.json")
    for code in ALL_CODES:
        cli.main(["--store", store_file, "--data-dir", str(DATA_DIR),
                  "watch", "add", code])
    capsys.readouterr()
    code = cli.main(["--store", store_file, "--data-dir", str(DATA_DIR),
                     "managers", "--period", "2026Q3", "--json"])
    captured = capsys.readouterr()
    assert code == cli.EXIT_OK
    payload = json.loads(captured.out)
    assert payload["schema"] == "funddiff/managers@1"
    by_code = {fund["fund_code"]: fund for fund in payload["funds"]}
    assert by_code["990002"]["managers"][0]["change_class"] == "in_period"
    assert by_code["990004"]["managers"][0]["change_class"] == "prior_period"
    assert by_code["990005"]["managers"][0]["change_class"] == "unparsed"

    out_file = pathlib.Path(__file__).resolve().parents[1] / "snapshots" / (
        "q2026q3") / "managers.json"
    assert out_file.is_file()
    assert json.loads(out_file.read_text(encoding="utf-8"))["schema"] == payload["schema"]


def test_cli_managers_exit_codes(capsys, tmp_path):
    store_file = str(tmp_path / "watchlist.json")
    code = cli.main(["--store", store_file, "--data-dir", str(DATA_DIR), "managers"])
    assert code == cli.EXIT_GATE_FAILED
    assert "清单为空" in capsys.readouterr().err

    cli.main(["--store", store_file, "--data-dir", str(DATA_DIR),
              "watch", "add", "990001"])
    capsys.readouterr()
    code = cli.main(["--store", store_file, "--data-dir", str(DATA_DIR),
                     "managers", "--fund", "999999"])
    assert code == cli.EXIT_GATE_FAILED
    assert "未在清单中" in capsys.readouterr().err

    code = cli.main(["--store", store_file, "--data-dir", str(DATA_DIR),
                     "managers", "--period", "2026Q9"])
    assert code == cli.EXIT_USAGE

    code = cli.main(["--store", store_file, "--data-dir", str(DATA_DIR),
                     "managers", "--period", "2026Q1"])
    assert code == cli.EXIT_GATE_FAILED
    assert "缺少事件快照" in capsys.readouterr().err
