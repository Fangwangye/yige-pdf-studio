# MCP 接入规范（二期 · 草案）

> 状态：规划中，依赖一期结构化知识库落地。本文定义契约，便于先行设计。

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

## 配置

接入设置新增「知识源」：`本地知识库` / `MCP`（填 endpoint）。质检报告增加「MCP 命中 N 条 / 已回退本地」。

## 与现有架构的关系

- 不替换翻译引擎，只替换「知识从哪来」。
- 仍复用 `default_translation_prompt` 的注入位，只是知识来源从静态文本变为检索结果。
