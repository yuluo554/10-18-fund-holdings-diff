import json
import pathlib

import pytest

from funddiff import compliance

DATA_DIR = pathlib.Path(__file__).resolve().parents[1] / "data"


@pytest.fixture(scope="module")
def terms():
    from funddiff import config as config_module
    return config_module.load_config(DATA_DIR)["compliance"]["forbidden_terms"]


def test_neutral_text_has_no_hits(terms):
    assert compliance.scan_text("本季度持仓发生变化，详见明细。", terms) == []


def test_hit_reports_line_and_term(terms):
    text = "第一行正常\n第二行含" + terms[0] + "表述"
    hits = compliance.scan_text(text, terms)
    assert hits and hits[0]["line"] == 2 and hits[0]["term"] == terms[0]


def test_matching_is_case_and_width_insensitive():
    term = "ABC"
    assert compliance.scan_text("ａｂｃ", [term])


def test_whitespace_is_folded():
    term = "跟随基金经理"
    assert compliance.scan_text("跟随 基金 经理", [term])


def test_empty_terms_is_noop(terms):
    assert compliance.scan_text("任意文本", []) == []


def test_scan_files_skips_missing(tmp_path):
    target = tmp_path / "r.md"
    target.write_text("中性文本", encoding="utf-8")
    results = compliance.scan_files([str(target), str(tmp_path / "missing.md")], ["中性"])
    assert str(target) in results
    assert len(results) == 1


def test_format_hits_is_stable(tmp_path):
    target = tmp_path / "r.md"
    target.write_text("x", encoding="utf-8")
    results = {str(target): [{"line": 1, "term": "x", "excerpt": "x"}]}
    assert compliance.format_hits(results) == ["%s:1:x" % target]
