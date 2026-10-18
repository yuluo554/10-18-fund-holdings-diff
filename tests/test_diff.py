"""M3 diff 引擎测试：真值对齐、五态、双口径冲突、失败季、确定性、CLI 接线。

全部走合成 fixtures（data/fixtures），零网络、零真实快照依赖。
"""

import copy
import json
import pathlib

import pytest

from funddiff import cli, diff, serialize

DATA_DIR = pathlib.Path(__file__).resolve().parents[1] / "data"
FIXTURES = DATA_DIR / "fixtures"
ALL_CODES = ["99000%d" % i for i in range(1, 9)]


def _config():
    return json.loads((DATA_DIR / "config" / "app.json").read_text(encoding="utf-8"))


def _read(path):
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def _build(codes=ALL_CODES, period="2026Q3", mode="computed"):
    return diff.build(str(DATA_DIR), _config(), codes, period, mode)


def test_output_aligns_with_truth_fixture_entry_by_entry():
    """DoD：diff 引擎输出必须与 data/fixtures/truth/diff_truth.json 逐条对齐。"""
    truth = _read(FIXTURES / "truth" / "diff_truth.json")
    result = _build()
    assert result["schema"] == "funddiff/diff@1"
    assert result["report_period"] == truth["report_period"]
    assert result["prev_period"] == truth["prev_period"]
    actual = {fund["fund_code"]: fund for fund in result["funds"]}

    for tfund in truth["funds"]:
        fund = actual[tfund["fund_code"]]
        assert fund["summary"] == tfund["summary"], tfund["fund_code"]
        if tfund["expected_holdings_status"] != "ok":
            # 失败季 → insufficient_data；空仓 → ok 但 0 条。两者都不得有 entries。
            expected_status = ("insufficient_data"
                               if tfund["expected_holdings_status"] == "failed"
                               else "ok")
            assert fund["status"] == expected_status, tfund["fund_code"]
            assert fund["entries"] == [], tfund["fund_code"]
            continue
        assert fund["status"] == "ok"
        actual_entries = {e["stock_code"]: e for e in fund["entries"]}
        for tentry in tfund["entries"]:
            entry = actual_entries[tentry["stock_code"]]
            for key in ("prev_ratio", "cur_ratio", "delta", "status", "basis"):
                assert entry[key] == tentry[key], (
                    tfund["fund_code"], tentry["stock_code"], key)


def test_failed_quarter_is_insufficient_data_not_empty():
    """任一季 failed → 整体 insufficient_data、entries 空；与空仓（ok + 0 条）区分。"""
    result = _build()
    funds = {fund["fund_code"]: fund for fund in result["funds"]}
    assert funds["990006"]["status"] == "insufficient_data"
    assert funds["990007"]["status"] == "insufficient_data"
    assert funds["990006"]["entries"] == []
    # 空仓（ETF 联接）：不是 insufficient_data
    assert funds["990003"]["status"] == "ok"
    assert funds["990003"]["summary"]["待确认"] == 0


def test_failed_prev_quarter_only_also_insufficient(tmp_path):
    """上季失败 + 本季 ok 同样整体 insufficient_data（两季失败组合全覆盖）。"""
    data_dir = tmp_path / "data"
    import shutil
    shutil.copytree(FIXTURES, data_dir / "fixtures")
    (data_dir / "config").mkdir()
    (data_dir / "config" / "app.json").write_text(
        (DATA_DIR / "config" / "app.json").read_text(encoding="utf-8"),
        encoding="utf-8")
    # 把 Q2 的 990008 从 ok 改为 failed
    path = data_dir / "fixtures" / "q2026q2" / "holdings" / "990008.json"
    payload = _read(path)
    payload["status"] = "failed"
    payload["rows"] = []
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                               indent=2) + "\n", encoding="utf-8")
    result = diff.build(str(data_dir), _config(), ["990008"], "2026Q3", "computed")
    assert result["funds"][0]["status"] == "insufficient_data"
    assert result["funds"][0]["entries"] == []


