"""README 指令面 ↔ CLI 注册表的双向门禁。

两个面：
1. README 出现的 `funddiff <command>` 必须真在 argparse 注册表里；
2. argparse 注册的每个子命令都必须在 README 命令表里出现。
外加：README 提到的安装 extras 必须真在 pyproject 里声明。
"""

import argparse
import re
import sys
from pathlib import Path

from funddiff import cli

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
PYPROJECT = ROOT / "pyproject.toml"

COMMAND_RE = re.compile(r"\bfunddiff\s+([a-z][a-z0-9-]*)")
OPTION_RE = re.compile(r"--[a-z][a-z0-9-]*")


def read_readme():
    return README.read_text(encoding="utf-8")


def registered_commands():
    parser = cli.build_parser()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return set(action.choices)
    return set()


def test_readme_mentions_only_registered_commands():
    registered = registered_commands()
    mentioned = set(COMMAND_RE.findall(read_readme()))
    unknown = mentioned - registered
    assert not unknown, "README 提到未注册的子命令：%s" % sorted(unknown)


def test_every_registered_command_is_documented():
    text = read_readme()
    missing = [name for name in sorted(registered_commands())
               if ("funddiff %s" % name) not in text and ("`%s`" % name) not in text]
    assert not missing, "README 未记录子命令：%s" % missing


def test_readme_mentions_all_seven_plus_run_and_selftest():
    text = read_readme()
    for name in ("watch", "window", "fetch", "diff", "managers", "scale", "report", "run", "selftest"):
        assert name in text, "README 缺少子命令：%s" % name


def test_documented_flags_exist_somewhere_in_parser():
    """只检查出现在 `funddiff ...` 命令行里的参数（tools/ 脚本的参数不在此面）。"""
    parser = cli.build_parser()
    known = set()
    for action in parser._actions:
        known.update(action.option_strings)
        if isinstance(action, argparse._SubParsersAction):
            for sub in action.choices.values():
                for sub_action in sub._actions:
                    known.update(sub_action.option_strings)
                    if isinstance(sub_action, argparse._SubParsersAction):
                        for leaf in sub_action.choices.values():
                            for leaf_action in leaf._actions:
                                known.update(leaf_action.option_strings)

    unknown = []
    for line in read_readme().splitlines():
        if "funddiff" not in line:
            continue
        for flag in OPTION_RE.findall(line):
            if flag not in known:
                unknown.append((flag, line.strip()))
    assert not unknown, "README 的 funddiff 命令行用到未实现的参数：%s" % unknown


def test_pyproject_declares_dev_extra():
    text = PYPROJECT.read_text(encoding="utf-8")
    assert "dev = [" in text


def test_pyproject_requires_python_38():
    text = PYPROJECT.read_text(encoding="utf-8")
    assert 'requires-python = ">=3.8"' in text


def test_console_script_target_is_importable():
    from funddiff.cli import main  # noqa: F401
    text = PYPROJECT.read_text(encoding="utf-8")
    assert 'funddiff = "funddiff.cli:main"' in text


def test_package_layout_matches_pyproject():
    src = ROOT / "src" / "funddiff"
    assert (src / "__init__.py").is_file()
    assert (src / "__main__.py").is_file()
    assert sys.version_info >= (3, 8)
