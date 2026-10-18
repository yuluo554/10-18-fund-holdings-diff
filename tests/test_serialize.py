import json

import pytest

from funddiff import serialize


def test_dumps_is_sorted_and_keeps_chinese():
    text = serialize.dumps({"b": 1, "a": "中文"})
    assert text == '{\n  "a": "中文",\n  "b": 1\n}\n'


def test_dumps_is_byte_stable():
    payload = {"z": [1, 2, 3], "a": {"n": None}}
    assert serialize.dumps(payload) == serialize.dumps(payload)


def test_write_json_no_crlf_and_trailing_newline(tmp_path):
    target = tmp_path / "out" / "x.json"
    serialize.write_json(target, {"k": "中文"})
    raw = target.read_bytes()
    assert b"\r\n" not in raw
    assert raw.endswith(b"\n")
    assert raw.decode("utf-8") == serialize.dumps({"k": "中文"})


def test_write_json_leaves_no_temp_files(tmp_path):
    target = tmp_path / "x.json"
    serialize.write_json(target, {"k": 1})
    assert [item.name for item in tmp_path.iterdir()] == ["x.json"]


def test_write_json_overwrites_atomically(tmp_path):
    target = tmp_path / "x.json"
    serialize.write_json(target, {"v": 1})
    serialize.write_json(target, {"v": 2})
    assert serialize.read_json(target) == {"v": 2}


def test_read_json_missing_file_raises(tmp_path):
    with pytest.raises(OSError):
        serialize.read_json(tmp_path / "missing.json")


def test_null_and_zero_stay_distinct(tmp_path):
    target = tmp_path / "x.json"
    serialize.write_json(target, {"a": None, "b": 0})
    text = target.read_text(encoding="utf-8")
    assert '"a": null' in text
    assert '"b": 0' in text
    assert json.loads(text) == {"a": None, "b": 0}