def test_five_states_and_decimal_arithmetic():
    """五态齐备；delta 是两位小数字符串（Decimal 运算，无浮点尾差）。"""
    result = _build(codes=["990001"])
    entries = {e["stock_code"]: e for e in result["funds"][0]["entries"]}
    assert entries["600005"]["status"] == "新进"
    assert entries["600005"]["prev_ratio"] is None
    assert entries["600004"]["status"] == "退出"
    assert entries["600004"]["cur_ratio"] is None
    assert entries["600001"]["status"] == "加仓"
    assert entries["600001"]["delta"] == "0.50"
    assert entries["600002"]["status"] == "减仓"
    assert entries["600002"]["delta"] == "-0.50"
    assert entries["600003"]["status"] == "不变"
    assert entries["600003"]["delta"] == "0.00"
    for entry in entries.values():
        assert entry["source_quarters"] == {"prev": "2026Q2", "cur": "2026Q3"}


def test_missing_ratio_is_pending_not_zero():
    """K3：ratio 缺失 null ≠ 0 → 待确认（insufficient_data），不参与增减判断。"""
    result = _build(codes=["990005"])
    entries = {e["stock_code"]: e for e in result["funds"][0]["entries"]}
    entry = entries["600021"]  # Q2 ratio null，Q3 有值
    assert entry["status"] == "待确认"
    assert entry["basis"] == "insufficient_data"
    assert entry["delta"] is None
    assert "ratio_null" in entry["anomalies"]


def test_anomaly_marks_present():
    result = _build(codes=["990005"])
    entries = {e["stock_code"]: e for e in result["funds"][0]["entries"]}
    assert "invalid_stock_code" in entries["ABC123"]["anomalies"]
    assert "change_type_missing" in entries["600022"]["anomalies"]
    assert entries["600020"]["anomalies"] == []


def test_provider_mode_uses_upstream_change_type():
    """provider 口径直接采信上游 PCTNVCHGTYPE，delta 用上游 change_pct。"""
    result = _build(codes=["990001"], mode="provider")
    entries = {e["stock_code"]: e for e in result["funds"][0]["entries"]}
    assert entries["600001"]["basis"] == "provider"
    assert entries["600001"]["status"] == "加仓"
    assert entries["600001"]["delta"] == "0.50"
    assert entries["600002"]["status"] == "减仓"
    assert entries["600002"]["delta"] == "-0.50"
    # 上游无标识的（新进/退出）仍走 computed
    assert entries["600005"]["basis"] == "computed"
    assert result["mode"] == "provider"


def test_conflicting_provider_label_goes_to_conflict_list():
    """上游标识与两季 ratio 自算结论不一致 → 进冲突清单，不合并、不裁决。"""
    config = _config()
    cur = _read(FIXTURES / "q2026q3" / "holdings" / "990001.json")
    prev = _read(FIXTURES / "q2026q2" / "holdings" / "990001.json")
    cur["rows"][1]["change_type"] = "增持"  # 600003 实际两季同 ratio（不变）
    fund, conflicts = diff.diff_fund(prev, cur, config, mode="computed")
    assert len(conflicts) == 1
    item = conflicts[0]
    assert item["stock_code"] == "600003"
    assert item["provider_status"] == "加仓"
    assert item["computed_status"] == "不变"
    assert item["prev_ratio"] == "8.45" and item["cur_ratio"] == "8.45"
    # 条目本身保持 computed 结论（不静默采用 provider）
    entries = {e["stock_code"]: e for e in fund["entries"]}
    assert entries["600003"]["status"] == "不变"
    assert entries["600003"]["basis"] == "computed"


def test_config_frozen_mode_is_default_and_cli_override(capsys, tmp_path):
    """缺省取配置冻结 diff.mode；--mode 可覆盖但必须显式。"""
    store_file = str(tmp_path / "watchlist.json")
    cli.main(["--store", store_file, "--data-dir", str(DATA_DIR),
              "watch", "add", "990001"])
    capsys.readouterr()
    code = cli.main(["--store", store_file, "--data-dir", str(DATA_DIR),
                     "diff", "--json"])
    captured = capsys.readouterr()
    assert code == 0
    payload = json.loads(captured.out)
    assert payload["mode"] == "computed"  # 配置冻结值
    # 显式覆盖
    code = cli.main(["--store", store_file, "--data-dir", str(DATA_DIR),
                     "diff", "--mode", "provider", "--json"])
    captured = capsys.readouterr()
    assert code == 0
    assert json.loads(captured.out)["mode"] == "provider"


