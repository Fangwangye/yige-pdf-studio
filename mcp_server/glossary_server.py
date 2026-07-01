"""术语知识 MCP Server（二期）。

把一期的结构化知识库（storage/knowledge/*.json）作为术语源对外暴露，
供翻译服务作为 MCP Client 在翻译前实时检索。

工具：
- glossary_search(text, top_k, domain): 返回出现在 text 中的术语条目。
- style_get(domain): 返回风格规则与禁译表。

运行（stdio）：
    python -m mcp_server.glossary_server
"""
from __future__ import annotations

import sys
from pathlib import Path

# 允许以脚本或 -m 方式启动时都能 import app 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp.server.fastmcp import FastMCP

from app import knowledge

mcp = FastMCP("yige-glossary")


def _iter_entries(domain: str = ""):
    for summary in knowledge.list_profiles():
        name = summary.get("name")
        if domain and name != domain:
            continue
        profile = knowledge.load_profile(name)
        if not profile:
            continue
        for entry in profile.get("glossary", []):
            yield {**entry, "domain": name}


@mcp.tool()
def glossary_search(text: str, top_k: int = 40, domain: str = "") -> dict:
    """检索术语：返回其原文出现在 text 中的术语条目（按知识库聚合，可按 domain=配置名限定）。"""
    lowered = text.lower()
    hits: list[dict] = []
    seen: set[str] = set()
    total = 0
    for entry in _iter_entries(domain):
        total += 1
        src = str(entry.get("src") or "")
        if not src:
            continue
        key = src.lower()
        if key in seen:
            continue
        found = (src in text) if entry.get("case_sensitive") else (key in lowered)
        if found:
            seen.add(key)
            hits.append(
                {
                    "src": src,
                    "dst": entry.get("dst", ""),
                    "note": entry.get("note", ""),
                    "domain": entry.get("domain", ""),
                }
            )
        if len(hits) >= top_k:
            break
    return {"hits": hits, "total_terms": total}


@mcp.tool()
def style_get(domain: str = "") -> dict:
    """返回风格规则与禁译表（可按 domain=配置名限定，否则聚合所有配置并去重）。"""
    style_rules: list[str] = []
    do_not_translate: list[str] = []
    for summary in knowledge.list_profiles():
        name = summary.get("name")
        if domain and name != domain:
            continue
        profile = knowledge.load_profile(name)
        if not profile:
            continue
        style_rules.extend(profile.get("style_rules", []))
        do_not_translate.extend(profile.get("do_not_translate", []))
    return {
        "style_rules": list(dict.fromkeys(style_rules)),
        "do_not_translate": list(dict.fromkeys(do_not_translate)),
    }


if __name__ == "__main__":
    mcp.run()
