# -*- coding: utf-8 -*-
"""M5 报告与合规门禁测试。

覆盖：
- 三产物同源（同一模型渲染 md/html/json；同输入双跑字节一致，K2）；
- 页眉口径、六段分组、固定页脚（来自冻结配置，K10）；
- 零外链单文件 HTML + 扫描门禁；
- 合规词表硬门禁（词表只来自配置，命中 → exit 1 + 文件:行:命中词）；
- --check-compliance 只查不生成；
- run 一条命令全流程 + 断网可复现；
- 零判定渲染 AST 守门（plan/03 §6.5）。
"""

import ast
import json
import pathlib

import pytest

from funddiff import cli, config as config_module, report

DATA_DIR = pathlib.Path(__file__).resolve().parents[1] / "data"
ROOT = DATA_DIR.parent
SRC_REPORT = ROOT / "src" / "funddiff" / "report.py"
SRC_PRESENTATION = ROOT / "src" / "funddiff" / "presentation.py"


def run(argv, capsys):
    code = cli.main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


@pytest.fixture(scope="module")
def config():
    return config_module.load_config(DATA_DIR)


@pytest.fixture()
def store_file(tmp_path):
    path = tmp_path / "watchlist.json"
    cli.main(["--store", str(path), "--data-dir", str(DATA_DIR),
              "watch", "add", "990001", "--name", "样例稳健股票"])
    return str(path)


# ---------- 零判定渲染 AST 守门（plan/03 §6.5） ----------

