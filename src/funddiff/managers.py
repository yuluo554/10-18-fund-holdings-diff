"""基金经理变更（M4）：`jjjl` 页面解析 + 四类事件判定 + 产物渲染。

口径（plan/03 §5.1、HANDOFF-M4）：
- `change_class` 四类：in_period / prior_period / none / unparsed；
- "本季内"区间来自冻结配置：报告期起止由 `quarters.*.period_end` 推导，
  不读系统时钟、不写死日期（K10）；
- `unparsed` 必须附页面快照（原文 + SHA256），与"无变更"（空列表 + none 计数）分开；
- 排序确定（K2）：基金代码升序；经理按 change_date 升序（null 最后）、姓名、分类；
- `managers@1` 从 events 台账（`q<period>/events/<code>.json`）读取，
  并对每条已分类记录用配置区间反向复算，label 漂移即内部一致性错误（exit 5）。
"""

import hashlib
import html as html_module
import re
import datetime

from . import events, window

SCHEMA = "funddiff/managers@1"

CLASS_IN_PERIOD = "in_period"
CLASS_PRIOR_PERIOD = "prior_period"
CLASS_NONE = "none"
CLASS_UNPARSED = "unparsed"
CLASSES = (CLASS_IN_PERIOD, CLASS_PRIOR_PERIOD, CLASS_NONE, CLASS_UNPARSED)

SOURCE = "jjjl"

CHANGE_MARKER = "基金经理变动一览"
PROFILE_MARKER = "现任基金经理简介"

_TAG_RE = re.compile(r"<[^>]+>")
_ROW_RE = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.S | re.I)
_TABLE_RE = re.compile(r"<table\b[^>]*>.*?</table>", re.S | re.I)
_DATE_RE = re.compile(
    r"^(\d{4})\s*[-/年]\s*(\d{1,2})\s*[-/月]\s*(\d{1,2})\s*日?$")
_START_DATE_RE = re.compile(
    r"上任日期\s*[：:]?\s*(\d{4}\s*[-/年]\s*\d{1,2}\s*[-/月]\s*\d{1,2}\s*日?)")
_EMPTY_END = ("", "至今", "今", "—", "-", "--", "无")


class ManagerError(Exception):
    """events 台账缺失/清单为空等门禁失败（exit 1）。"""


class ManagerParseError(Exception):
    """`jjjl` 页面结构无法解析（落 unparsed + 页面快照，不猜）。"""

    def __init__(self, message, raw_text="", raw_sha256=None):
        Exception.__init__(self, message)
        self.raw_text = raw_text
        self.raw_sha256 = raw_sha256 or _sha256_text(raw_text)


