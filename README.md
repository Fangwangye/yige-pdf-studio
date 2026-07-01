# 译格 PDF Studio

本项目是一个本地 Web 版 PDF 翻译工作台：左侧预览原 PDF，右侧预览翻译后的 PDF，并支持接入 OpenAI-compatible 三方翻译 API。

## 功能

- 左右双栏 PDF 预览：原文 PDF 与译文 PDF 同屏对照，单栏可一键放大（⛶ / Esc 还原）。
- 对照模式：基于 pdf.js 的双栏视图，支持左右**同步滚动**（可关闭改为各自独立滚动）。
- 多翻译后端：OpenAI-compatible 网关（DeepSeek 等）、Argos 离线翻译（开源 NMT，无需 Key）、Mock 版式测试。
- BabelDOC/pdf2zh 版式重建：尽量保留图片、表格、公式和页面布局；默认关闭 BabelDOC 的推广水印。
- 文档类型与分段翻译：按类型（学术论文/技术文档/合同/通用）勾选「保留原文」的段落——整页型（目录/参考文献/附录）自动检测页码保留，同页型（摘要/公式/代码）走提示词禁译。
- 并发可调：质量/均衡/速度模式（4/8/16 线程）或直接指定并发线程数（1–32），显著提升长文档速度。
- 结构化翻译知识库：术语对照表 + 风格规则 + 禁译表，存服务端、可保存多套、导入导出；翻译时按文档命中过滤术语再注入提示词。
- MCP 术语检索（可选）：内置术语 MCP Server，翻译前实时检索术语；不可用时自动回退本地知识库。在「接入设置 → 知识来源」切换。
- Claude Skill：`.claude/skills/translate-pdf/` 把整条翻译流水线封装成可被 Claude Code 调度的 skill。
- 文档级上下文：自动抽取标题、摘要和高频术语，注入翻译提示词。
- 跨页连续性：自动识别页尾到下一页页首的断句上下文，减少长文逻辑断裂。
- 质量检查：扫描未解析占位符、乱码样字符和替换字符。
- 异常页回退：对异常页可自动使用 legacy 引擎重跑并替换回最终 PDF。
- 后台任务：长 PDF 翻译不阻塞 HTTP 请求，前端轮询任务状态。

## 技术方案

- 后端：FastAPI
- PDF 处理：PDFMathTranslate / pdf2zh / BabelDOC
- 前端：原生 HTML/CSS/JavaScript
- 编码：所有源码使用 UTF-8

PDF 生成策略调用 `pdf2zh` 与 BabelDOC：先做版面解析，再翻译并重新渲染 PDF。Mock 模式只复制原 PDF，用于确认左右预览和下载流程。

## 运行

```powershell
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8010
```

打开：

```text
http://127.0.0.1:8010/
```

## 任务流程

翻译接口采用后台任务模式，避免长 PDF 翻译导致 HTTP 请求超时：

- `POST /api/translate`：上传 PDF 并创建任务，返回 `job_id`、`status_url`、`download_url`
- `GET /api/jobs/{job_id}`：查询任务状态，状态包括 `queued`、`running`、`succeeded`、`failed`
- `GET /api/preview/{job_id}`：内嵌预览译文 PDF
- `GET /api/files/{job_id}`：下载译文 PDF

前端会自动轮询任务状态，只有 `succeeded` 后才加载右侧 PDF。失败时会展示 `pdf2zh/BabelDOC` 的错误摘要。

## 三方 API

当前通过 `pdf2zh` 的 `openailiked` 服务实现 `OpenAI-compatible` 模式。Base URL 填到 `/v1` 这一层，例如：

```text
https://api.example.com/v1
```

没有 API Key 时可以选择 `Mock 版式测试`，它不会翻译，只复制原 PDF 到右侧，验证界面流程。

## 知识库

知识库为结构化数据，存服务端 `storage/knowledge/{name}.json`（空目录首次访问自动种子默认配置），结构：

```jsonc
{
  "name": "计算机与AI",
  "glossary": [
    { "src": "large language model", "dst": "大语言模型",
      "domain": "AI", "pos": "", "definition": "",
      "status": "preferred", "case_sensitive": false, "note": "" }
  ],
  "style_rules": ["使用准确、简洁的技术中文"],
  "do_not_translate": ["代码", "命令", "公式"]
}
```

- 每条术语支持**专业字段**：`domain`（领域）、`pos`（词性）、`definition`（定义）、`status`（`preferred` 推荐 / `forbidden` 禁译 / `deprecated` 弃用）。`status=forbidden` 的术语会自动作为「保留原文」注入。
- 前端在「知识库」视图用术语表格（原文/译文/领域/状态/备注/大小写）+ 风格/禁译编辑，CRUD 走 `/api/knowledge*`。
- **标准格式互通**：支持 CSV 导入/导出（`POST /api/knowledge/import-csv`、`GET /api/knowledge/{name}/export.csv`），列名兼容中英；无表头时按 `原文,译文,领域,备注` 解析。
- 内置一套原创的 **`计算机与AI`** 领域种子术语库（自建，无第三方版权）。其它开源术语库（如机器之心 AI 术语库 CC BY-NC-SA、微软 Terminology）请自行按各自许可证用 CSV/TBX 导入。
- 翻译时只把**实际出现在文档**中的术语注入提示词，命中数见质检报告（`stats.glossary_hits`）。
- 导入兼容旧版 `{name, content}` 纯文本（自动解析「术语/风格/禁译」段落）。
- 知识库优先级高于自动抽取的文档上下文，但不覆盖占位符、公式、引用保护规则。

详见 [docs/模块说明/知识库设计.md](docs/模块说明/知识库设计.md) 与 [docs/接入规范/HTTP-API.md](docs/接入规范/HTTP-API.md)。

## 当前限制

- `pdf2zh` 首次运行会初始化模型、字体和缓存，可能比较慢。
- 输出质量主要取决于 PDF 复杂度和翻译模型；PDF 天然不是结构化编辑格式，无法对所有文件承诺 100% 完全一致。
- **跨页/跨栏衔接**：保版式模式下，双栏论文中一段跨栏或跨页的文字会被切块分别翻译，视觉上可能出现断裂或页眉重渲染——这是 BabelDOC 保版式路线的固有限制，暂无法根治（「改善页衔接」实验开关仅能减少段内碎片，不解决跨栏跨页）。
- 扫描版 PDF 需要 OCR 路径；后续可继续接 BabelDOC/OCR workaround 配置。
- 并发线程越大越快，但可能触发翻译服务商的限流；默认质量模式为 4 线程，可在「接入设置」调整。