def test_diff_writes_deterministic_product(tmp_path, capsys):
    """K2：同输入双跑字节一致；产物 schema funddiff/diff@1。"""
    store_file = str(tmp_path / "watchlist.json")
    for code in ALL_CODES:
        cli.main(["--store", store_file, "--data-dir", str(DATA_DIR),
                  "watch", "add", code])
    capsys.readouterr()
    argv = ["--store", store_file, "--data-dir", str(DATA_DIR), "diff", "--json"]
    code = cli.main(argv)
    first = capsys.readouterr().out
    assert code == 0
    second = (cli.main(argv), capsys.readouterr().out)[1]
    assert first == second
    payload = json.loads(first)
    assert payload["schema"] == "funddiff/diff@1"
    # 冻结产物与 CLI 输出同一来源：serialize 排序键守字节序
    assert serialize.dumps(payload) == first


def test_cli_diff_exit_codes(capsys, tmp_path):
    """清单空 → 1；基金不在清单 → 1；报告期非法 → 2。"""
    store_file = str(tmp_path / "watchlist.json")
    code = cli.main(["--store", store_file, "--data-dir", str(DATA_DIR), "diff"])
    captured = capsys.readouterr()
    assert code == cli.EXIT_GATE_FAILED
    assert "清单为空" in captured.err

    cli.main(["--store", store_file, "--data-dir", str(DATA_DIR),
              "watch", "add", "990001"])
    capsys.readouterr()
    code = cli.main(["--store", store_file, "--data-dir", str(DATA_DIR),
                     "diff", "--fund", "999999"])
    assert code == cli.EXIT_GATE_FAILED
    assert "未在清单中" in capsys.readouterr().err

    code = cli.main(["--store", store_file, "--data-dir", str(DATA_DIR),
                     "diff", "--period", "2026Q9"])
    assert code == cli.EXIT_USAGE

    # 990001 在清单中、两季快照齐备 → 正常跑完（合成 fixtures）
    code = cli.main(["--store", store_file, "--data-dir", str(DATA_DIR),
                     "diff", "--fund", "990001"])
    assert code == cli.EXIT_OK

    # 缺两季快照的季度 → 门禁失败（exit 1）
    code = cli.main(["--store", store_file, "--data-dir", str(DATA_DIR),
                     "diff", "--period", "2026Q1"])
    assert code == cli.EXIT_GATE_FAILED
    assert "缺少" in capsys.readouterr().err


def test_empty_and_missing_one_quarter_snapshot(tmp_path):
    """单季快照缺失 → 门禁失败（DiffError），不得当空仓算。"""
    config = _config()
    with pytest.raises(diff.DiffError):
        diff.build(str(DATA_DIR), config, ["990001"], "2026Q1", "computed")


def test_sorting_is_deterministic_ratio_desc_then_code():
    """同基金内：cur_ratio 降序、null 最后、再按 stock_code。"""
    result = _build(codes=["990005"])
    entries = result["funds"][0]["entries"]
    ratios = [e["cur_ratio"] for e in entries]
    assert ratios == ["8.65", "6.36", "5.05", "3.99"]
    # ratio 缺失（null）的条目排在最后：990002 的退出股 600013 cur_ratio=null
    result2 = _build(codes=["990002"])
    entries2 = result2["funds"][0]["entries"]
    assert [e["stock_code"] for e in entries2] == ["600010", "600011", "600012", "600013"]
    assert entries2[-1]["cur_ratio"] is None
    assert entries2[-1]["status"] == "退出"
    # 基金按代码升序
    full = _build()
    codes = [f["fund_code"] for f in full["funds"]]
    assert codes == sorted(codes)


def test_threshold_comes_from_config_not_code():
    """K10：阈值来自冻结配置；改配置必改行为（变异守门的对偶）。"""
    config = _config()
    config = copy.deepcopy(config)
    config["diff"]["threshold"] = "10"  # 巨大阈值：一切差额都不变
    prev = _read(FIXTURES / "q2026q2" / "holdings" / "990001.json")
    cur = _read(FIXTURES / "q2026q3" / "holdings" / "990001.json")
    fund, _ = diff.diff_fund(prev, cur, config, mode="computed")
    entries = {e["stock_code"]: e for e in fund["entries"]}
    assert entries["600001"]["status"] == "不变"
    assert entries["600001"]["delta"] == "0.50"