def _sha256_text(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _text(fragment):
    """去标签、反转义、压空白；保留可见文本。"""
    if fragment is None:
        return ""
    plain = html_module.unescape(_TAG_RE.sub(" ", fragment))
    return re.sub(r"\s+", " ", plain).strip()


def normalize_date(value):
    """常见页面日期格式 → ISO；无法识别返回 None（调用方决定 unparsed）。"""
    text = _text(value)
    match = _DATE_RE.match(text)
    if not match:
        return None
    try:
        return datetime.date(int(match.group(1)), int(match.group(2)),
                             int(match.group(3))).isoformat()
    except ValueError:
        return None


def _cells(row_html, tag):
    pattern = re.compile(r"<%s\b[^>]*>(.*?)</%s>" % (tag, tag), re.S | re.I)
    return pattern.findall(row_html)


def _table_after(html_text, marker):
    """取标记之后的第一个表格；找不到即结构失败（附快照证据）。"""
    index = html_text.find(marker)
    if index < 0:
        raise ManagerParseError(
            "未找到「%s」段落" % marker,
            raw_text=html_text[:2000], raw_sha256=_sha256_text(html_text))
    section = html_text[index:]
    match = _TABLE_RE.search(section)
    if not match:
        raise ManagerParseError(
            "「%s」段落未找到表格" % marker,
            raw_text=section[:2000], raw_sha256=_sha256_text(html_text))
    return match.group(0), section[:2000]


def _header_cells(table_html):
    for row in _ROW_RE.findall(table_html):
        if re.search(r"<th\b", row, re.I):
            cells = _cells(row, "th")
            if not cells:
                cells = _cells(row, "td")
            return [_text(cell) for cell in cells]
    return []


def _column(headers, keywords):
    for index, text in enumerate(headers):
        for keyword in keywords:
            if keyword in text:
                return index
    return None


def _split_names(name_text):
    parts = re.split(r"[\s、,，/]+", _text(name_text))
    return [part for part in parts if part]


def parse_incumbent_starts(html_text):
    """解析「现任基金经理简介」里的姓名 → 上任日期。

    页面结构变化时返回空字典（姓名仍保留，start=null），不猜测日期。
    """
    index = html_text.find(PROFILE_MARKER)
    if index < 0:
        return {}
    section = html_text[index + len(PROFILE_MARKER):]
    starts = {}

    # 结构一：每位经理一个 <h4>姓名</h4>，其后 1.5k 字符内出现「上任日期」。
    for block in re.split(r"(?=<h4\b)", section, flags=re.I):
        name_match = re.search(r"<h4\b[^>]*>(.*?)</h4>", block, re.S | re.I)
        if not name_match:
            continue
        name = _text(name_match.group(1))
        if not name or "基金经理" in name:
            continue
        date_match = _START_DATE_RE.search(block)
        if date_match:
            date = normalize_date(date_match.group(1))
            if date:
                starts.setdefault(name, date)

    # 结构二：姓名链接后紧跟简介段落。
    if not starts:
        for link in re.finditer(r"<a\b[^>]*>(.*?)</a>", section, re.S | re.I):
            name = _text(link.group(1))
            if not name or "基金经理" in name:
                continue
            tail = section[link.end():link.end() + 1500]
            date_match = _START_DATE_RE.search(tail)
            if date_match:
                date = normalize_date(date_match.group(1))
                if date:
                    starts.setdefault(name, date)
    return starts


def classify_change(change_date, period, config):
    """按冻结配置推导的报告期区间分类；区间外返回 None（与当前报告无关）。

    - in_period  : period_start <= change_date <= period_end
    - prior_period: 上一报告期区间内
    - None       : 更早或更晚，不是本报告窗口的事件
    `none` 由"没有任何相关记录"表达，不落到单条记录上。
    """
    day = normalize_date(change_date)
    if day is None:
        raise ValueError("内部一致性：非法变更日期 %r" % (change_date,))
    current = window.window_for_period(config, period)
    previous = window.window_for_period(config, window.previous_period(period))
    if current["period_start"] <= day <= current["period_end"]:
        return CLASS_IN_PERIOD
    if previous["period_start"] <= day <= previous["period_end"]:
        return CLASS_PRIOR_PERIOD
    return None


def _snapshot(raw_text):
    """页面快照证据：原文 + 自身 SHA256（留证，不猜）。"""
    text = raw_text or ""
    return {
        "kind": "page_text",
        "raw_text": text,
        "sha256": _sha256_text(text),
    }


def unparsed_record(message, raw_text, raw_sha256=None):
    """解析失败的显式记录：字段留 null，附快照；不替用户猜姓名/日期。"""
    text = raw_text or ""
    record = {
        "name": None,
        "start": None,
        "end": None,
        "change_date": None,
        "in_period": None,
        "change_class": CLASS_UNPARSED,
        "source": SOURCE,
        "raw_text": text,
        "snapshot": _snapshot(text),
        "unparsed_reason": message,
    }
    if raw_sha256:
        record["snapshot"]["page_sha256"] = raw_sha256
    return record


def parse_managers_html(html_text, config, period, raw_sha256=None):
    """解析 `jjjl` 页面，返回与 events.managers 同形的记录列表。

    - 表头/表体结构缺失 → ManagerParseError（附快照，调用方落 unparsed）；
    - 单行字段坏掉 → 该行落 unparsed 记录，其余行照常解析；
    - 只有与本报告期（或上一报告期）相关的记录会保留；更早历史 = 无变更。
    """
    table, excerpt = _table_after(html_text, CHANGE_MARKER)
    headers = _header_cells(table)
    if not headers:
        raise ManagerParseError(
            "「%s」表格缺少表头" % CHANGE_MARKER,
            raw_text=excerpt, raw_sha256=raw_sha256 or _sha256_text(html_text))

    start_index = _column(headers, ("起始期", "起始日期", "开始日期"))
    end_index = _column(headers, ("截止期", "截止日期", "结束日期"))
    name_index = _column(headers, ("基金经理", "姓名"))
    if start_index is None or end_index is None or name_index is None:
        raise ManagerParseError(
            "「%s」表头缺少必需列（起始期/截止期/基金经理）：%s" % (
                CHANGE_MARKER, " | ".join(headers)),
            raw_text=excerpt, raw_sha256=raw_sha256 or _sha256_text(html_text))

    profile_starts = parse_incumbent_starts(html_text)
    records = []
    for row_html in _ROW_RE.findall(table):
        if re.search(r"<th\b", row_html, re.I):
            continue
        cells = _cells(row_html, "td")
        if not cells:
            continue
        texts = [_text(cell) for cell in cells]
        if not any(texts):
            continue
        raw_text = " | ".join(texts)

        required = max(start_index, end_index, name_index)
        if len(texts) <= required:
            records.append(unparsed_record(
                "变动一览行列数不足（需要至少 %d 列）" % (required + 1),
                raw_text, raw_sha256))
            continue

        change_date = normalize_date(texts[start_index])
        end_text = texts[end_index]
        if end_text in _EMPTY_END:
            end_date = None
        else:
            end_date = normalize_date(end_text)
            if end_date is None:
                records.append(unparsed_record(
                    "截止期无法解析：%r" % end_text, raw_text, raw_sha256))
                continue
        names = _split_names(texts[name_index])
        if change_date is None or not names:
            records.append(unparsed_record(
                "起始期或基金经理姓名无法解析", raw_text, raw_sha256))
            continue

        change_class = classify_change(change_date, period, config)
        if change_class is None:
            # 更早/更晚的历史记录：不属于本报告窗口，不是"未解析"。
            continue
        for name in names:
            records.append({
                "name": name,
                "start": profile_starts.get(name),
                "end": end_date,
                "change_date": change_date,
                "in_period": change_class == CLASS_IN_PERIOD,
                "change_class": change_class,
                "source": SOURCE,
                "raw_text": raw_text,
            })
    return sort_records(records)


def sort_records(records):
    """确定性排序（K2）：change_date 升序（null 最后）→ 分类 → 姓名。"""
    def key(record):
        change_date = record.get("change_date")
        if change_date is None:
            return (1, "", record.get("change_class") or "",
                    record.get("name") or "")
        return (0, change_date, record.get("change_class") or "",
                record.get("name") or "")
    return sorted(records, key=key)


def _normalize_record(item, period, config, fund_code):
    """把 events 台账里的一条经理记录转成产物条目，并做配置区间反向复算。"""
    change_class = item.get("change_class")
    if change_class not in CLASSES:
        raise ValueError("内部一致性：未知经理变更分类 %r（%s）" % (
            change_class, fund_code))
    if change_class == CLASS_NONE:
        raise ValueError(
            "内部一致性：managers 条目不应使用 none；无变更用空列表表达（%s）"
            % fund_code)
    if change_class == CLASS_UNPARSED:
        raw_text = item.get("raw_text") or ""
        record = unparsed_record(
            item.get("unparsed_reason") or "页面解析失败（events 台账标记 unparsed）",
            raw_text)
        # 台账若已带快照哈希，作为页面级哈希单列；快照条目本身仍对应 raw_text。
        page_sha = (item.get("snapshot") or {}).get("sha256")
        if page_sha and page_sha != record["snapshot"]["sha256"]:
            record["snapshot"]["page_sha256"] = page_sha
        return record

    change_date = item.get("change_date")
    if change_date is None:
        raise ValueError("内部一致性：%s 的经理记录缺少 change_date" % fund_code)
    computed = classify_change(change_date, period, config)
    if computed != change_class:
        raise ValueError(
            "内部一致性：%s 的 change_class=%r 与配置区间重算=%r 不一致"
            % (fund_code, change_class, computed))
    return {
        "name": item.get("name"),
        "start": item.get("start"),
        "end": item.get("end"),
        "change_date": change_date,
        "in_period": change_class == CLASS_IN_PERIOD,
        "change_class": change_class,
        "source": item.get("source") or SOURCE,
        "raw_text": item.get("raw_text"),
    }


def summarize(records):
    summary = {name: 0 for name in CLASSES}
    if not records:
        summary[CLASS_NONE] = 1
    for record in records:
        summary[record["change_class"]] = summary[record["change_class"]] + 1
    return summary


def build(data_dir, config, codes, period):
    """生成 `funddiff/managers@1` 产物；基金代码升序、记录确定性排序。"""
    if period is None:
        raise ManagerError(
            "缺少报告期：先 watch/window 确定报告期，或显式传 --period YYYYQn")
    window.parse_period(period)
    if not codes:
        raise ManagerError("清单为空。用 `funddiff watch add <code>` 添加。")

    info = window.window_for_period(config, period)
    funds = []
    totals = {name: 0 for name in CLASSES}
    for code in sorted(codes):
        payload = events.load_events(data_dir, period, code)
        if payload is None:
            raise ManagerError(
                "缺少事件快照：%s（先具备 %s 的 events 台账）" % (
                    code, period))
        events.validate_events(payload, period, code)
        records = [_normalize_record(item, period, config, code)
                   for item in payload.get("managers") or []]
        records = sort_records(records)
        summary = summarize(records)
        funds.append({
            "fund_code": code,
            "fund_name": payload.get("fund_name"),
            "inputs": {"events": events.input_pointer(period, code)},
            "managers": records,
            "summary": summary,
        })
        for name in CLASSES:
            totals[name] = totals[name] + summary[name]

    return {
        "schema": SCHEMA,
        "report_period": period,
        "period_start": info["period_start"],
        "period_end": info["period_end"],
        "generated_at": window.today_iso(),
        "funds": funds,
        "totals": totals,
    }
