---
name: translate-pdf
description: Translate a PDF into another language while preserving layout, using the 译格 PDF Studio pipeline (BabelDOC layout reconstruction + glossary knowledge base). Use when the user wants to translate a PDF document, render a foreign-language PDF into Chinese (or another target), or run this project's translation flow on a file. Reuses the project's HTTP API end to end and returns a structured result (job id, output PDF path, quality report).
---

# translate-pdf

把整条「上传 → 文档级上下文抽取 → 知识库注入 → 翻译重排 → 质检」流水线，封装成一个可被调度的 skill。它**不重写引擎**，而是调用本项目运行中的 HTTP API。

## 何时使用
- 用户要翻译一个 PDF（如「把这篇论文翻成中文」「translate this PDF」）。
- 用户要用某套知识库 / 某个引擎跑这个项目的翻译流程。
- 用户要对译文做质检结论。

## 前置条件
后端必须在运行。若未运行，先启动（后台）：

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8010
```

脚本会先做健康检查，连不上会返回明确错误。

## 用法
入口脚本：`.claude/skills/translate-pdf/translate_pdf.py`（仅用标准库）。

```bash
# 离线、无需 Key（推荐默认；首次会联网下载 Argos 语言包）
python .claude/skills/translate-pdf/translate_pdf.py --file path/to/paper.pdf --provider argos

# OpenAI-compatible + 知识库（术语/风格生效）
python .claude/skills/translate-pdf/translate_pdf.py \
  --file path/to/paper.pdf \
  --provider openai_compatible \
  --base-url https://api.deepseek.com/v1 --model deepseek-v4-pro --api-key sk-xxx \
  --knowledge 学术论文 --knowledge-source local

# 仅验证版式/流程，不真正翻译
python .claude/skills/translate-pdf/translate_pdf.py --file path/to/paper.pdf --provider mock
```

### 关键参数
| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--file` | 必填 | 待翻译 PDF 路径 |
| `--provider` | `argos` | `argos`（离线无 Key）/ `openai_compatible`（需 Key）/ `mock` |
| `--source` / `--target` | `en` / `zh` | 源/目标语言 |
| `--knowledge` | 空 | 知识库配置名（**仅 openai_compatible 生效**；argos 是 NMT 不吃提示词） |
| `--knowledge-source` | `local` | `local` / `mcp`（MCP 检索，失败自动回退本地） |
| `--quality` | `quality` | `quality`/`balanced`/`fast` |
| `--server` | `http://127.0.0.1:8010` | 后端地址 |

## 输出
脚本向 stdout 打印结构化 JSON（进度走 stderr）：

```jsonc
{
  "ok": true,
  "job_id": "…",
  "state": "succeeded",
  "download_url": "http://127.0.0.1:8010/api/files/…",
  "output_pdf": "storage/outputs/{job_id}.pdf",
  "stats": { "pages": 12, "engine": "argos-babeldoc", "glossary_hits": 0, "knowledge_source": "none", "quality_warnings": [] },
  "checks": [ { "name": "占位符/乱码扫描", "status": "pass", "detail": "未发现疑似异常" } ]
}
```

退出码：`0` 成功；非 0 表示文件不存在/后端未启动/创建失败/超时/翻译失败（错误在 JSON 的 `error`）。

## 给 Claude 的执行建议
1. 确认 `--file` 路径存在；不确定服务商时默认用 `argos`（零配置）。
2. 需要术语/风格一致性时用 `openai_compatible` + `--knowledge`，并提醒用户准备 Base URL/Model/Key。
3. 运行后把 JSON 里的 `state`、`output_pdf`、`checks` 的结论转述给用户；失败则把 `error` 与建议（换引擎 / 降质量模式）一并说明。

## 关系
- 与 **MCP（二期）** 正交：MCP 决定「知识从哪来」，skill 决定「谁来发起翻译」。skill 触发的翻译内部仍可用 `--knowledge-source mcp`。
- 详见 [docs/接入规范/Skill接入规范.md](../../../docs/接入规范/Skill接入规范.md)。
