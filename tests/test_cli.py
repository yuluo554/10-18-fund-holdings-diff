import json
import pathlib

import pytest

from funddiff import cli

DATA_DIR = pathlib.Path(__file__).resolve().parents[1] / "data"


def run(argv, capsys):
    code = cli.main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


@pytest.fixture()
def store_file(tmp_path):
    return str(tmp_path / "watchlist.json")


def test_no_command_prints_help(capsys):
    code, out, _ = run([], capsys)
    assert code == cli.EXIT_OK
    assert "funddiff" in out


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0


def test_watch_add_list_remove(capsys, store_file):
    code, out, _ = run(["--store", store_file, "watch", "add", "990001", "--name", "样例"], capsys)
    assert code == 0 and "已添加" in out

    code, out, _ = run(["--store", store_file, "watch", "list"], capsys)
    assert code == 0 and "990001" in out

    code, out, _ = run(["--store", store_file, "watch", "list", "--json"], capsys)
    assert code == 0
    assert json.loads(out)["funds"][0]["code"] == "990001"

    code, out, _ = run(["--store", store_file, "watch", "remove", "990001"], capsys)
    assert code == 0


def test_watch_remove_absent_returns_1(capsys, store_file):
    code, _, err = run(["--store", store_file, "watch", "remove", "990001"], capsys)
    assert code == cli.EXIT_GATE_FAILED
    assert "未在清单中" in err


def test_watch_invalid_code_returns_2(capsys, store_file):
    code, _, err = run(["--store", store_file, "watch", "add", "abc"], capsys)
    assert code == cli.EXIT_USAGE
    assert "6 位数字" in err


def test_watch_without_action_returns_2(capsys, store_file):
    code, _, err = run(["--store", store_file, "watch"], capsys)
    assert code == cli.EXIT_USAGE


def test_window_text_output(capsys, store_file):
    code, out, _ = run(
        ["--store", store_file, "--data-dir", str(DATA_DIR), "window", "--as-of", "2026-10-18"],
        capsys)
    assert code == 0
    assert "2026Q3" in out
    assert "2026-09-30" in out
    assert "判断基准日：2026-10-18" in out


def test_window_json_three_states(capsys, store_file):
    cli.main(["--store", store_file, "watch", "add", "990001", "--name", "甲"])
    cli.main(["--store", store_file, "watch", "add", "990002", "--name", "乙"])
    cli.main(["--store", store_file, "watch", "add", "990008", "--name", "丙"])
    capsys.readouterr()

    # 2026-10-18：Q3 快照最早发送日是 10-20，历史时点应全部“待披露”。
    code = cli.main(["--store", store_file, "--data-dir", str(DATA_DIR),
                     "window", "--as-of", "2026-10-18", "--json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert code == 0
    assert {item["disclosure"] for item in payload["funds"]} == {"待披露"}

    # 2026-10-20：990001/990002 已发送，990008 仍无记录。
    code = cli.main(["--store", store_file, "--data-dir", str(DATA_DIR),
                     "window", "--as-of", "2026-10-20", "--json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert code == 0
    states = {item["code"]: item["disclosure"] for item in payload["funds"]}
    assert states["990001"] == "已披露"
    assert states["990002"] == "已披露"
    assert states["990008"] == "待披露"
    assert payload["totals"]["已披露"] == 2
    assert payload["totals"]["待披露"] == 1


def test_window_no_data_when_snapshot_missing(capsys, store_file, tmp_path):
    data_dir = tmp_path / "data"
    (data_dir / "config").mkdir(parents=True)
    source = DATA_DIR / "config" / "app.json"
    (data_dir / "config" / "app.json").write_text(
        source.read_text(encoding="utf-8"), encoding="utf-8")
    cli.main(["--store", store_file, "watch", "add", "990001"])
    capsys.readouterr()

    code = cli.main(["--store", store_file, "--data-dir", str(data_dir),
                     "window", "--as-of", "2026-10-20", "--json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert code == 0
    assert payload["funds"][0]["disclosure"] == "无数据"
    assert payload["totals"]["无数据"] == 1


def test_window_invalid_date_returns_2(capsys, store_file):
    code, _, err = run(
        ["--store", store_file, "--data-dir", str(DATA_DIR), "window", "--as-of", "2026-13-01"],
        capsys)
    assert code == cli.EXIT_USAGE


def test_missing_data_dir_returns_2(capsys, store_file, tmp_path):
    code, _, err = run(
        ["--store", store_file, "--data-dir", str(tmp_path / "nope"), "window"], capsys)
    assert code == cli.EXIT_USAGE
    assert "数据目录不可用" in err


@pytest.mark.parametrize("command,stage", [
    ("managers", "M4"),
    ("scale", "M4"), ("report", "M5"), ("run", "M5"),
])
def test_stub_commands_return_3(capsys, store_file, command, stage):
    code, _, err = run(
        ["--store", store_file, "--data-dir", str(DATA_DIR), command], capsys)
    assert code == cli.EXIT_NOT_READY
    assert stage in err


def test_unknown_command_returns_2():
    with pytest.raises(SystemExit) as exc:
        cli.main(["nope"])
    assert exc.value.code == 2


def test_selftest_passes_in_repo(capsys, store_file, tmp_path):
    code, out, _ = run(
        ["--store", str(tmp_path / "w.json"), "--data-dir", str(DATA_DIR), "selftest"], capsys)
    assert code == 0, out
    assert "自检：通过" in out


def test_selftest_fails_when_data_dir_broken(capsys, store_file, tmp_path):
    code, out, err = run(
        ["--store", store_file, "--data-dir", str(tmp_path / "nope"), "selftest"], capsys)
    assert code == cli.EXIT_USAGE
    assert "数据目录不可用" in err


def test_selftest_never_touches_real_store(capsys, tmp_path):
    store_file = tmp_path / "watchlist.json"
    code = cli.main(["--store", str(store_file), "--data-dir", str(DATA_DIR), "selftest"])
    capsys.readouterr()
    assert code == 0
    assert not store_file.exists()


def test_build_parser_registers_all_documented_commands():
    parser = cli.build_parser()
    subparsers = [action for action in parser._actions
                  if isinstance(action, __import__("argparse")._SubParsersAction)][0]
    assert set(subparsers.choices) == {
        "watch", "window", "fetch", "diff", "managers", "scale", "report", "run", "selftest"}
