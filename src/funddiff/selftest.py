"""自检（可证伪）。

设计原则：
- 每项检查都必须能"被弄坏后变红"（假门禁令）；
- 不触碰用户真实清单：store 检查一律在临时目录里做；
- 依赖尚未落盘的数据资产时记 skipped（不是 pass），并在输出里写明原因。
"""

import datetime
import tempfile
from pathlib import Path

from . import compliance, config as config_module, frozen, serialize, store, window

CONFIG_MANIFEST_SCHEMA = "funddiff/config-manifest@1"
FIXTURES_MANIFEST_SCHEMA = "funddiff/fixtures-manifest@1"

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"


def _check(name, fn):
    try:
        ok, detail = fn()
    except Exception as exc:  # 自检必须"永不崩"，异常记 FAIL
        return {"name": name, "status": FAIL, "detail": "%s: %s" % (type(exc).__name__, exc)}
    if ok is None:
        return {"name": name, "status": SKIP, "detail": detail}
    return {"name": name, "status": PASS if ok else FAIL, "detail": detail}


def _check_config(config):
    try:
        config_module.validate_config(config)
    except config_module.ConfigError as exc:
        return False, str(exc)
    return True, "必需键齐全；diff.mode=%s" % config["diff"]["mode"]


def _check_determinism():
    payload = {"b": [1, 2], "a": {"y": None, "x": "中文"}}
    first = serialize.dumps(payload)
    second = serialize.dumps(payload)
    if first != second:
        return False, "同输入两次序列化不一致"
    if not first.endswith("\n") or "\r" in first:
        return False, "序列化未以单个 LF 结尾"
    if "\\u4e2d" in first:
        return False, "中文被转义（ensure_ascii 未关闭）"
    return True, "sort_keys / ensure_ascii=False / LF 结尾"


def _check_atomic_write():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "nested" / "probe.json"
        serialize.write_json(target, {"k": "v"})
        if not target.is_file():
            return False, "原子写未产出文件"
        leftovers = [item.name for item in target.parent.iterdir() if item.name != "probe.json"]
        if leftovers:
            return False, "临时文件残留：%s" % ", ".join(sorted(leftovers))
    return True, "写临时文件 + os.replace，无残留"


def _check_store_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "watchlist.json"
        watchlist = store.Watchlist(path)
        watchlist.add("990001", name="样例甲", today="2026-10-18")
        watchlist.add("990001", name="样例甲", today="2026-10-18")
        watchlist.add("990002", today="2026-10-18")
        entries = watchlist.list_all()
        if len(entries) != 2:
            return False, "重复添加产生了重复条目（%d 条）" % len(entries)
        if [item["code"] for item in entries] != ["990001", "990002"]:
            return False, "清单未按代码升序"
        if not watchlist.remove("990002"):
            return False, "remove 未生效"
        if watchlist.remove("990002"):
            return False, "重复 remove 应返回 False"
    return True, "幂等添加 / 升序 / 删除谓词"


def _check_window(config):
    cases = [
        ("2026-10-18", "2026Q3"),
        ("2026-09-30", "2026Q3"),
        ("2026-09-29", "2026Q2"),
        ("2026-01-05", "2025Q4"),
    ]
    for as_of, expected in cases:
        info, _ = window.resolve_window(config, as_of)
        if info["report_period"] != expected:
            return False, "%s 应属 %s，实际 %s" % (as_of, expected, info["report_period"])
    info, _ = window.resolve_window(config, "2026-10-18")
    if info["period_start"] != "2026-07-01" or info["period_end"] != "2026-09-30":
        return False, "报告期起止不符：%s ~ %s" % (info["period_start"], info["period_end"])
    if info["as_of"] != "2026-10-18":
        return False, "as_of 未回显"
    return True, "季度映射 / 报告期起止 / as_of 回显"


def _check_disclosure_snapshot(data_dir):
    from . import eid

    disclosure = eid.load_disclosure(data_dir)
    if not disclosure["available"]:
        return None, "披露快照不可用（%s），M1 落地后启用" % disclosure["reason"]
    if not disclosure["reports"]:
        return False, "披露快照存在但没有可解析记录"
    return True, "%d 条披露元数据（合成快照）" % len(disclosure["reports"])


def _check_config_manifest(data_dir, config):
    manifest_path = Path(data_dir) / "config" / frozen.MANIFEST_NAME
    if not manifest_path.is_file():
        return False, "配置 MANIFEST 缺失：%s" % manifest_path
    try:
        manifest = serialize.read_json(manifest_path)
    except (OSError, ValueError) as exc:
        return False, "配置 MANIFEST 不可读：%s" % exc
    problems = frozen.verify_manifest(
        Path(data_dir) / "config", manifest, CONFIG_MANIFEST_SCHEMA)
    if manifest.get("config_version") != config.get("config_version"):
        problems.append("config_version 与 app.json 不一致")
    if problems:
        return False, "; ".join(problems[:3])
    return True, "%d 个配置文件与 SHA256 一致" % len(manifest.get("files", {}))


