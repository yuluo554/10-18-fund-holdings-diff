"""命令矩阵冒烟：CI 与本地跑同一份。

每个用例声明期望退出码；退出码不符即失败（并打印 stdout/stderr）。
所有临时路径显式传入，绝不污染开发者本机 local_data/。
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
DATA_DIR = ROOT / "data"


def _env():
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(SRC) + (os.pathsep + existing if existing else "")
    env["PYTHONUTF8"] = "1"
    return env


def run(args, expect, label, cwd=None):
    command = [sys.executable, "-m", "funddiff"] + args
    proc = subprocess.run(
        command,
        cwd=str(cwd or ROOT),
        env=_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    out = proc.stdout.decode("utf-8", "replace")
    err = proc.stderr.decode("utf-8", "replace")
    status = "ok" if proc.returncode == expect else "FAIL"
    print("[%s] %s -> exit %d (expected %d)" % (status, label, proc.returncode, expect))
    if status == "FAIL":
        print("  stdout: %s" % out.strip())
        print("  stderr: %s" % err.strip())
    return status == "ok", out, err


def run_tool(script, args, expect, label):
    command = [sys.executable, str(ROOT / "tools" / script)] + args
    proc = subprocess.run(
        command,
        cwd=str(ROOT),
        env=_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    status = "ok" if proc.returncode == expect else "FAIL"
    print("[%s] %s -> exit %d (expected %d)" % (status, label, proc.returncode, expect))
    if status == "FAIL":
        print("  stdout: %s" % proc.stdout.decode("utf-8", "replace").strip())
        print("  stderr: %s" % proc.stderr.decode("utf-8", "replace").strip())
    return proc.returncode == expect


def main():
    failures = 0
    for args, label in ((["--check"], "freeze_config --check"),
                        (["--check"], "gen_fixtures --check")):
        script = "freeze_config.py" if "freeze" in label else "gen_fixtures.py"
        if not run_tool(script, args, 0, label):
            failures += 1

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        store = str(tmp_path / "watchlist.json")
        out_report = str(tmp_path / "out-report")
        out_run = str(tmp_path / "out-run")
        global_args = ["--store", store, "--data-dir", str(DATA_DIR)]

        cases = [
            # fetch 在空清单上：失败隔离前的用法门禁（exit 1），不发任何网络请求
            (["fetch", "--store", str(tmp_path / "empty.json"),
              "--data-dir", str(DATA_DIR)], 1, "fetch empty watchlist", None),
            (["--help"], 0, "help", None),
            (["--version"], 0, "version", None),
            (["--store", store, "--data-dir", str(DATA_DIR), "selftest"], 0, "selftest", None),
            (["watch", "add", "990001", "--name", "样例甲"] + global_args, 0, "watch add", None),
            (["watch", "add", "990001", "--name", "样例甲"] + global_args, 0, "watch add (repeat)", None),
            (["watch", "list"] + global_args, 0, "watch list", None),
            (["watch", "list", "--json"] + global_args, 0, "watch list --json", None),
            (["watch", "remove", "990002"] + global_args, 1, "watch remove absent", None),
            (["watch", "add", "abc"] + global_args, 2, "watch add invalid", None),
            (["watch", "add", "990002", "--name", "样例乙"] + global_args, 0, "watch add 2", None),
            # diff 真实跑：8 只合成基金全加进清单，走完整 Q/Q diff（M3 退役 stub）
            (["watch", "add", "990003", "--name", "样例丙"] + global_args, 0, "watch add 3", None),
            (["watch", "add", "990004", "--name", "样例丁"] + global_args, 0, "watch add 4", None),
            (["watch", "add", "990005", "--name", "样例戊"] + global_args, 0, "watch add 5", None),
            (["watch", "add", "990006", "--name", "样例己"] + global_args, 0, "watch add 6", None),
            (["watch", "add", "990007", "--name", "样例庚"] + global_args, 0, "watch add 7", None),
            (["watch", "add", "990008", "--name", "样例辛"] + global_args, 0, "watch add 8", None),
            (["diff", "--period", "2026Q3", "--json"] + global_args, 0, "diff real run", None),
            (["diff", "--period", "2026Q3"] + global_args, 0, "diff real run (text)", None),
            (["window", "--as-of", "2026-10-18"] + global_args, 0, "window", None),
            (["window", "--as-of", "2026-10-18", "--json"] + global_args, 0, "window --json", None),
            (["window", "--as-of", "2026-13-01"] + global_args, 2, "window invalid date", None),
            # diff 空清单门禁：独立空清单（exit 1），不受上面已加基金的影响
            (["diff", "--store", str(tmp_path / "empty-wl.json"),
              "--data-dir", str(DATA_DIR)], 1, "diff empty watchlist", None),
            (["diff", "--mode", "bogus", "--store", store, "--data-dir", str(DATA_DIR)],
             2, "diff invalid mode", None),
            (["diff", "--period", "2026Q9", "--store", store, "--data-dir", str(DATA_DIR)],
             2, "diff invalid period", None),
            # M4 真实跑：managers / scale 退役 stub（events 合成台账）
            (["managers", "--period", "2026Q3", "--json"] + global_args, 0,
             "managers real run", None),
            (["managers", "--period", "2026Q3"] + global_args, 0,
             "managers real run (text)", None),
            (["scale", "--period", "2026Q3", "--json"] + global_args, 0,
             "scale real run", None),
            (["scale", "--period", "2026Q3"] + global_args, 0,
             "scale real run (text)", None),
            (["managers", "--store", str(tmp_path / "empty-wl2.json"),
              "--data-dir", str(DATA_DIR)], 1, "managers empty watchlist", None),
            (["scale", "--store", str(tmp_path / "empty-wl3.json"),
              "--data-dir", str(DATA_DIR)], 1, "scale empty watchlist", None),
            (["managers", "--period", "2026Q9"] + global_args, 2,
             "managers invalid period", None),
            (["scale", "--period", "2026Q9"] + global_args, 2,
             "scale invalid period", None),
            # M5 真实跑：report 三产物 + 合规/零外链门禁；run 一条命令全流程（离线）
            (["report", "--period", "2026Q3", "--out-dir", out_report,
              "--store", store, "--data-dir", str(DATA_DIR)], 0,
             "report real run", None),
            (["report", "--period", "2026Q3", "--check-compliance",
              "--store", store, "--data-dir", str(DATA_DIR)], 0,
             "report --check-compliance", None),
            (["report", "--period", "2026Q9",
              "--store", store, "--data-dir", str(DATA_DIR)], 2,
             "report invalid period", None),
            (["report", "--store", str(tmp_path / "empty-wl4.json"),
              "--data-dir", str(DATA_DIR)], 1, "report empty watchlist", None),
            (["run", "--as-of", "2026-10-18", "--out-dir", out_run,
              "--store", store, "--data-dir", str(DATA_DIR)], 0,
             "run real run (offline)", None),
            (["run", "--store", str(tmp_path / "empty-wl5.json"),
              "--data-dir", str(DATA_DIR)], 1, "run empty watchlist", None),
        ]

        for args, expect, label, cwd in cases:
            ok, out, err = run(args, expect, label, cwd)
            if not ok:
                failures += 1
            if label == "diff real run" and ok:
                payload = json.loads(out)
                if payload["schema"] != "funddiff/diff@1" or payload["funds"][0]["fund_code"] != "990001":
                    print("[FAIL] diff real run 产物不符")
                    failures += 1
            if label == "managers real run" and ok:
                payload = json.loads(out)
                if payload["schema"] != "funddiff/managers@1":
                    print("[FAIL] managers real run 产物不符")
                    failures += 1
                else:
                    by_code = {fund["fund_code"]: fund for fund in payload["funds"]}
                    classes = {
                        "990002": "in_period", "990004": "prior_period",
                        "990005": "unparsed", "990001": "none"}
                    for code_, expected in classes.items():
                        records = by_code[code_]["managers"]
                        actual = records[0]["change_class"] if records else "none"
                        if actual != expected:
                            print("[FAIL] managers 分类不符：%s %s != %s" % (
                                code_, actual, expected))
                            failures += 1
            if label == "scale real run" and ok:
                payload = json.loads(out)
                if payload["schema"] != "funddiff/scale@1":
                    print("[FAIL] scale real run 产物不符")
                    failures += 1
                else:
                    by_code = {fund["fund_code"]: fund for fund in payload["funds"]}
                    if by_code["990004"]["scale"]["subscribe"] != "0.00" or \
                            by_code["990003"]["scale"]["subscribe"] is not None:
                        print("[FAIL] scale 0/null 区分不符")
                        failures += 1
            if label == "watch list --json" and ok:
                payload = json.loads(out)
                if [item["code"] for item in payload["funds"]] != ["990001"]:
                    print("[FAIL] watch list --json 内容不符：%s" % payload)
                    failures += 1
            if label == "window" and ok:
                for token in ("2026Q3", "已披露", "待披露"):
                    if token not in out:
                        print("[FAIL] window 输出缺少 %r" % token)
                        failures += 1
            if label == "report real run" and ok:
                for name in ("report.md", "report.html", "report_data.json"):
                    if not (Path(out_report) / name).is_file():
                        print("[FAIL] report 缺少 %s" % name)
                        failures += 1
                payload = json.loads(
                    (Path(out_report) / "report_data.json").read_text(
                        encoding="utf-8"))
                if payload["schema"] != "funddiff/report@1":
                    print("[FAIL] report schema 不符")
                    failures += 1
                html_text = (Path(out_report) / "report.html").read_text(
                    encoding="utf-8")
                for pattern in ("<script src", "<link", "http://", "https://",
                                'src="//', "url("):
                    if pattern in html_text.lower():
                        print("[FAIL] report.html 含外链形态 %r" % pattern)
                        failures += 1
            if label == "run real run (offline)" and ok:
                for name in ("report.md", "report.html", "report_data.json",
                             "diff.json", "managers.json", "scale.json"):
                    if not (Path(out_run) / name).is_file():
                        print("[FAIL] run 缺少 %s" % name)
                        failures += 1
                payload = json.loads(
                    (Path(out_run) / "report_data.json").read_text(
                        encoding="utf-8"))
                if payload["totals"]["funds"] != 8:
                    print("[FAIL] run 汇总基金数不符：%r" % payload["totals"])
                    failures += 1

        # 数据目录不可用时 selftest 必须非零（可证伪）；语义是"输入错误"→ exit 2
        ok, _, _ = run(
            ["--store", store, "--data-dir", str(tmp_path / "missing"), "selftest"],
            2, "selftest with broken data dir", None)
        if not ok:
            failures += 1

        # 裸 clone 等价：把清单留在临时目录，仓库内不得出现 local_data
        if (ROOT / "local_data").exists():
            print("[FAIL] 冒烟污染了仓库 local_data/")
            failures += 1

    print("ci_smoke: %s (%d failure(s))" % ("PASS" if failures == 0 else "FAIL", failures))
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
