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


def test_pyproject_requires_python_312():
    text = PYPROJECT.read_text(encoding="utf-8")
    assert 'requires-python = ">=3.12"' in text


def test_console_script_target_is_importable():
    from funddiff.cli import main  # noqa: F401
    text = PYPROJECT.read_text(encoding="utf-8")
    assert 'funddiff = "funddiff.cli:main"' in text


def test_package_layout_matches_pyproject():
    src = ROOT / "src" / "funddiff"
    assert (src / "__init__.py").is_file()
    assert (src / "__main__.py").is_file()
    assert sys.version_info >= (3, 12)


# ---------- 状态面常驻断言（D1）----------
# 这一面在 v0.1.0 回写时整段漂过一次（只改了 plan/00，README 没跟上）。
# 四条分开写、各查各的字面，任一条被改坏只会有它自己变红——不要合并成一个弱断言。

def status_section():
    """README 的「当前状态」段（从该标题到下一个二级标题）。"""
    text = read_readme()
    start = text.index("## 当前状态")
    rest = text[start + len("## 当前状态"):]
    end = rest.find("\n## ")
    return rest if end < 0 else rest[:end]


def test_readme_status_section_names_published_version():
    """状态段必须同时写出"已发布"与版本号 v0.1.0；只改这一段任一要素即红。"""
    section = status_section()
    assert "已发布" in section, "状态段没有'已发布'字样"
    assert "v0.1.0" in section, "状态段没有已发布版本号 v0.1.0"
    assert "releases/tag/v0.1.0" in section, "状态段没有 Release 链接"


def test_readme_does_not_claim_m6_pending():
    """不得再写"M6 待开工"——M6 已于 2026-10-18 完成。"""
    assert "待开工" not in read_readme(), "README 仍称 M6 待开工"


def test_readme_does_not_claim_ci_never_ran():
    """不得再写"尚未跑过 CI"——远端存在且 4 个 run 全 success。"""
    assert "尚未跑过 CI" not in read_readme(), "README 仍称尚未跑过 CI"


def test_readme_milestone_m6_row_is_done():
    """里程碑表的 M6 行必须是 ✅，不能留 ⬜。"""
    text = read_readme()
    assert "| M6 | GitHub 发布 | ⬜ |" not in text, "README 的 M6 行仍是未完成"
    rows = [line for line in text.splitlines()
            if line.startswith("| M6 |") and "GitHub 发布" in line]
    assert rows, "README 里程碑表缺少 M6 行"
    assert "✅" in rows[0], "M6 行未标 ✅：%r" % rows[0]


def test_readme_exit_code_3_is_marked_retired():
    """退出码总表必须把 3 说成已退役，不能继续当成可用语义。"""
    lines = read_readme().splitlines()
    starts = [i for i, line in enumerate(lines) if "退出码总表" in line]
    assert starts, "README 找不到退出码总表"
    # 总表是一段（多行）续行，取标记行起连续 4 行合并后再判
    block = "\n".join(lines[starts[0]:starts[0] + 4])
    assert "`3`" in block, "退出码总表未列出 3：%r" % block
    assert "已退役" in block, "退出码总表未把 3 标注为已退役：%r" % block
