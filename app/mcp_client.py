"""MCP 客户端（二期）。

翻译前连接术语知识 MCP Server，检索文档命中的术语与风格规则，
渲染成提示词片段。任何失败都抛异常，由调用方回退一期本地知识库。
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from . import knowledge

BASE_DIR = Path(__file__).resolve().parent.parent

# 默认启动 stdio 方式的内置术语 server；可用环境变量覆盖命令。
_DEFAULT_COMMAND = os.environ.get("YIGE_MCP_COMMAND", sys.executable)
_DEFAULT_ARGS = (
    os.environ.get("YIGE_MCP_ARGS", "").split()
    if os.environ.get("YIGE_MCP_ARGS")
    else ["-m", "mcp_server.glossary_server"]
)


def _result_data(result) -> dict:
    """从 CallToolResult 取结构化数据（优先 structuredContent，回退解析文本）。"""
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        return structured
    for item in getattr(result, "content", None) or []:
        text = getattr(item, "text", None)
        if text:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                continue
    return {}


async def _retrieve_async(document_text: str, domain: str, top_k: int) -> tuple[dict, dict]:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=_DEFAULT_COMMAND,
        args=_DEFAULT_ARGS,
        cwd=str(BASE_DIR),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            glossary_result = await session.call_tool(
                "glossary_search",
                {"text": document_text, "top_k": top_k, "domain": domain or ""},
            )
            style_result = await session.call_tool(
                "style_get", {"domain": domain or ""}
            )
            return _result_data(glossary_result), _result_data(style_result)


def retrieve_knowledge(
    document_text: str,
    domain: str = "",
    top_k: int = 40,
    timeout: float = 25.0,
) -> tuple[str, int]:
    """同步入口：返回 (提示词文本, 命中术语数)。失败抛异常。

    可在工作线程中调用（内部新建事件循环）。
    """

    async def _run() -> tuple[dict, dict]:
        return await asyncio.wait_for(_retrieve_async(document_text, domain, top_k), timeout)

    glossary_data, style_data = asyncio.run(_run())
    hits = glossary_data.get("hits") if isinstance(glossary_data, dict) else None
    hits = hits if isinstance(hits, list) else []
    pseudo_profile = {
        "glossary": hits,
        "style_rules": (style_data or {}).get("style_rules", []),
        "do_not_translate": (style_data or {}).get("do_not_translate", []),
    }
    # 已由 server 完成命中过滤，这里不再按文档过滤。
    text, _ = knowledge.render_profile(pseudo_profile, document_text=None)
    return text, len(hits)
