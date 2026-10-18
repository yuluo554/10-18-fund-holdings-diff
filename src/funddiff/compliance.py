"""合规词表扫描（硬门禁；M5 接进 report）。

纪律：
- 词表只来自配置（K10），代码零硬编码；
- 归一：大小写 + 全半角 + 空白折叠后匹配；
- 命中 → 由调用方转 exit 1，并输出 文件:行:命中词。
"""

import unicodedata


def normalize_text(text):
    if not isinstance(text, str):
        return ""
    folded = unicodedata.normalize("NFKC", text)
    folded = folded.casefold()
    return "".join(folded.split())


def scan_text(text, terms):
    """返回命中列表 [{line, term, excerpt}]；行号从 1 开始。"""
    hits = []
    normalized_terms = [(term, normalize_text(term)) for term in terms]
    normalized_terms = [(term, norm) for term, norm in normalized_terms if norm]

    for index, line in enumerate(text.splitlines(), start=1):
        normalized_line = normalize_text(line)
        for term, norm in normalized_terms:
            if norm in normalized_line:
                hits.append({"line": index, "term": term, "excerpt": line.strip()})
    return hits


def scan_files(paths, terms):
    """扫描多个文件，返回 {path: [hits]}（仅含有命中的文件）。"""
    results = {}
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                text = handle.read()
        except OSError:
            continue
        hits = scan_text(text, terms)
        if hits:
            results[str(path)] = hits
    return results


def format_hits(results):
    lines = []
    for path in sorted(results):
        for hit in results[path]:
            lines.append("%s:%d:%s" % (path, hit["line"], hit["term"]))
    return lines
