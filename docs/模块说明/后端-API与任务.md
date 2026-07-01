# 后端 · API 与任务（app/main.py）

## 职责
FastAPI 应用：接收上传、创建后台翻译任务、持久化任务状态、提供预览/下载与质检报告，并把 `static/` 挂为根静态站点。

## 路由
见 [接入规范/HTTP-API.md](../接入规范/HTTP-API.md)。`StaticFiles` 挂在 `/`（`html=True`），所以 `/api/*` 之外的路径回落到前端。

## 后台任务
- `POST /api/translate` 立即写入 `queued` 状态并返回，`BackgroundTasks` 异步执行 `_run_translation_job`，避免长翻译阻塞 HTTP。
- `_run_translation_job`：置 `running` → 调 `copy_pdf_without_translation`（mock）或 `translate_with_pdf2zh` → 置 `succeeded`/`failed`。`log_callback` 实时回写 `log_tail` 供前端轮询。

## 状态持久化
- 每个任务一份 `storage/jobs/{job_id}.json`。
- **原子写**：`_write_job_status` 写临时文件再 `replace`；Windows 文件锁用 `_replace_with_retry` 重试。
- **并发安全**：`_job_status_lock(job_id)` 给每个任务一把 `RLock`，`_patch_job_status` 读改写串行化。

## 参数归一
- `normalize_language_code`：`中文/英文/...` → `zh/en/...`。
- `thread_count_for_quality_mode`：`quality/balanced/fast` → `1/2/4`。
- `parse_page_list`：`"2,4-5"`（含中文逗号）→ 去重排序的页码元组。

## 安全
- `_validate_job_id`：仅允许字母数字与 `-`，挡路径穿越。
- 仅接受 `.pdf`。

## 维护注意
- 新增翻译参数：同时改 form 参数、`Pdf2zhConfig`、`settings` 快照三处。
- 一期知识库迁服务端时，CRUD 写入复用本文件的原子写 + 锁机制。