def _check_fixtures_manifest(data_dir):
    manifest_path = Path(data_dir) / "fixtures" / frozen.MANIFEST_NAME
    if not manifest_path.is_file():
        return False, "fixtures MANIFEST 缺失：%s" % manifest_path
    try:
        manifest = serialize.read_json(manifest_path)
    except (OSError, ValueError) as exc:
        return False, "fixtures MANIFEST 不可读：%s" % exc
    problems = frozen.verify_manifest(
        Path(data_dir) / "fixtures", manifest, FIXTURES_MANIFEST_SCHEMA)
    if manifest.get("sample") != "synthetic":
        problems.append("MANIFEST.sample 必须为 synthetic")
    if manifest.get("rng") != "splitmix64":
        problems.append("MANIFEST.rng 必须为 splitmix64")
    if not isinstance(manifest.get("seed"), int):
        problems.append("MANIFEST.seed 必须是整数")
    if problems:
        return False, "; ".join(problems[:3])
    return True, "%d 个合成文件与 SHA256 一致" % len(manifest.get("files", {}))


def _check_compliance(config):
    terms = config["compliance"]["forbidden_terms"]
    hits = compliance.scan_text("完全中性的句子。", terms)
    if hits:
        return False, "中性文本被误报：%s" % hits[0]["term"]
    # 用配置里的词构造阳性对照：词面来自配置，代码不内嵌
    probe = "这句话包含 " + terms[0] + " 这一表述。"
    hits = compliance.scan_text(probe, terms)
    if not hits or hits[0]["term"] != terms[0]:
        return False, "阳性对照未命中（词表扫描未生效）"
    return True, "阴性无命中 / 阳性可命中"


def _check_store_no_side_effects():
    """读清单不得创建文件或目录（否则"看一眼"就会污染工作目录）。

    这是真断言：路径指向一个不存在的嵌套目录，读完后仍必须不存在。
    """
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "nested" / "deep" / "watchlist.json"
        entries = store.Watchlist(target).list_all()
        if entries:
            return False, "空路径读出了条目"
        if target.exists():
            return False, "读取操作创建了清单文件"
        if target.parent.exists():
            return False, "读取操作创建了清单目录"
    return True, "读取零副作用（不建文件、不建目录）"


def run(data_dir, config=None, store_file=None):
    """data_dir 可为 None：此时只跑与数据目录无关的检查，并记一条 FAIL。

    这是"可证伪"的落点：数据根不可用时 selftest 必须给非零，而不是静默通过。
    """
    checks = []
    if config is None and data_dir is not None:
        try:
            config = config_module.load_config(data_dir)
        except config_module.ConfigError as exc:
            checks.append({"name": "config.load", "status": FAIL, "detail": str(exc)})
            config = None
    elif config is None:
        checks.append({
            "name": "config.load",
            "status": FAIL,
            "detail": "数据目录不可用（缺少 config/app.json）",
        })

    if config is not None:
        checks.append(_check("config.validate", lambda: _check_config(config)))
        checks.append(_check(
            "config.manifest",
            lambda: _check_config_manifest(data_dir, config) if data_dir else (None, "数据目录不可用"),
        ))
        checks.append(_check(
            "fixtures.manifest",
            lambda: _check_fixtures_manifest(data_dir) if data_dir else (None, "数据目录不可用"),
        ))
    checks.extend([
        _check("serialize.determinism", _check_determinism),
        _check("serialize.atomic_write", _check_atomic_write),
        _check("store.roundtrip", _check_store_roundtrip),
    ])
    if config is not None:
        checks.append(_check("window.quarters", lambda: _check_window(config)))
    checks.append(
        _check("disclosure.snapshot",
               lambda: _check_disclosure_snapshot(data_dir) if data_dir else (None, "数据目录不可用"))
    )
    if config is not None:
        checks.append(_check("compliance.terms", lambda: _check_compliance(config)))
    checks.append(_check("store.no_side_effects", _check_store_no_side_effects))

    failed = sum(1 for item in checks if item["status"] == FAIL)
    skipped = sum(1 for item in checks if item["status"] == SKIP)
    return {
        "schema": "funddiff/selftest@1",
        "ok": failed == 0,
        "failed": failed,
        "skipped": skipped,
        "checks": checks,
    }
