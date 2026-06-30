# HTTP API

后端 `app/main.py`（FastAPI），默认 `127.0.0.1:8010`。

## 现有接口

### POST `/api/translate`
上传 PDF 并创建后台翻译任务。`multipart/form-data`：

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `file` | 必填 | PDF 文件 |
| `provider` | `mock` | `openai_compatible` / `mock` |
| `source_language` / `target_language` | `en` / `中文` | 经 `normalize_language_code` 归一 |
| `api_key` / `base_url` / `model` | — | OpenAI-compatible 凭证 |
| `layout_engine` | `babeldoc` | `babeldoc` / `legacy` |
| `quality_mode` | `quality` | `quality`/`balanced`/`fast` → 线程 1/2/4 |
| `preserve_toc` | `true` | 保留目录页 |
| `protected_pages` | — | 如 `2,4-5`，经 `parse_page_list` |
| `knowledge_base` | — | 知识库文本（当前为纯文本） |

返回：`{ job_id, state, status_url, preview_url, download_url, attachment_url, source_url }`。

### GET `/api/jobs?limit=20`
任务列表（摘要），按更新时间倒序。

### GET `/api/jobs/{job_id}`
单任务完整状态（见 [数据模型.md](../公共设计/数据模型.md) 的 Job）。

### GET `/api/jobs/{job_id}/report`
派生质检报告。

### GET `/api/source/{job_id}` · `/api/preview/{job_id}` · `/api/files/{job_id}`
原文 PDF（inline）/ 译文 PDF（inline）/ 译文 PDF（attachment 下载）。

> `job_id` 经 `_validate_job_id` 校验（仅字母数字与 `-`），防路径穿越。

## 知识库 CRUD（一期 · 已实现）

由 `app/knowledge.py` 提供，存储 `storage/knowledge/{name}.json`（原子写）。空目录首次访问自动种子 3 套默认配置。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/knowledge` | 列出所有配置（名称/版本/术语数/更新时间） |
| GET | `/api/knowledge/{name}` | 取单套结构化配置 |
| PUT | `/api/knowledge/{name}` | 新建/更新（JSON body 为 `KnowledgeProfile`，自动规范化） |
| DELETE | `/api/knowledge/{name}` | 删除 |
| POST | `/api/knowledge/import` | 导入 JSON（兼容旧版 `{name, content}` 纯文本） |

`POST /api/translate` 新增 form 字段 **`knowledge_name`**：传入后端按名加载结构化配置，翻译时**按文档命中过滤术语**再注入提示词，命中数写入 `stats.glossary_hits`（旧 `knowledge_base` 纯文本字段仍兼容）。

## 约定

- 所有响应 UTF-8、`ensure_ascii=false`。
- 长任务一律走「创建任务 + 轮询」，不在请求里同步等待翻译完成。
