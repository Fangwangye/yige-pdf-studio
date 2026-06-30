# MCP 接入规范（二期 · 已实现）

> 状态：✅ 已落地。MCP Server：`mcp_server/glossary_server.py`（FastMCP，stdio）；MCP Client：`app/mcp_client.py`；引擎接线：`pdf2zh_engine._resolve_knowledge`。在「接入设置 → 知识来源」选 `MCP 检索` 即启用。下文为契约说明。

## 目标

把术语/风格知识从「每次塞进 prompt」改为「翻译时按段落实时检索」，支持大规模术语与多系统共享。本翻译服务作为 **MCP Client**，连接一个**术语知识 MCP Server**。

## Server 暴露的工具

### `glossary.search`
```jsonc
// input
{ "text": "We pre-train a large language model ...", "top_k": 20, "domain": "academic" }
// output
{ "hits": [ { "src": "large language model", "dst": "大语言模型", "score": 0.97, "note": "" } ] }
```

### `style.get`
```jsonc
// input
{ "domain": "academic" }
// output
{ "style_rules": ["使用正式流畅的学术中文"], "do_not_translate": ["公式", "引用"] }
```

## 调用时机

翻译每页（或每段）前：
1. 取该段源文本 → `glossary.search` 拿命中术语。
2. （首页/切换领域时）`style.get` 拿风格规则。
3. 把命中术语 + 风格规则注入该段 prompt。

## 降级策略（必须）

- MCP 不可用 / 超时 / 报错 → **自动回退一期本地知识库**，记录到 `stats`，不阻塞翻译。
- 检索为空 → 退化为仅风格规则。

## 实现现状

- **传输**：stdio。Client（`app/mcp_client.py`）按需用 `StdioServerParameters` 拉起内置 Server（`python -m mcp_server.glossary_server`），完成 `initialize` 后调用工具。可用环境变量 `YIGE_MCP_COMMAND` / `YIGE_MCP_ARGS` 覆盖启动命令（接外部 Server）。
- **术语源**：Server 复用一期 `storage/knowledge/*.json`；`domain` 传入当前选中的知识库名，做范围限定；空 `domain` 聚合全部配置。
- **检索时机**：翻译前用文档全文（`build_document_context` 的 `full_text`）一次性检索（pdf2zh 内部逐段翻译不暴露 hook，故在启动 pdf2zh 前注入）。
- **超时**：默认 25s（`retrieve_knowledge(timeout=...)`）。

## 配置

接入设置「知识来源」：`本地知识库` / `MCP 检索`。翻译时 form 传 `knowledge_source`。质检报告「知识库」项显示来源：`MCP 检索` / `MCP→本地回退` / `本地知识库`，并附命中术语数。

## 与现有架构的关系

- 不替换翻译引擎，只替换「知识从哪来」。
- 仍复用 `default_translation_prompt` 的注入位（`knowledge_block`），知识来源从本地结构化变为 MCP 检索结果，失败回退本地。
