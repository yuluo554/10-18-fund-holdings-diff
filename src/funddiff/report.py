# -*- coding: utf-8 -*-
"""零判定渲染（M5）：内存模型一份，渲染 report.md / report.html / report_data.json 三份。

纪律（plan/03 §6.5，AST 守门测试会打挂）：
- 本模块不 import diff / managers / scale，不 import presentation；
- 判定只来自 model 的现成字段（label / hits / status_text 等已判定文本）；
- 渲染里不出现「某态走某分支」的业务判定——同一结构统一循环渲染。

三产物同源：build_report_products(model) 对同一 model 渲染三份文本，
同输入双跑字节一致（K2；时间戳类字段由 presentation 组装期固定）。
"""

import html

from . import serialize

REPORT_JSON_SCHEMA = "funddiff/report@1"

# 零外链扫描（plan/03 §6.4）：以下形态出现即门禁失败（命中即 1）。
_EXTERNAL_LINK_PATTERNS = (
    "<script src",
    "<link",
    "http://",
    "https://",
    'src="//',
    "url(",
)


class ReportRenderError(Exception):
    """渲染产物违反零外链门禁。调用方转 exit 1。"""


def scan_external_links(html_text):
    """零外链扫描：返回命中列表 [{pattern, line, excerpt}]（行号从 1 起）。"""
    hits = []
    lowered = html_text.lower()
    for index, line in enumerate(html_text.splitlines(), start=1):
        low = line.lower()
        for pattern in _EXTERNAL_LINK_PATTERNS:
            if pattern in low:
                hits.append({
                    "pattern": pattern,
                    "line": index,
                    "excerpt": line.strip()[:160],
                })
    # lowered 供全文级兜底断言（多行属性等罕见形态）；
    # 行级扫描是主判据，这里仅确保模式表不为空。
    if lowered and not _EXTERNAL_LINK_PATTERNS:
        raise ReportRenderError("内部一致性：零外链模式表为空")
    return hits


def _esc(text):
    return html.escape(str(text), quote=True)


def _display(value):
    """null 与数值的统一显示：缺失 → null 字面量（K3：缺失不冒充 0）。"""
    if value is None:
        return "null"
    return str(value)


def render_markdown(model):
    """funddiff/report@1 模型 → report.md（人读）。"""
    meta = model["meta"]
    lines = []
    lines.append("# 基金季报：持仓变动与事件（%s）" % meta["report_period"])
    lines.append("")
    lines.append("- 报告窗口：%s ~ %s" % (meta["period_start"], meta["period_end"]))
    lines.append("- 数据基准日 as_of：%s" % meta["as_of"])
    lines.append("- 抓取时间戳：%s" % meta["fetched_at"])
    lines.append("- diff 口径：%s（阈值 %s）" % (meta["diff_mode"], meta["threshold"]))
    for note in meta.get("data_notes") or []:
        lines.append("- 数据说明：%s" % note)
    lines.append("")
    totals = model["totals"]
    lines.append("## 汇总")
    lines.append("")
    lines.append("基金 %d 只；披露：已披露 %d / 待披露 %d / 无数据 %d。" % (
        totals["funds"], totals["disclosed"], totals["pending"], totals["no_data"]))
    counts = totals.get("changes") or {}
    if counts:
        pairs = ["%s %d" % (label, counts[label]) for label in sorted(counts)]
        lines.append("变动汇总（五态 + 待确认）：%s。" % "，".join(pairs))
    lines.append("")

    for fund in model["funds"]:
        lines.append("## %s %s" % (fund["fund_code"], fund.get("name") or ""))
        lines.append("")
        for section in fund["sections"]:
            lines.extend(_render_md_section(section))
            lines.append("")
        if fund.get("prev_report_note"):
            lines.append("> 与上期报告对比：%s" % fund["prev_report_note"])
            lines.append("")
    lines.append("---")
    lines.append(model["footer"])
    lines.append("")
    return "\n".join(lines)


