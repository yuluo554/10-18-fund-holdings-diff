"""冻结配置加载与校验。

纪律（K 项）：
- 必需键缺失 → ConfigError（CLI 层转 exit 2），不做聪明默认值；
- diff.mode 必须显式给出，取值 provider / computed，不允许缺省推断；
- 数值以字符串存 JSON，以 Decimal 入内存，避免二进制浮点漂移；
- 披露期限只由法规条文 + 国务院节假日通知决定（count + calendar），
  配置里不写"某个季度截止到某月某日"这类无法追溯来源的固定日期。
"""

import datetime
import json
import re
from decimal import Decimal
from pathlib import Path

REQUIRED_PATHS = (
    ("diff", "mode"),
    ("diff", "threshold"),
    ("quarters",),
    ("disclosure_rule", "count"),
    ("disclosure_rule", "calendar"),
    ("rate_limit",),
    ("compliance", "forbidden_terms"),
    ("sources",),
    ("ordering",),
)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

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
        _month_day(entry["period_end"], "quarters.%s.period_end" % name)

    _validate_disclosure_rule(config["disclosure_rule"])

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


def _validate_disclosure_rule(rule):
    """披露期限规则：法定工作日数 + 已核对来源 + 逐年节假日日历。"""
    if not isinstance(rule, dict):
        raise ConfigError("disclosure_rule 必须是对象")
    kind = rule.get("kind")
    if kind != "workdays_after_period_end":
        raise ConfigError(
            "disclosure_rule.kind 必须是 workdays_after_period_end，实际为 %r" % (kind,))
    count = rule.get("count")
    if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
        raise ConfigError("disclosure_rule.count 必须是正整数，实际为 %r" % (count,))
    citation = rule.get("citation")
    if not isinstance(citation, dict):
        raise ConfigError("disclosure_rule.citation 必须在配置中给出（法规依据不可缺省）")
    for key in ("title", "article", "text", "url", "retrieved_on",
                "attachment", "attachment_sha256"):
        if not citation.get(key):
            raise ConfigError("disclosure_rule.citation 缺少 %s" % key)
    _validate_date(citation["retrieved_on"], "disclosure_rule.citation.retrieved_on")
    if not re.match(r"^[0-9a-f]{64}$", citation["attachment_sha256"]):
        raise ConfigError("disclosure_rule.citation.attachment_sha256 必须是 64 位小写十六进制")

    calendar = rule.get("calendar")
    if not isinstance(calendar, dict) or not calendar:
        raise ConfigError("disclosure_rule.calendar 必须是非空对象（按年登记节假日）")
    for year in sorted(calendar):
        entry = calendar[year]
        if not isinstance(year, str) or len(year) != 4 or not year.isdigit():
            raise ConfigError("disclosure_rule.calendar 的年份键必须是四位数字字符串，实际为 %r" % (year,))
        if not isinstance(entry, dict) or not entry.get("notice"):
            raise ConfigError("disclosure_rule.calendar.%s 缺少 notice（通知出处）" % year)
        for field in ("holidays", "makeup_workdays"):
            values = entry.get(field)
            if not isinstance(values, list):
                raise ConfigError("disclosure_rule.calendar.%s.%s 必须是列表" % (year, field))
            seen = []
            for value in values:
                where = "disclosure_rule.calendar.%s.%s" % (year, field)
                if not isinstance(value, str) or not _DATE_RE.match(value):
                    raise ConfigError("%s 含非法日期：%r" % (where, value))
                _validate_date(value, where)
                if not value.startswith(year + "-"):
                    raise ConfigError("%s 的日期不属于该年份：%r" % (where, value))
                if value in seen:
                    raise ConfigError("%s 含重复日期：%r" % (where, value))
                seen.append(value)
        overlap = [value for value in entry["holidays"] if value in entry["makeup_workdays"]]
        if overlap:
            raise ConfigError("disclosure_rule.calendar.%s 的节假日与调休上班日重叠：%s" % (
                year, ", ".join(overlap)))
    return True


def _validate_date(value, where):
    try:
        datetime.date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except (TypeError, ValueError):
        raise ConfigError("%s 不是有效日期：%r" % (where, value))


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
