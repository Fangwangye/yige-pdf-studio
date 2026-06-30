# PR 说明（可复用模板）

> 分支 `feature/knowledge-base-and-mcp` 的 PR 正文。创建 PR：
> <https://github.com/Fangwangye/yige-pdf-studio/pull/new/feature/knowledge-base-and-mcp>

**标题**：知识库结构化 + MCP 检索 + Argos 离线翻译 + 侧边栏 UI

---

## 概述
围绕「翻译质量可控性」推进三期能力，并重做 UI 与文档。分支含多个提交，可独立交付。

## 改动
### 1. UI 改版 + 文档
- 前端重构为左侧导航 + 工作区（5 个视图），所有元素 ID 保留，翻译/轮询逻辑不变。
- 新增 `docs/` 文档树：功能说明 / 公共设计 / 接入规范 / 模块说明（开发设计 + 用户手册）。

### 2. 一期：结构化知识库
- `KnowledgeProfile`（术语表 / 风格 / 禁译）+ 服务端存储 + CRUD API（`/api/knowledge*`）。
- 翻译时按文档命中过滤术语注入（`stats.glossary_hits`），前端术语表格编辑器，兼容旧纯文本导入。

### 3. 二期：MCP 术语检索
- 内置术语 MCP Server（FastMCP/stdio，`glossary_search` / `style_get`）+ MCP Client。
- 引擎接线，MCP 失败/超时**自动回退本地知识库**；质检报告显示知识来源。

### 4. Argos 离线翻译 provider
- 新 `provider=argos`，走 pdf2zh 内置 ArgosTranslator + 保留 BabelDOC 版式，无需 API Key。
- 修复 pdf2zh 1.9.11 ArgosTranslator 的导入笔误 bug。

### 5. 三期：Claude Skill 封装
- `.claude/skills/translate-pdf/`：把整条翻译流水线封装成 skill，复用 HTTP API（创建任务 → 轮询 → 取报告）。

## 验证
- 知识库 CRUD、MCP 全链路 + 失败回退、Argos 补丁生效、Skill 脚本端到端（mock），均已测；整站启动无报错、API 全 200。

## 已知限制
- Argos 首次需联网下载语言包；Argos 为 NMT，不吃提示词，知识库对其不生效。
- 真实翻译质量需本地配 Key / 装 argostranslate 后端到端实测。

🤖 Generated with [Claude Code](https://claude.com/claude-code)
