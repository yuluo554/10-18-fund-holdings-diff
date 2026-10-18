"""桩哨兵扫描：骨架期不许留下"看着做了其实没做"的痕迹。

扫描面：src / tools / tests。
被扫的三类标记在源码里以**运行时拼接**形式构造，避免扫描器自身成为命中源。
骨架期用 `errors.NotReady`（CLI 映射为退出码 3）表达"未落地"，它是显式契约，不是哨兵。
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = ("src", "tools", "tests")
SELF = Path(__file__).resolve()

SENTINELS = (
    "NotImple" + "mentedError",
    "TO" + "DO: 实现",
    "place" + "holder",
)


def iter_files():
    for name in SCAN_DIRS:
        for path in sorted((ROOT / name).rglob("*.py")):
            if path.resolve() == SELF:
                continue
            yield path


def test_scan_surface_is_not_empty():
    assert len(list(iter_files())) >= 12


def test_scanner_has_real_markers():
    assert len(SENTINELS) == 3
    assert all(marker for marker in SENTINELS)


def test_no_sentinel_markers():
    hits = []
    for path in iter_files():
        text = path.read_text(encoding="utf-8")
        for marker in SENTINELS:
            if marker in text:
                hits.append((str(path.relative_to(ROOT)), marker))
    assert not hits, "发现桩哨兵：%s" % hits


def test_not_ready_carries_stage():
    from funddiff.errors import NotReady

    exc = NotReady("某能力", "M2")
    assert exc.stage == "M2"
    assert "M2" in str(exc)


def test_stub_network_modules_use_not_ready():
    import pytest

    from funddiff.errors import NotReady
    from funddiff.net import csrc

    with pytest.raises(NotReady):
        csrc.fetch_public_metadata({})
