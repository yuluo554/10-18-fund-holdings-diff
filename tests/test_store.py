import pytest

from funddiff import paths, store


def test_add_is_idempotent(tmp_path):
    watchlist = store.Watchlist(tmp_path / "w.json")
    action, entry = watchlist.add("990001", name="甲", today="2026-10-18")
    assert action == "created"
    action, entry = watchlist.add("990001", name="甲", today="2026-10-18")
    assert action == "unchanged"
    assert len(watchlist.list_all()) == 1
    assert entry["added_on"] == "2026-10-18"


def test_update_keeps_original_added_on(tmp_path):
    watchlist = store.Watchlist(tmp_path / "w.json")
    watchlist.add("990001", name="甲", today="2026-10-18")
    action, entry = watchlist.add("990001", name="甲（改名）", today="2026-11-01")
    assert action == "updated"
    assert entry["added_on"] == "2026-10-18"
    assert entry["name"] == "甲（改名）"


def test_entries_sorted_by_code(tmp_path):
    watchlist = store.Watchlist(tmp_path / "w.json")
    watchlist.add("990003", today="2026-10-18")
    watchlist.add("990001", today="2026-10-18")
    assert [item["code"] for item in watchlist.list_all()] == ["990001", "990003"]


def test_remove_returns_false_when_absent(tmp_path):
    watchlist = store.Watchlist(tmp_path / "w.json")
    assert watchlist.remove("990001") is False
    watchlist.add("990001", today="2026-10-18")
    assert watchlist.remove("990001") is True


@pytest.mark.parametrize("code", ["1", "00001", "0000001", "abcdef", "", "00000A"])
def test_invalid_codes_rejected(tmp_path, code):
    with pytest.raises(store.StoreError):
        store.Watchlist(tmp_path / "w.json").add(code)


def test_missing_file_is_empty_list(tmp_path):
    watchlist = store.Watchlist(tmp_path / "w.json")
    assert watchlist.list_all() == []


def test_read_does_not_create_file(tmp_path):
    watchlist = store.Watchlist(tmp_path / "nested" / "w.json")
    watchlist.load()
    assert not (tmp_path / "nested").exists()


def test_list_all_does_not_write(tmp_path):
    """只读操作不得落盘（selftest 曾当场抓到这个缺陷）。"""
    target = tmp_path / "nested" / "w.json"
    assert store.Watchlist(target).list_all() == []
    assert not target.exists()
    assert not target.parent.exists()


def test_list_all_returns_copy(tmp_path):
    watchlist = store.Watchlist(tmp_path / "w.json")
    watchlist.add("990001", today="2026-10-18")
    snapshot = watchlist.list_all()
    snapshot[0]["name"] = "改副本"
    assert watchlist.list_all()[0]["name"] is None


def test_corrupt_file_raises(tmp_path):
    path = tmp_path / "w.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(store.StoreError):
        store.Watchlist(path).load()


def test_store_path_defaults_to_cwd(tmp_path):
    assert paths.store_path(cwd=tmp_path) == tmp_path / "local_data" / "watchlist.json"
    assert paths.store_path(explicit=tmp_path / "x.json", cwd=tmp_path) == tmp_path / "x.json"