def _render_md_section(section):
    out = []
    out.append("### %s" % section["title"])
    out.append("")
    for row in section["rows"]:
        cells = " | ".join(_display(cell) for cell in row)
        out.append("- %s" % cells)
    for text in section.get("notes") or []:
        out.append("")
        out.append("> %s" % text)
    return out


_CSS = (
    "body{font-family:sans-serif;margin:2rem auto;max-width:60rem;"
    "padding:0 1rem;color:#1a1a1a;line-height:1.6}"
    "h1{font-size:1.5rem}h2{font-size:1.2rem;margin-top:2rem}"
    "h3{font-size:1.05rem;margin-top:1.2rem}"
    "table{border-collapse:collapse;width:100%;margin:0.4rem 0}"
    "th,td{border:1px solid #bbb;padding:0.25rem 0.5rem;text-align:left;"
    "vertical-align:top}"
    "th{background:#f2f2f2}"
    "footer{margin-top:2rem;padding-top:0.6rem;border-top:1px solid #999;"
    "color:#555;font-size:0.9rem}"
)


def render_html(model):
    """funddiff/report@1 模型 → report.html（单文件、内联 CSS、零外链）。"""
    meta = model["meta"]
    out = []
    out.append("<!doctype html>")
    out.append('<html lang="zh-CN"><head><meta charset="utf-8">')
    out.append("<title>%s</title>" % _esc(
        "基金季报：持仓变动与事件（%s）" % meta["report_period"]))
    out.append("<style>%s</style>" % _CSS)
    out.append("</head><body>")
    out.append("<h1>基金季报：持仓变动与事件（%s）</h1>" % _esc(meta["report_period"]))
    out.append("<ul>")
    out.append("<li>报告窗口：%s ~ %s</li>" % (
        _esc(meta["period_start"]), _esc(meta["period_end"])))
    out.append("<li>数据基准日 as_of：%s</li>" % _esc(meta["as_of"]))
    out.append("<li>抓取时间戳：%s</li>" % _esc(meta["fetched_at"]))
    out.append("<li>diff 口径：%s（阈值 %s）</li>" % (
        _esc(meta["diff_mode"]), _esc(meta["threshold"])))
    for note in meta.get("data_notes") or []:
        out.append("<li>数据说明：%s</li>" % _esc(note))
    out.append("</ul>")

    totals = model["totals"]
    out.append("<h2>汇总</h2>")
    out.append("<p>基金 %d 只；披露：已披露 %d / 待披露 %d / 无数据 %d。</p>" % (
        totals["funds"], totals["disclosed"], totals["pending"], totals["no_data"]))
    counts = totals.get("changes") or {}
    if counts:
        pairs = ["%s %d" % (label, counts[label]) for label in sorted(counts)]
        out.append("<p>变动汇总（五态 + 待确认）：%s。</p>" % _esc("，".join(pairs)))

    for fund in model["funds"]:
        out.append("<h2>%s %s</h2>" % (
            _esc(fund["fund_code"]), _esc(fund.get("name") or "")))
        for section in fund["sections"]:
            out.extend(_render_html_section(section))
        if fund.get("prev_report_note"):
            out.append("<p><em>与上期报告对比：%s</em></p>" % _esc(fund["prev_report_note"]))
    out.append("<footer>%s</footer>" % _esc(model["footer"]))
    out.append("</body></html>")
    return "\n".join(out) + "\n"


def _render_html_section(section):
    out = []
    out.append("<h3>%s</h3>" % _esc(section["title"]))
    out.append("<table>")
    for row in section["rows"]:
        out.append("<tr>%s</tr>" % "".join(
            "<td>%s</td>" % _esc(_display(cell)) for cell in row))
    out.append("</table>")
    for text in section.get("notes") or []:
        out.append("<p><em>%s</em></p>" % _esc(text))
    return out


def render_json(model):
    """模型 → report_data.json 文本（走 serialize 单点规范，K1）。"""
    return serialize.dumps(model)


def build_report_products(model):
    """同一内存模型 → {md, html, json} 三份文本（三产物同源）。"""
    md_text = render_markdown(model)
    html_text = render_html(model)
    json_text = render_json(model)
    return {"report.md": md_text, "report.html": html_text, "report_data.json": json_text}
