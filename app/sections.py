"""文档分段：把「文档类型 + 保留段落」映射到要保留原文的页码。

只有「整页型」段落（目录/参考文献/附录/签字页/封面）能可靠按页保留；
「同页型」段落（摘要/作者/公式/代码/数字）无法按页隔离，作为提示词禁译项（尽力而为）。
"""
from __future__ import annotations

# section_key -> 元信息。kind=page 可按页检测保留；kind=inpage 只能走提示词禁译。
SECTION_CATALOG: dict[str, dict] = {
    "toc": {"label": "目录", "kind": "page", "keywords": ["table of contents", "contents", "目录"]},
    "references": {"label": "参考文献", "kind": "page", "keywords": ["references", "bibliography", "参考文献", "引用文献"]},
    "appendix": {"label": "附录", "kind": "page", "keywords": ["appendix", "appendices", "supplementary material", "附录"]},
    "signature": {"label": "签字/盖章页", "kind": "page", "keywords": ["signature", "signatures", "签字", "盖章", "署名页"]},
    "cover": {"label": "封面", "kind": "page", "keywords": []},  # 封面固定为第 1 页
    "abstract": {"label": "摘要", "kind": "inpage", "keywords": []},
    "authors": {"label": "作者信息", "kind": "inpage", "keywords": []},
    "formula_code": {"label": "公式/代码块", "kind": "inpage", "keywords": []},
    "code": {"label": "代码/命令块", "kind": "inpage", "keywords": []},
    "numbers": {"label": "条款编号/金额/日期", "kind": "inpage", "keywords": []},
}


def _page_has_heading(text: str, keywords: list[str]) -> bool:
    """页面内是否出现某关键词的「标题行」。

    标题通常是独占一行的短文本（可带章节编号前缀），如 "References" / "6 References" /
    "A. Appendix" / "参考文献"。限制行长以避免匹配到正文里提到关键词的长句。
    """
    for raw in text.splitlines():
        line = raw.strip()
        if not line or len(line) > 40:
            continue
        low = line.lower()
        # 去掉行首编号/标点
        norm = low.lstrip("0123456789.、)（）. ").strip()
        for kw in keywords:
            if low == kw or norm == kw:
                return True
            if (low.startswith(kw) or norm.startswith(kw)) and len(line) <= len(kw) + 14:
                return True
    return False


def _find_section_start(page_texts: list[str], keywords: list[str]) -> int | None:
    """返回首个含该段落标题的页（0-based），找不到返回 None。"""
    if not keywords:
        return None
    for index, text in enumerate(page_texts):
        if _page_has_heading(text, keywords):
            return index
    return None


def detect_keep_pages(
    page_texts: list[str], keep_keys: set[str]
) -> tuple[set[int], dict[str, list[int]]]:
    """对「整页型」保留段落，返回 (要保留的 1-based 页码集合, {标签: 页码列表})。"""
    n = len(page_texts)
    pages: set[int] = set()
    detail: dict[str, list[int]] = {}
    if n == 0:
        return pages, detail

    ref = _find_section_start(page_texts, SECTION_CATALOG["references"]["keywords"])
    app = _find_section_start(page_texts, SECTION_CATALOG["appendix"]["keywords"])
    toc = _find_section_start(page_texts, SECTION_CATALOG["toc"]["keywords"])
    sig = _find_section_start(page_texts, SECTION_CATALOG["signature"]["keywords"])

    def add(label: str, rng: range) -> None:
        got = [p for p in rng if 1 <= p <= n]
        if got:
            pages.update(got)
            detail[label] = sorted(set(detail.get(label, []) + got))

    if "references" in keep_keys and ref is not None:
        last = (app - 1) if (app is not None and app > ref) else (n - 1)
        add(SECTION_CATALOG["references"]["label"], range(ref + 1, last + 2))
    if "appendix" in keep_keys and app is not None:
        add(SECTION_CATALOG["appendix"]["label"], range(app + 1, n + 1))
    if "toc" in keep_keys and toc is not None:
        add(SECTION_CATALOG["toc"]["label"], range(toc + 1, toc + 2))
    if "signature" in keep_keys and sig is not None:
        add(SECTION_CATALOG["signature"]["label"], range(sig + 1, n + 1))
    if "cover" in keep_keys:
        add(SECTION_CATALOG["cover"]["label"], range(1, 2))

    return pages, detail


def inpage_keep_labels(keep_keys: set[str]) -> list[str]:
    """返回「同页型」保留段落的标签（用于提示词禁译，尽力而为）。"""
    labels: list[str] = []
    for key in keep_keys:
        meta = SECTION_CATALOG.get(key)
        if meta and meta["kind"] == "inpage":
            labels.append(meta["label"])
    return labels


def normalize_keep_sections(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    keys = []
    for raw in value.replace("，", ",").split(","):
        key = raw.strip()
        if key in SECTION_CATALOG and key not in keys:
            keys.append(key)
    return tuple(keys)
