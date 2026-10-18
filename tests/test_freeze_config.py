"""配置冻结门禁：MANIFEST 与 app.json 必须逐字节一致。"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
TOOL = ROOT / "tools" / "freeze_config.py"


def _run(*args):
    return subprocess.run(
        [sys.executable, str(TOOL)] + list(args),
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _read(path):
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def test_repo_config_manifest_check_passes():
    proc = _run("--check")
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")


def test_manifest_lists_app_json_and_not_itself():
    manifest = _read(DATA_DIR / "config" / "MANIFEST.json")
    assert manifest["schema"] == "funddiff/config-manifest@1"
    assert "app.json" in manifest["files"]
    assert "MANIFEST.json" not in manifest["files"]
    assert manifest["files"]["app.json"]["sha256"]


def test_manifest_config_version_matches_app():
    app = _read(DATA_DIR / "config" / "app.json")
    manifest = _read(DATA_DIR / "config" / "MANIFEST.json")
    assert manifest["config_version"] == app["config_version"]


def test_tampered_config_fails_check(tmp_path):
    data_dir = tmp_path / "data"
    shutil.copytree(DATA_DIR / "config", data_dir / "config")
    app_path = data_dir / "config" / "app.json"
    app_path.write_text(app_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    proc = _run("--data-dir", str(data_dir), "--check")
    assert proc.returncode == 1
    assert b"SHA256" in proc.stderr


def test_missing_manifest_fails_check(tmp_path):
    data_dir = tmp_path / "data"
    shutil.copytree(DATA_DIR / "config", data_dir / "config")
    (data_dir / "config" / "MANIFEST.json").unlink()

    proc = _run("--data-dir", str(data_dir), "--check")
    assert proc.returncode == 1
    assert b"MANIFEST" in proc.stderr


def test_extra_config_file_fails_check(tmp_path):
    data_dir = tmp_path / "data"
    shutil.copytree(DATA_DIR / "config", data_dir / "config")
    (data_dir / "config" / "extra.json").write_text("{}\n", encoding="utf-8")

    proc = _run("--data-dir", str(data_dir), "--check")
    assert proc.returncode == 1
    assert "未登记".encode("utf-8") in proc.stderr


def test_generate_refuses_invalid_config(tmp_path):
    data_dir = tmp_path / "data"
    shutil.copytree(DATA_DIR / "config", data_dir / "config")
    app_path = data_dir / "config" / "app.json"
    app = _read(app_path)
    app["diff"]["mode"] = "auto"
    app_path.write_text(
        json.dumps(app, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    proc = _run("--data-dir", str(data_dir))
    assert proc.returncode == 2
    assert b"diff.mode" in proc.stderr
