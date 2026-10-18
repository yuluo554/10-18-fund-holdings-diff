"""合成 fixtures 门禁：字节确定性、真值独立复算、覆盖矩阵、披露历史回放。"""

import json
import shutil
import subprocess
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

from funddiff import eid, frozen, window

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
FIXTURES = DATA_DIR / "fixtures"
TOOL = ROOT / "tools" / "gen_fixtures.py"


def _read(path):
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _run(*args):
    return subprocess.run(
        [sys.executable, str(TOOL)] + list(args),
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def test_repo_fixture_manifest_check_passes():
    proc = _run("--check")
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")


def test_manifest_records_generator_and_seed():
    manifest = _read(FIXTURES / "MANIFEST.json")
    assert manifest["schema"] == "funddiff/fixtures-manifest@1"
    assert manifest["sample"] == "synthetic"
    assert manifest["rng"] == "splitmix64"
    assert isinstance(manifest["seed"], int)
    assert manifest["generator"] == "tools/gen_fixtures.py"
    assert manifest["files"]
    assert "MANIFEST.json" not in manifest["files"]


def test_regeneration_is_byte_identical():
    with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
        assert _run("--out", first).returncode == 0
        assert _run("--out", second).returncode == 0
        assert frozen.compare_tree(first, second, exclude=()) == []


def test_every_fixture_is_marked_synthetic():
    for path in sorted(FIXTURES.rglob("*.json")):
        payload = _read(path)
        assert payload.get("sample") == "synthetic", str(path.relative_to(ROOT))


def test_truth_contains_no_observed_fields():
    def walk(node, where):
        if isinstance(node, dict):
            for key, value in node.items():
                assert not key.startswith("observed_"), "%s 出现 %s" % (where, key)
                walk(value, where)
        elif isinstance(node, list):
            for item in node:
                walk(item, where)

    for path in sorted((FIXTURES / "truth").glob("*.json")):
        walk(_read(path), str(path.relative_to(ROOT)))


def _holdings(relative):
    payload = _read(FIXTURES / relative)
    rows = {row["stock_code"]: row["ratio"] for row in payload["rows"]}
    return payload, rows


def _format_delta(value):
    return str(value.quantize(Decimal("0.01")))


def test_diff_truth_can_be_recomputed_from_inputs():
    truth = _read(FIXTURES / "truth" / "diff_truth.json")
    app = _read(DATA_DIR / "config" / "app.json")
    threshold = Decimal(str(app["diff"]["threshold"]))

    for fund in truth["funds"]:
        prev_payload, prev = _holdings(fund["inputs"]["prev"])
        cur_payload, cur = _holdings(fund["inputs"]["cur"])
        expected_status = fund["expected_holdings_status"]
        assert prev_payload["status"] in ("ok", "empty", "failed")
        assert cur_payload["status"] == expected_status

        if expected_status != "ok":
            assert fund["entries"] == []
            continue

        expected = {}
        for code in sorted(set(prev) | set(cur)):
            prev_ratio = prev.get(code)
            cur_ratio = cur.get(code)
            if prev_ratio is None and cur_ratio is not None and code not in prev:
                status, delta, basis = "新进", None, "computed"
            elif cur_ratio is None and prev_ratio is not None and code not in cur:
                status, delta, basis = "退出", None, "computed"
            elif prev_ratio is None or cur_ratio is None:
                status, delta, basis = "待确认", None, "insufficient_data"
            else:
                difference = Decimal(cur_ratio) - Decimal(prev_ratio)
                if abs(difference) < threshold:
                    status = "不变"
                elif difference > 0:
                    status = "加仓"
                else:
                    status = "减仓"
                delta, basis = _format_delta(difference), "computed"
            expected[code] = {
                "prev_ratio": prev_ratio,
                "cur_ratio": cur_ratio,
                "delta": delta,
                "status": status,
                "basis": basis,
            }

        actual = {entry["stock_code"]: entry for entry in fund["entries"]}
        assert set(actual) == set(expected), fund["fund_code"]
        for code, wanted in expected.items():
            for key, value in wanted.items():
                assert actual[code][key] == value, (fund["fund_code"], code, key)

        # summary 必须能由 entries 独立复算（不依赖生成器内部意图）
        recomputed = {"新进": 0, "退出": 0, "加仓": 0, "减仓": 0, "不变": 0, "待确认": 0}
        for entry in fund["entries"]:
            recomputed[entry["status"]] += 1
        assert fund["summary"] == recomputed, fund["fund_code"]


def test_events_truth_matches_inputs():
    truth = _read(FIXTURES / "truth" / "events_truth.json")
    for fund in truth["funds"]:
        events = _read(FIXTURES / fund["inputs"]["events"])
        actual_classes = [item["change_class"] for item in events["managers"]]
        expected_classes = [item["change_class"] for item in fund["managers"]]
        assert actual_classes == expected_classes, fund["fund_code"]
        for key, value in fund["scale"].items():
            assert events["scale"][key] == value, (fund["fund_code"], key)


def test_coverage_matrix_is_complete():
    coverage = _read(FIXTURES / "truth" / "coverage.json")
    assert coverage["note"] == "抽样覆盖、非穷举"
    required = {
        "holding_change": {"新进", "退出", "加仓", "减仓", "不变"},
        "manager": {"in_period", "prior_period", "none", "unparsed"},
        "scale": {"正常变动", "no_prev_baseline", "零申赎"},
        "fund_type": {"股票型", "混合型", "ETF联接", "QDII"},
        "anomaly": {"ratio_null", "invalid_stock_code", "change_type_missing",
                    "page_parse_failed", "network_failed"},
        "disclosure": {"已披露", "待披露", "无数据"},
    }
    for dimension, values in required.items():
        entry = coverage["dimensions"][dimension]
        assert entry["note"].startswith("抽样覆盖、非穷举")
        assert entry["total"] == entry["sampled"]
        for value in values:
            item = entry["items"][value]
            assert item["total"] >= 1
            assert item["sampled"] >= 1


def test_tampered_fixture_fails_check(tmp_path):
    fixture_dir = tmp_path / "fixtures"
    shutil.copytree(FIXTURES, fixture_dir)
    path = fixture_dir / "q2026q3" / "holdings" / "990001.json"
    payload = _read(path)
    payload["rows"][0]["ratio"] = "9.99"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")

    proc = _run("--out", str(fixture_dir), "--check")
    assert proc.returncode == 1
    stderr = proc.stderr.decode("utf-8", "replace")
    assert "SHA256" in stderr or "字节不一致" in stderr


def test_q3_disclosure_snapshot_and_history():
    snapshot = eid.load_disclosure(DATA_DIR, period="2026Q3")
    assert snapshot["available"] is True
    assert snapshot["snapshot"].replace("\\", "/").endswith("q2026q3/disclosure.json")
    reports = snapshot["reports"]
    assert len(reports) == 7
    first = [item for item in reports if item["fundcode"] == "990001"][0]
    assert first["report_period"] == "2026Q3"  # 仅靠标题解析
    assert first["report_send_date"] == "2026-10-20"

    assert window.disclosure_status(
        True, reports, "990001", "2026Q3", as_of="2026-10-19") == window.STATUS_PENDING
    assert window.disclosure_status(
        True, reports, "990001", "2026Q3", as_of="2026-10-20") == window.STATUS_DISCLOSED
    assert window.disclosure_status(
        True, reports, "990008", "2026Q3", as_of="2026-10-31") == window.STATUS_PENDING


def test_disclosure_snapshots_cover_three_states():
    q2 = eid.load_disclosure(DATA_DIR, period="2026Q2")
    q3 = eid.load_disclosure(DATA_DIR, period="2026Q3")
    aggregate = eid.load_disclosure(DATA_DIR)
    unavailable = eid.load_disclosure(
        DATA_DIR, path=str(FIXTURES / "disclosure_unavailable.json"))

    assert q2["available"] and len(q2["reports"]) == 8
    assert q3["available"] and len(q3["reports"]) == 7
    assert aggregate["available"] and len(aggregate["reports"]) == 15
    assert unavailable["available"] is False
    assert unavailable["reason"] == "synthetic_network_failure"
    assert window.disclosure_status(
        unavailable["available"], unavailable["reports"], "990001", "2026Q3"
    ) == window.STATUS_NO_DATA


def test_quarter_snapshot_falls_back_to_aggregate(tmp_path):
    data_dir = tmp_path / "data"
    shutil.copytree(FIXTURES, data_dir / "fixtures")
    (data_dir / "fixtures" / "q2026q3" / "disclosure.json").unlink()

    snapshot = eid.load_disclosure(data_dir, period="2026Q3")
    assert snapshot["available"] is True
    assert snapshot["snapshot"].replace("\\", "/").endswith("fixtures/disclosure.json")
    assert len(snapshot["reports"]) == 15


def test_missing_snapshot_is_no_data(tmp_path):
    snapshot = eid.load_disclosure(tmp_path, period="2026Q3")
    assert snapshot["available"] is False
    assert snapshot["reason"] == "snapshot_missing"
