# MCP 术语服务（二期）

把术语/风格知识外置为可检索的 MCP 服务，翻译前实时检索注入，失败回退一期本地知识库。

## 组成

| 文件 | 角色 |
| --- | --- |
| `mcp_server/glossary_server.py` | MCP **Server**（FastMCP，stdio）。复用 `storage/knowledge/*.json` 作为术语源。 |
| `app/mcp_client.py` | MCP **Client**。按需 stdio 拉起 Server，检索并渲染成提示词文本。 |
| `app/pdf2zh_engine.py::_resolve_knowledge` | 接线点：决定本次用 MCP 还是本地，失败回退。 |

## Server 工具

- `glossary_search(text, top_k=40, domain="")`：返回原文出现在 `text` 中的术语条目（`domain` = 知识库名，限定范围；空则聚合全部）。
- `style_get(domain="")`：返回去重后的风格规则与禁译表。

返回值通过 FastMCP 的 `structuredContent` 传回；Client 优先读 `structuredContent`，回退解析文本 JSON。

## Client 流程（`retrieve_knowledge`）

1. `StdioServerParameters(command=python, args=["-m","mcp_server.glossary_server"], cwd=项目根)`，可用 `YIGE_MCP_COMMAND` / `YIGE_MCP_ARGS` 覆盖（接外部 Server）。
2. `stdio_client` + `ClientSession.initialize()` → `call_tool` 两个工具。
3. 把 hits + 风格规则拼成 `pseudo_profile`，复用 `knowledge.render_profile` 渲染（不再二次过滤，Server 已过滤）。
4. 默认超时 25s。在工作线程内用 `asyncio.run` 跑（新建事件循环，安全）。

## 回退语义（`_resolve_knowledge`）

| 情况 | `stats.knowledge_source` |
| --- | --- |
| MCP 检索成功且非空 | `mcp` |
| MCP 失败/超时/为空 → 本地结构化 | `mcp-fallback-local` |
| 知识来源=本地 | `local` |
| 仅旧版纯文本 | `legacy` |

回退过程通过 `log_callback` 写入任务日志，前端可见；不阻塞翻译。

## 测试要点

- 直接 import `mcp_server.glossary_server` 调函数验证检索逻辑。
- `app.mcp_client.retrieve_knowledge(...)` 验证 stdio 全链路。
- 设 `YIGE_MCP_COMMAND=不存在的命令` 验证回退路径。
