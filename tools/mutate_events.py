# -*- coding: utf-8 -*-
"""M4 变异运行器：对 managers.py / scale.py 施加变异 → 跑对应测试 → 还原。

用法：py -3.12 -X utf8 tools/mutate_events.py
每道变异先 grep 验证命中（HANDOFF §4.4），测试必须打红才算门禁有效。
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

MANAGERS = ROOT / "src" / "funddiff" / "managers.py"
SCALE = ROOT / "src" / "funddiff" / "scale.py"
BACKUP_DIR = Path("_mutate_events_backup")

# (模块, 描述, 原文, 变异, 测试文件)
MUTATIONS = [
    ("managers", "本季内区间硬编码（K10 违反：绕过冻结配置）",
     'if current["period_start"] <= day <= current["period_end"]:',
     "if True:",
     "tests/test_managers.py"),
    ("managers", "unparsed 快照留证被丢弃（不猜承诺失效）",
     '"raw_text": text,\n        "snapshot": _snapshot(text),',
     '"raw_text": "",\n        "snapshot": {"kind": "page_text", '
     '"raw_text": "", "sha256": "0" * 64},',
     "tests/test_managers.py"),
    ("managers", "区间外历史记录被误标 in_period（混淆变更与历史）",
     "    return None\n\n\ndef _snapshot(raw_text):",
     '    return CLASS_IN_PERIOD\n\n\ndef _snapshot(raw_text):',
     "tests/test_managers.py"),
    ("scale", "缺失补 0（K3 违反：null ≠ 0）",
     '    if text in _MISSING:\n        return None',
     '    if text in _MISSING:\n        return "0.00"',
     "tests/test_scale.py"),
    ("scale", "单位硬编码不读表头（K10 违反）",
     '    unit = match.group(1).strip()\n    return unit or None',
     '    return "亿份"',
     "tests/test_scale.py"),
]


def _run_pytest(test_file):
    env = {"PYTHONPATH": str(ROOT / "src"), "PYTHONDONTWRITEBYTECODE": "1",
           "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", ""),
           "PATH": __import__("os").environ.get("PATH", "")}
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
    shutil.copyfile(MANAGERS, BACKUP_DIR / "managers.py")
    shutil.copyfile(SCALE, BACKUP_DIR / "scale.py")
    failures = 0
    try:
        for module, desc, old, new, test_file in MUTATIONS:
            target = MANAGERS if module == "managers" else SCALE
            source = (BACKUP_DIR / ("%s.py" % module)).read_text(encoding="utf-8")
            assert old in source, "模式未命中：%s" % desc
            target.write_text(source.replace(old, new), encoding="utf-8", newline="\n")
            mutated = target.read_text(encoding="utf-8")
            if new not in mutated:
                print("[FAIL] 变异未生效：%s" % desc)
                failures += 1
                continue
            hit, tail = _run_pytest(test_file)
            print("[%s] %s -> %s" % ("ok" if hit else "FAIL", desc, tail))
            if not hit:
                failures += 1
    finally:
        shutil.copyfile(BACKUP_DIR / "managers.py", MANAGERS)
        shutil.copyfile(BACKUP_DIR / "scale.py", SCALE)
        shutil.rmtree(BACKUP_DIR)
    print("mutate_events: %s (%d 个门禁未打红)" % (
        "PASS" if failures == 0 else "FAIL", failures))
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
