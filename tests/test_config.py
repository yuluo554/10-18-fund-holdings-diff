import json

import pytest

from funddiff import config as config_module

DATA_DIR = __import__("pathlib").Path(__file__).resolve().parents[1] / "data"


def load():
    return config_module.load_config(DATA_DIR)


def test_repo_config_is_valid():
    cfg = load()
    assert cfg["diff"]["mode"] in ("provider", "computed")


def test_diff_mode_must_be_valid(tmp_path):
    cfg = load()
    cfg["diff"]["mode"] = "auto"
    with pytest.raises(config_module.ConfigError):
        config_module.validate_config(cfg)


def test_missing_required_key_raises(tmp_path):
    cfg = load()
    del cfg["diff"]["threshold"]
    with pytest.raises(config_module.ConfigError):
        config_module.validate_config(cfg)


def test_disclosure_rule_requires_count():
    cfg = load()
    del cfg["disclosure_rule"]["count"]
    with pytest.raises(config_module.ConfigError):
        config_module.validate_config(cfg)


def test_disclosure_rule_kind_must_be_supported():
    cfg = load()
    cfg["disclosure_rule"]["kind"] = "fixed_date"
    with pytest.raises(config_module.ConfigError):
        config_module.validate_config(cfg)


def test_disclosure_calendar_requires_official_notice():
    cfg = load()
    cfg["disclosure_rule"]["calendar"]["2026"]["notice"] = ""
    with pytest.raises(config_module.ConfigError):
        config_module.validate_config(cfg)


def test_disclosure_calendar_rejects_bad_date():
    cfg = load()
    cfg["disclosure_rule"]["calendar"]["2026"]["holidays"].append("2026/10/01")
    with pytest.raises(config_module.ConfigError):
        config_module.validate_config(cfg)


def test_empty_forbidden_terms_rejected():
    cfg = load()
    cfg["compliance"]["forbidden_terms"] = []
    with pytest.raises(config_module.ConfigError):
        config_module.validate_config(cfg)


def test_footer_is_required():
    cfg = load()
    del cfg["compliance"]["footer"]
    with pytest.raises(config_module.ConfigError):
        config_module.validate_config(cfg)


def test_source_entries_are_complete():
    cfg = load()
    del cfg["sources"]["csrc_eid_public"]["label"]
    with pytest.raises(config_module.ConfigError):
        config_module.validate_config(cfg)


def test_threshold_is_decimal_string():
    cfg = load()
    assert isinstance(cfg["diff"]["threshold"], str)
    assert config_module.get_decimal(cfg, ["diff", "threshold"]) > 0


def test_broken_json_raises_config_error(tmp_path):
    data_dir = tmp_path / "data"
    (data_dir / "config").mkdir(parents=True)
    (data_dir / "config" / "app.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(config_module.ConfigError):
        config_module.load_config(data_dir)