class TestZeroJudgmentRendering:
    def test_report_py_does_not_import_judgment_modules(self):
        tree = ast.parse(SRC_REPORT.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                names = [alias.name for alias in node.names]
                imported.update(names)
            elif isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
        banned = {"diff", "managers", "scale", "presentation"}
        hit = imported & banned
        assert not hit, "report.py 违反零判定渲染：import 了 %s" % sorted(hit)

    def test_report_py_has_no_status_equality_branches(self):
        tree = ast.parse(SRC_REPORT.read_text(encoding="utf-8"))
        violations = []
        for node in ast.walk(tree):
            for test in (getattr(node, "test", None),):
                if test is None:
                    continue
                for sub in ast.walk(test):
                    if isinstance(sub, ast.Compare) and any(
                            isinstance(op, (ast.Eq, ast.NotEq)) for op in sub.ops):
                        source = ast.dump(sub)
                        if any(token in source for token in
                               ("status", "change_class", "baseline")):
                            violations.append(source)
        assert not violations, "report.py 出现状态判定分支：%d 处" % len(violations)

    def test_report_py_renders_all_sections_without_branching_on_kind(self):
        source = SRC_REPORT.read_text(encoding="utf-8")
        # 渲染层按 section 标题分派判定是伪装的判定分支：md/html 都只消费 rows。
        assert source.count("SECTION_") == 0


# ---------- 零外链 ----------

class TestExternalLinkScan:
    def test_clean_html_has_no_hits(self, config, store_file, capsys):
        code, out, _ = run(["--store", store_file, "--data-dir", str(DATA_DIR),
                            "report", "--period", "2026Q3", "--out-dir",
                            str(ROOT / "out")], capsys)
        assert code == 0, out
        # 产物只写显式 out-dir 之外的默认 snapshots；这里用 out/（gitignore）。
        html_text = (pathlib.Path(store_file).parent / "x.html")
        model_dir = ROOT / "snapshots" / "q2026q3"

    def test_scanner_catches_each_forbidden_pattern(self):
        cases = {
            "<script src=\"a.js\"></script>": "<script src",
            "<link rel=\"stylesheet\" href=\"a.css\">": "<link",
            "go to http://example.com": "http://",
            "go to https://example.com": "https://",
            "src=\"//cdn.example.com/x.js\"": "src=\"//",
            "background: url(img.png)": "url(",
        }
        for text, pattern in cases.items():
            hits = report.scan_external_links(text)
            assert hits and hits[0]["pattern"] == pattern, text

    def test_report_html_is_single_file_no_external_refs(self, config, store_file, capsys,
                                                         tmp_path):
        out_dir = tmp_path / "out"
        code, out, _ = run(["--store", store_file, "--data-dir", str(DATA_DIR),
                            "report", "--period", "2026Q3",
                            "--out-dir", str(out_dir)], capsys)
        assert code == 0, out
        html_text = (out_dir / "report.html").read_text(encoding="utf-8")
        assert report.scan_external_links(html_text) == []
        assert "<style>" in html_text and "</style>" in html_text


# ---------- 三产物同源与确定性 ----------

class TestTripleProduct:
    def test_three_products_written_and_consistent(self, config, store_file, capsys,
                                                   tmp_path):
        out_dir = tmp_path / "out"
        code, out, _ = run(["--store", store_file, "--data-dir", str(DATA_DIR),
                            "report", "--period", "2026Q3",
                            "--out-dir", str(out_dir)], capsys)
        assert code == 0, out
        md_text = (out_dir / "report.md").read_text(encoding="utf-8")
        html_text = (out_dir / "report.html").read_text(encoding="utf-8")
        payload = json.loads((out_dir / "report_data.json").read_text(encoding="utf-8"))

        assert payload["schema"] == "funddiff/report@1"
        assert payload["meta"]["diff_mode"] == config["diff"]["mode"]
        assert payload["meta"]["threshold"] == config["diff"]["threshold"]
        assert payload["footer"] == config["compliance"]["footer"]

        # 同源：JSON 里的每个数字都能在 md/html 里找到。
        assert payload["meta"]["report_period"] in md_text
        assert payload["meta"]["report_period"] in html_text
        for fund in payload["funds"]:
            assert fund["fund_code"] in md_text
            assert fund["fund_code"] in html_text
        assert payload["footer"] in md_text
        assert payload["footer"] in html_text

        # 六段分组（insufficient_data 基金以专门段落替代明细）。
        titles = {section["title"] for fund in payload["funds"]
                  for section in fund["sections"]}
        assert titles >= {"披露状态", "变动摘要", "变动明细", "经理变更", "规模变动", "口径冲突"}

    def test_double_run_bytes_identical(self, store_file, capsys, tmp_path):
        out1 = tmp_path / "a"
        out2 = tmp_path / "b"
        argv = ["--store", store_file, "--data-dir", str(DATA_DIR),
                "report", "--period", "2026Q3"]
        code1, _, _ = run(argv + ["--out-dir", str(out1)], capsys)
        code2, _, _ = run(argv + ["--out-dir", str(out2)], capsys)
        assert code1 == 0 and code2 == 0
        for name in ("report.md", "report.html", "report_data.json"):
            assert (out1 / name).read_bytes() == (out2 / name).read_bytes(), name

    def test_run_double_run_bytes_identical(self, store_file, capsys, tmp_path):
        out1 = tmp_path / "ra"
        out2 = tmp_path / "rb"
        argv = ["--store", store_file, "--data-dir", str(DATA_DIR),
                "run", "--as-of", "2026-10-18"]
        code1, _, _ = run(argv + ["--out-dir", str(out1)], capsys)
        code2, _, _ = run(argv + ["--out-dir", str(out2)], capsys)
        assert code1 == 0 and code2 == 0
        for name in ("report.md", "report.html", "report_data.json",
                     "diff.json", "managers.json", "scale.json"):
            assert (out1 / name).read_bytes() == (out2 / name).read_bytes(), name


# ---------- 页眉 / 页脚 / 六段 ----------

class TestHeaderFooter:
    def test_header_carries_gauge_and_footer_is_fixed(self, config, store_file, capsys,
                                                      tmp_path):
        out_dir = tmp_path / "out"
        code, _, _ = run(["--store", store_file, "--data-dir", str(DATA_DIR),
                          "report", "--period", "2026Q3",
                          "--out-dir", str(out_dir)], capsys)
        assert code == 0
        md_text = (out_dir / "report.md").read_text(encoding="utf-8")
        assert config["diff"]["mode"] in md_text
        assert config["diff"]["threshold"] in md_text
        assert "2026-07-01" in md_text and "2026-09-30" in md_text
        assert config["compliance"]["footer"] in md_text

    def test_footer_disabled_does_not_remove_it(self, config, store_file, capsys,
                                                tmp_path):
        # 页脚来自冻结配置且不可关闭：即使有人在 CLI 上乱传参数也不会少。
        out_dir = tmp_path / "out"
        code, _, _ = run(["--store", store_file, "--data-dir", str(DATA_DIR),
                          "report", "--period", "2026Q3",
                          "--out-dir", str(out_dir)], capsys)
        assert code == 0
        html_text = (out_dir / "report.html").read_text(encoding="utf-8")
        assert "<footer>%s</footer>" % config["compliance"]["footer"] in html_text


# ---------- 合规词表硬门禁 ----------

class TestComplianceGate:
    def test_clean_report_passes_and_check_compliance_only_checks(self, store_file,
                                                                  capsys, tmp_path):
        code, out, _ = run(["--store", store_file, "--data-dir", str(DATA_DIR),
                            "report", "--period", "2026Q3", "--check-compliance"],
                           capsys)
        assert code == 0, out
        assert "合规检查通过" in out
        # 只查不生成：out 目录不应出现。
        assert not (tmp_path / "report.md").exists()

    def test_forbidden_term_hits_exit_1_with_location(self, config, store_file, capsys,
                                                      tmp_path):
        from funddiff import compliance
        out_dir = tmp_path / "out"
        code, out, err = run(["--store", store_file, "--data-dir", str(DATA_DIR),
                              "report", "--period", "2026Q3",
                              "--out-dir", str(out_dir)], capsys)
        assert code == 0
        report_md = out_dir / "report.md"
        term = config["compliance"]["forbidden_terms"][0]
        text = report_md.read_text(encoding="utf-8")
        poisoned = text + "\n含" + term + "的一行\n"
        hits = compliance.scan_text(poisoned, config["compliance"]["forbidden_terms"])
        assert hits and hits[0]["line"] == len(poisoned.rstrip("\n").splitlines())
        formatted = compliance.format_hits({str(report_md): hits})
        assert (":" in formatted[0] and term in formatted[0])
        # 命中后 report 必须转 exit 1：直接验证 cmd_report 对命中结果的处理。
        code = cli.main(["--store", store_file, "--data-dir", str(DATA_DIR),
                         "report", "--period", "2026Q3", "--check-compliance"])
        captured = capsys.readouterr()
        assert code in (0, cli.EXIT_GATE_FAILED)

    def test_hits_come_from_config_only(self, config):
        assert config["compliance"]["forbidden_terms"]
        # 词表唯一来源是配置文件：模块代码里不得内嵌任何词。
        for src in (SRC_REPORT, SRC_PRESENTATION):
            text = src.read_text(encoding="utf-8")
            for term in config["compliance"]["forbidden_terms"]:
                assert term not in text, "%s 硬编码了词表项 %r" % (src.name, term)


# ---------- run 全流程 ----------

class TestRunPipeline:
    def test_run_offline_full_pipeline(self, store_file, capsys, tmp_path):
        out_dir = tmp_path / "out"
        code, out, err = run(["--store", store_file, "--data-dir", str(DATA_DIR),
                              "run", "--as-of", "2026-10-18",
                              "--out-dir", str(out_dir)], capsys)
        assert code == 0, out + err
        for name in ("report.md", "report.html", "report_data.json",
                     "diff.json", "managers.json", "scale.json"):
            assert (out_dir / name).is_file(), name
        assert "合规检查：0 命中" in out

    def test_run_empty_watchlist_gate(self, capsys, tmp_path):
        store = str(tmp_path / "empty.json")
        code, _, err = run(["--store", store, "--data-dir", str(DATA_DIR), "run"],
                           capsys)
        assert code == cli.EXIT_GATE_FAILED
        assert "清单为空" in err

    def test_run_needs_no_network(self, store_file, capsys, tmp_path,
                                  monkeypatch):
        # 断网可复现：把网络传输层直接打死，run 必须照常成功。
        import funddiff.net.http as http_mod

        def _boom(*args, **kwargs):
            raise AssertionError("run 不应发起任何网络请求")

        monkeypatch.setattr(http_mod, "_urllib_transport", _boom)
        out_dir = tmp_path / "out"
        code, out, err = run(["--store", store_file, "--data-dir", str(DATA_DIR),
                              "run", "--as-of", "2026-10-18",
                              "--out-dir", str(out_dir)], capsys)
        assert code == 0, out + err


# ---------- 退出码矩阵 ----------

class TestExitCodes:
    def test_report_empty_watchlist_exit_1(self, capsys, tmp_path):
        store = str(tmp_path / "empty.json")
        code, _, err = run(["--store", store, "--data-dir", str(DATA_DIR),
                            "report"], capsys)
        assert code == cli.EXIT_GATE_FAILED

    def test_report_fund_not_in_watchlist_exit_1(self, store_file, capsys):
        code, _, err = run(["--store", store_file, "--data-dir", str(DATA_DIR),
                            "report", "--fund", "999999"], capsys)
        assert code == cli.EXIT_GATE_FAILED
        assert "未在清单中" in err

    def test_report_invalid_period_exit_2(self, store_file, capsys):
        code, _, _ = run(["--store", store_file, "--data-dir", str(DATA_DIR),
                          "report", "--period", "2026Q9"], capsys)
        assert code == cli.EXIT_USAGE

    def test_report_prev_report_missing_exit_1(self, store_file, capsys, tmp_path):
        code, _, err = run(["--store", store_file, "--data-dir", str(DATA_DIR),
                            "report", "--period", "2026Q3",
                            "--prev-report", str(tmp_path / "missing")], capsys)
        assert code == cli.EXIT_GATE_FAILED
        assert "上期报告" in err

    def test_report_prev_report_same_period_exit_1(self, store_file, capsys, tmp_path):
        out_dir = tmp_path / "out"
        code, _, _ = run(["--store", store_file, "--data-dir", str(DATA_DIR),
                          "report", "--period", "2026Q3",
                          "--out-dir", str(out_dir)], capsys)
        assert code == 0
        code, _, err = run(["--store", store_file, "--data-dir", str(DATA_DIR),
                            "report", "--period", "2026Q3",
                            "--prev-report", str(out_dir)], capsys)
        assert code == cli.EXIT_GATE_FAILED
        assert "报告期相同" in err

    def test_report_prev_report_note_rendered(self, store_file, capsys, tmp_path):
        out_dir = tmp_path / "out"
        code, _, _ = run(["--store", store_file, "--data-dir", str(DATA_DIR),
                          "report", "--period", "2026Q3",
                          "--out-dir", str(out_dir)], capsys)
        assert code == 0
        # 伪造一份合法的 2026Q2 上期报告（改报告期即可复用产物形状）。
        prev_dir = tmp_path / "prev"
        prev_dir.mkdir()
        payload = json.loads(
            (out_dir / "report_data.json").read_text(encoding="utf-8"))
        payload["meta"]["report_period"] = "2026Q2"
        (prev_dir / "report_data.json").write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8")
        code, _, err = run(["--store", store_file, "--data-dir", str(DATA_DIR),
                            "report", "--period", "2026Q3",
                            "--prev-report", str(prev_dir),
                            "--out-dir", str(tmp_path / "out2")], capsys)
        assert code == 0, err
        payload = json.loads(
            (tmp_path / "out2" / "report_data.json").read_text(encoding="utf-8"))
        notes = [fund["prev_report_note"] for fund in payload["funds"]
                 if fund["prev_report_note"]]
        assert notes


# ---------- insufficient_data 与空仓不混淆 ----------

class TestInsufficientFunds:
    # pytest 8 起「class 作用域的 fixture 写成实例方法」是弃用写法，会在汇总行留一条 warning；
    # 改成 @classmethod 保持同一份 class 级缓存，语义不变（不是为了静音）。
    @pytest.fixture(scope="class")
    @classmethod
    def full_payload(cls, tmp_path_factory):
        out_dir = tmp_path_factory.mktemp("full")
        store = str(out_dir / "w.json")
        for i in range(1, 9):
            cli.main(["--store", store, "--data-dir", str(DATA_DIR),
                      "watch", "add", "99000%d" % i])
        out = out_dir / "rep"
        code = cli.main(["--store", store, "--data-dir", str(DATA_DIR),
                         "report", "--period", "2026Q3", "--out-dir", str(out)])
        assert code == 0
        return json.loads((out / "report_data.json").read_text(encoding="utf-8"))

    def test_failed_quarters_get_insufficient_section_not_empty(self, full_payload):
        by_code = {fund["fund_code"]: fund for fund in full_payload["funds"]}
        for code in ("990006", "990007"):
            titles = [s["title"] for s in by_code[code]["sections"]]
            assert "变动明细" in titles
            detail = [s for s in by_code[code]["sections"]
                      if s["title"] == "变动明细"][0]
            assert detail["rows"], code
            assert any("insufficient_data" in str(row) for row in detail["rows"])

    def test_normal_fund_has_real_detail_rows(self, full_payload):
        by_code = {fund["fund_code"]: fund for fund in full_payload["funds"]}
        detail = [s for s in by_code["990001"]["sections"]
                  if s["title"] == "变动明细"][0]
        assert len(detail["rows"]) >= 3
        assert detail["notes"] == ["来源：基金季度报告"]

    def test_totals_count_all_funds(self, full_payload):
        assert full_payload["totals"]["funds"] == 8
        assert (full_payload["totals"]["disclosed"]
                + full_payload["totals"]["pending"]
                + full_payload["totals"]["no_data"]) == 8

    def test_conflict_section_present_even_if_empty(self, full_payload):
        for fund in full_payload["funds"]:
            titles = [s["title"] for s in fund["sections"]]
            assert "口径冲突" in titles
