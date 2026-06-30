# Skill 接入规范（三期 · 已实现）

> 状态：✅ 已落地。Skill 目录：`.claude/skills/translate-pdf/`（`SKILL.md` + 入口脚本 `translate_pdf.py`，仅标准库）。复用运行中的 HTTP API（创建任务→轮询→取报告），不重写引擎。下文为契约说明。

## 目标

把整条翻译流水线封装成 **Claude Skill**，让 Claude Code 等 agent 直接调度，融入更大的 AI 工作流（例：「读这篇 PDF，翻译方法章节并总结」）。

## 形态

- 一个 skill 目录：`SKILL.md`（触发说明 + 用法）+ 入口脚本。
- skill **不重写引擎**，而是调用一/二期的 HTTP API（创建任务 → 轮询 → 取报告）。

## 触发条件（SKILL.md 描述）

当用户意图为「翻译某个 PDF / 用某知识库翻译 / 评估译文质量」时触发。

## 输入输出契约

```jsonc
// 输入
{
  "pdf_path": "papers/llm.pdf",
  "source_language": "en",
  "target_language": "zh",
  "knowledge_name": "学术论文",   // 引用服务端知识库
  "quality_mode": "quality"
}
// 输出
{
  "job_id": "…",
  "state": "succeeded",
  "output_pdf": "storage/outputs/{job_id}.pdf",
  "report": { "pages": 12, "glossary_hits": 34, "warnings": [] }
}
```

## 执行流程

1. 校验 PDF 与知识库存在。
2. `POST /api/translate`（带 `knowledge_name`）。
3. 轮询 `GET /api/jobs/{id}` 至终态。
4. 拉 `GET /api/jobs/{id}/report`，把质检结论返回给调用方。
5. 失败时把 `error` 与建议（换引擎/降质量模式）回传。

## 与 MCP 的关系

- **MCP（二期）= 知识从哪来**（数据层，翻译过程内部使用）。
- **Skill（三期）= 谁来发起翻译**（编排层，翻译过程外部调度）。
- 二者正交：skill 触发的翻译，内部仍可用 MCP 检索知识。

## 安全

- 仅操作工作目录内文件，复用 `_validate_job_id` 等既有校验。
- API Key 由服务端配置注入，不在 skill 输入里明文传递。
