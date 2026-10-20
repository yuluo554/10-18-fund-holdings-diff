# -*- coding: utf-8 -*-
"""发布终态门自身的测试：探针必须"一条检查一次红"。

`tools/check_release.py` 是发布的守门人；如果它的某条检查从来没被证伪过，
它就只是打印 PASS 的装饰。这里在 pytest 里替 CI 兜住这一点——
只跑**内存探针**（不读 tag、不读附件、不联网），所以在 sdist 解包树里也成立。
"""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "check_release.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("check_release_tool", str(TOOL))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_tool_exists():
    assert TOOL.is_file(), "tools/check_release.py 缺失"


def test_every_check_has_a_mutation_probe():
    tool = load_tool()
    specs = tool._mutation_specs(tool._synthetic_facts())
    for name, _func in tool.RELEASE_CHECKS:
        assert name in specs, "检查 %s 没有变异探针（=从未被证伪）" % name


def test_synthetic_world_is_green():
    """探针的基线必须全绿，否则"变红"证明不了任何事。"""
    tool = load_tool()
    results = tool.run_checks(tool._synthetic_facts(), tool.RELEASE_CHECKS)
    failed = [(name, detail) for name, ok, detail in results if not ok]
    assert not failed, "合成干净世界不干净：%s" % failed


def test_each_probe_reddens_exactly_one_check():
    tool = load_tool()
    assert tool.mutation_probe() == 0


def test_metadata_mode_is_a_subset_of_release_mode():
    """metadata 模式只能更宽松：它的每条检查都必须也在 release 模式里。"""
    tool = load_tool()
    release = {name for name, _ in tool.RELEASE_CHECKS}
    metadata = {name for name, _ in tool.METADATA_CHECKS}
    assert metadata <= release, "metadata 模式出现了 release 模式没有的检查"
