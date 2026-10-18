# -*- coding: utf-8 -*-
"""变异运行器：对 diff.py 施加一处变异 → 跑 test_diff.py → 还原。

用法：py -3.12 -X utf8 tools/mutate_diff.py
每道变异先 grep 验证命中（HANDOFF §4.4），测试必须打红才算门禁有效。
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src" / "funddiff" / "diff.py"
BACKUP = Path("_mutate_backup_diff.py")

MUTATIONS = [
    ("缺失当0（K3 违反）",
     "elif prev_ratio is None or cur_ratio is None:",
     "elif False:"),
    ("冲突清单静默跳过（不合并承诺失效）",
     "if provider_label is not None and provider_label != status:",
     "if False:"),
    ("失败季不标 insufficient_data（与空仓混淆）",
     'if prev_status == "failed" or cur_status == "failed":',
     "if False:"),
    ("排序倒置（K2 确定性/降序破坏）",
     "return (1, Decimal(0)) if ratio is None else (0, -Decimal(str(ratio)))",
     "return (0, Decimal(0)) if ratio is None else (0, Decimal(str(ratio)))"),
    ("阈值硬编码绕过冻结配置（K10 违反）",
     'threshold = parse_ratio(config["diff"]["threshold"], "diff.threshold")',
     'threshold = Decimal("0.001")'),
]


def main():
    shutil.copyfile(TARGET, BACKUP)
    failures = 0
    try:
        for desc, old, new in MUTATIONS:
            source = BACKUP.read_text(encoding="utf-8")
            assert old in source, "模式未命中：%s" % desc
            TARGET.write_text(source.replace(old, new), encoding="utf-8", newline="\n")
            mutated = TARGET.read_text(encoding="utf-8")
            if new not in mutated:
                print("[FAIL] 变异未生效：%s" % desc)
                failures += 1
                continue
            proc = subprocess.run(
                [sys.executable, "-X", "utf8", "-m", "pytest", "-q",
                 "tests/test_diff.py"],
                cwd=str(ROOT),
                env={"PYTHONPATH": str(ROOT / "src"), "PYTHONDONTWRITEBYTECODE": "1",
                     "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", ""),
                     "PATH": __import__("os").environ.get("PATH", "")},
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            combined = (proc.stdout + proc.stderr).decode("utf-8", "replace").upper()
            # 变异有效 = 测试打红（FAILED 行或 failed/error 计数）
            hit = proc.returncode != 0 or "FAILED" in combined or "ERROR" in combined
            tail = [line for line in combined.strip().splitlines() if line][-1] \
                if combined.strip() else "?"
            print("[%s] %s -> %s" % ("ok" if hit else "FAIL", desc, tail))
            if not hit:
                failures += 1
    finally:
        shutil.copyfile(BACKUP, TARGET)
        BACKUP.unlink()
    print("mutate_diff: %s (%d 个门禁未打红)" % ("PASS" if failures == 0 else "FAIL", failures))
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
