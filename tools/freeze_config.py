"""冻结配置包：生成 / 校验 data/config/MANIFEST.json。

用法：
  py -3.12 -X utf8 tools/freeze_config.py            # 生成（改配置后必须重跑）
  py -3.12 -X utf8 tools/freeze_config.py --check    # 校验；不一致 exit 1

纪律：MANIFEST 是生成物，禁止手改；配置目录里的每个 JSON（除 MANIFEST 自身）
都必须登记 SHA256，任何未登记文件都算漂移。
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from funddiff import config as config_module  # noqa: E402
from funddiff import frozen, serialize  # noqa: E402

SCHEMA = "funddiff/config-manifest@1"
GENERATOR = "tools/freeze_config.py"


def build_manifest(data_dir):
    data_dir = Path(data_dir)
    config_dir = data_dir / "config"
    app_path = config_dir / "app.json"
    if not app_path.is_file():
        raise config_module.ConfigError("配置文件不存在：%s" % app_path)
    config = config_module.load_config(data_dir)
    return frozen.build_manifest(
        config_dir,
        SCHEMA,
        extra={
            "config_version": config.get("config_version"),
            "generator": GENERATOR,
        },
    )


def check(data_dir):
    data_dir = Path(data_dir)
    config_dir = data_dir / "config"
    manifest_path = config_dir / frozen.MANIFEST_NAME
    if not manifest_path.is_file():
        return ["MANIFEST 不存在：%s（先运行 tools/freeze_config.py）" % manifest_path]
    try:
        with manifest_path.open("r", encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, ValueError) as exc:
        return ["MANIFEST 无法读取：%s" % exc]

    expected = build_manifest(data_dir)
    problems = frozen.verify_manifest(config_dir, manifest, SCHEMA)
    for key in ("config_version", "generator"):
        if manifest.get(key) != expected.get(key):
            problems.append("%s 不符：清单 %r / 实际 %r" % (
                key, manifest.get(key), expected.get(key)))
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description="配置包冻结与校验")
    parser.add_argument("--data-dir", default=str(ROOT / "data"),
                        help="数据目录（默认仓库 data/）")
    parser.add_argument("--check", action="store_true", help="只校验，不写盘")
    args = parser.parse_args(argv)

    data_dir = Path(args.data_dir)
    try:
        if args.check:
            problems = check(data_dir)
        else:
            manifest = build_manifest(data_dir)
            serialize.write_json(data_dir / "config" / frozen.MANIFEST_NAME, manifest)
            print("freeze_config: 已写入 %s（%d 个文件）" % (
                data_dir / "config" / frozen.MANIFEST_NAME, len(manifest["files"])))
            return 0
    except config_module.ConfigError as exc:
        print("freeze_config: %s" % exc, file=sys.stderr)
        return 2
    except OSError as exc:
        print("freeze_config: 写盘/读取失败：%s" % exc, file=sys.stderr)
        return 2

    if problems:
        for problem in problems:
            print("[FAIL] %s" % problem, file=sys.stderr)
        print("freeze_config: FAIL（%d 处不一致）" % len(problems), file=sys.stderr)
        return 1
    print("freeze_config: PASS（配置包与 MANIFEST 一致）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
