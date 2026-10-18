"""冻结配置加载与校验。

纪律（K 项）：
- 必需键缺失 → ConfigError（CLI 层转 exit 2），不做聪明默认值；
- diff.mode 必须显式给出，取值 provider / computed，不允许缺省推断；
- 数值以字符串存 JSON，以 Decimal 入内存，避免二进制浮点漂移。
"""

import json
from decimal import Decimal
from pathlib import Path

REQUIRED_PATHS = (
    ("diff", "mode"),
    ("diff", "threshold"),
    ("quarters",),
    ("rate_limit",),
    ("compliance", "forbidden_terms"),
    ("sources",),
    ("ordering",),
)

VALID_MODES = ("provider", "computed")
VALID_QUARTERS = ("Q1", "Q2", "Q3", "Q4")


class ConfigError(Exception):
    """配置缺失或非法。对应退出码 2。"""


def load_config(data_dir):
    path = Path(data_dir) / "config" / "app.json"
    if not path.is_file():
        raise ConfigError("配置文件不存在：%s" % path)
    try:
        with path.open("r", encoding="utf-8") as handle:
            config = json.load(handle)
    except (ValueError, OSError) as exc:
        raise ConfigError("配置文件无法读取：%s（%s）" % (path, exc))
    validate_config(config)
    return config


def _dig(config, keys):
    node = config
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            return False
        node = node[key]
    return True


def validate_config(config):
    if not isinstance(config, dict):
        raise ConfigError("配置根必须是对象")
    for keys in REQUIRED_PATHS:
        if not _dig(config, keys):
            raise ConfigError("配置缺少必需项：%s" % ".".join(keys))

    mode = config["diff"]["mode"]
    if mode not in VALID_MODES:
        raise ConfigError(
            "diff.mode 必须是 %s 之一，实际为 %r" % (" / ".join(VALID_MODES), mode)
        )
    decimal_value(config["diff"]["threshold"], "diff.threshold")

    quarters = config["quarters"]
    if not isinstance(quarters, dict):
        raise ConfigError("quarters 必须是对象")
    for name in VALID_QUARTERS:
        if name not in quarters:
            raise ConfigError("quarters 缺少 %s" % name)
        entry = quarters[name]
        if not isinstance(entry, dict) or "period_end" not in entry:
            raise ConfigError("quarters.%s 缺少 period_end" % name)
        if "disclosure_deadline" not in entry:
            raise ConfigError("quarters.%s 缺少 disclosure_deadline" % name)
        _month_day(entry["period_end"], "quarters.%s.period_end" % name)
        _month_day(entry["disclosure_deadline"], "quarters.%s.disclosure_deadline" % name)
        if "unverified" not in entry:
            raise ConfigError("quarters.%s 缺少 unverified 标记" % name)

    terms = config["compliance"]["forbidden_terms"]
    if not isinstance(terms, list) or not terms:
        raise ConfigError("compliance.forbidden_terms 必须是非空列表")
    for term in terms:
        if not isinstance(term, str) or not term.strip():
            raise ConfigError("compliance.forbidden_terms 含空项或非字符串")
    footer = config["compliance"].get("footer")
    if not footer:
        raise ConfigError("compliance.footer 必须在配置中给出（不可关闭）")

    for source, meta in config["sources"].items():
        if not isinstance(meta, dict):
            raise ConfigError("sources.%s 必须是对象" % source)
        for key in ("kind", "label", "endpoint", "role"):
            if key not in meta:
                raise ConfigError("sources.%s 缺少 %s" % (source, key))

    return True


def _month_day(value, where):
    try:
        month_text, day_text = value.split("-")
        month = int(month_text)
        day = int(day_text)
    except (AttributeError, ValueError):
        raise ConfigError("%s 必须是 MM-DD，实际为 %r" % (where, value))
    if not (1 <= month <= 12 and 1 <= day <= 31):
        raise ConfigError("%s 超出范围：%r" % (where, value))
    return month, day


def decimal_value(value, where):
    try:
        return Decimal(str(value))
    except Exception:
        raise ConfigError("%s 必须是十进制字符串，实际为 %r" % (where, value))


def get_decimal(config, keys):
    node = config
    for key in keys:
        node = node[key]
    return decimal_value(node, ".".join(keys))


def source_label(config, source_name):
    return config["sources"][source_name]["label"]
