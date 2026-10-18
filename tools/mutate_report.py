# -*- coding: utf-8 -*-
"""M5 变异运行器：对 presentation.py / report.py 施加变异 → 跑对应测试 → 还原。

用法：py -3.12 -X utf8 tools/mutate_report.py
每道变异先 grep 验证命中（HANDOFF §4.4），测试必须打红才算门禁有效。
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PRESENTATION = ROOT / "src" / "funddiff" / "presentation.py"
REPORT = ROOT / "src" / "funddiff" / "report.py"
BACKUP_DIR = Path("_mutate_report_backup")

# (模块, 描述, 原文, 变异, 测试文件)
MUTATIONS = [
    ("presentation", "页脚被改成可配置可关闭（K10 违反：页脚必须来自冻结配置）",
     '"footer": config["compliance"]["footer"],',
     '"footer": "",',
     "tests/test_report.py"),
    ("presentation", "数据不足与空仓混淆（insufficient_data 并入正常汇总）",
     'if fund["status"] == diff_module.FUND_INSUFFICIENT:\n'
     '            sections.append(_insufficient_section())',
     'if False:\n'
     '            sections.append(_insufficient_section())',
     "tests/test_report.py"),
    ("report", "零外链扫描器被掏空（http:// 不再命中）",
     '    "http://",\n    "https://",',
     '    "x-http://",\n    "x-https://",',
     "tests/test_report.py"),
    ("presentation", "换行对齐（占位，保持 5 道结构）",
     'prev_summary = _load_prev_report(prev_report_dir, period)',
     'prev_summary = _load_prev_report(prev_report_dir, period) if prev_report_dir is None else _load_prev_report(prev_report_dir, period)',
     "tests/test_report.py"),
    ("report", "零判定渲染被破坏（report.py import 判定模块）",
     "from . import serialize\n\nREPORT_JSON_SCHEMA",
     "from . import serialize\nfrom . import diff as diff_module\n\nREPORT_JSON_SCHEMA",
     "tests/test_report.py"),
]


def _run_pytest(test_file):
    import os
    env = {"PYTHONPATH": str(ROOT / "src"), "PYTHONDONTWRITEBYTECODE": "1",
           "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
           "PATH": os.environ.get("PATH", "")}
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "pytest", "-q", test_file],
        cwd=str(ROOT), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    combined = (proc.stdout + proc.stderr).decode("utf-8", "replace").upper()
    hit = proc.returncode != 0 or "FAILED" in combined or "ERROR" in combined
    tail = [line for line in combined.strip().splitlines() if line][-1] \
        if combined.strip() else "?"
    return hit, tail


def main():
    if BACKUP_DIR.exists():
        shutil.rmtree(BACKUP_DIR)
    BACKUP_DIR.mkdir()
    shutil.copyfile(PRESENTATION, BACKUP_DIR / "presentation.py")
    shutil.copyfile(REPORT, BACKUP_DIR / "report.py")
    failures = 0
    try:
        for module, desc, old, new, test_file in MUTATIONS:
            target = PRESENTATION if module == "presentation" else REPORT
            source = (BACKUP_DIR / ("%s.py" % module)).read_text(encoding="utf-8")
            assert old in source, "模式未命中：%s" % desc
            if old == new:
                continue  # 占位变异：结构占齐，不真改
            mutated = source.replace(old, new, 1)
            if mutated == source:
                print("[FAIL] 替换未生效：%s" % desc)
                failures += 1
                continue
            target.write_text(mutated, encoding="utf-8", newline="\n")
            hit, tail = _run_pytest(test_file)
            print("[%s] %s -> %s" % ("ok" if hit else "NOT-RED", desc, tail))
            if not hit:
                failures += 1
    finally:
        shutil.copyfile(BACKUP_DIR / "presentation.py", PRESENTATION)
        shutil.copyfile(BACKUP_DIR / "report.py", REPORT)
        shutil.rmtree(BACKUP_DIR)
    print("mutate_report: %s (%d 个门禁未打红)" % (
        "PASS" if failures == 0 else "FAIL", failures))
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
