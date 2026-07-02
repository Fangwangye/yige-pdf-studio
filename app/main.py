from __future__ import annotations

import asyncio
import json
import mimetypes
import shutil
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import knowledge
from . import sections as doc_sections
from .pdf2zh_engine import (
    Pdf2zhConfig,
    Pdf2zhError,
    copy_pdf_without_translation,
    translate_with_pdf2zh,
)
from fastapi import Body


BASE_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = BASE_DIR / "storage"
UPLOAD_DIR = STORAGE_DIR / "uploads"
OUTPUT_DIR = STORAGE_DIR / "outputs"
WORK_DIR = STORAGE_DIR / "work"
JOB_DIR = STORAGE_DIR / "jobs"
_JOB_STATUS_LOCKS: dict[str, threading.RLock] = {}
_JOB_STATUS_LOCKS_LOCK = threading.Lock()

mimetypes.add_type("text/javascript", ".mjs")  # 保证 pdf.js 的 .mjs 以模块类型返回

app = FastAPI(title="PDF Translate")


@app.post("/api/translate")
async def translate_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    provider: str = Form("mock"),
    source_language: str = Form("en"),
    target_language: str = Form("中文"),
    api_key: str | None = Form(None),
    base_url: str | None = Form(None),
    model: str | None = Form(None),
    layout_engine: str = Form("babeldoc"),
    quality_mode: str = Form("quality"),
    thread_count: int = Form(0),
    preserve_toc: bool = Form(True),
    protected_pages: str | None = Form(None),
    knowledge_base: str | None = Form(None),
    knowledge_name: str | None = Form(None),
    knowledge_source: str = Form("local"),
    document_type: str = Form(""),
    keep_sections: str | None = Form(None),
    improve_pagebreak: bool = Form(False),
    capture_tm: bool = Form(True),
) -> dict[str, object]:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    job_id = uuid.uuid4().hex
    input_path = UPLOAD_DIR / f"{job_id}.pdf"
    output_path = OUTPUT_DIR / f"{job_id}.pdf"
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    JOB_DIR.mkdir(parents=True, exist_ok=True)

    with input_path.open("wb") as target:
        shutil.copyfileobj(file.file, target)

    knowledge_profile = knowledge.load_profile(knowledge_name) if knowledge_name else None
    config = Pdf2zhConfig(
        provider="argos" if provider == "argos" else "openai_compatible",
        source_language=normalize_language_code(source_language, fallback="en"),
        target_language=normalize_language_code(target_language, fallback="zh"),
        api_key=api_key,
        base_url=base_url,
        model=model,
        thread_count=resolve_thread_count(quality_mode, thread_count),
        use_babeldoc=layout_engine != "legacy",
        preserve_toc=preserve_toc,
        protected_pages=parse_page_list(protected_pages),
        knowledge_base=knowledge_base,
        knowledge_profile=knowledge_profile,
        knowledge_source="mcp" if knowledge_source == "mcp" else "local",
        document_type=document_type or "",
        keep_sections=doc_sections.normalize_keep_sections(keep_sections),
        improve_layout=bool(improve_pagebreak),
        capture_tm=bool(capture_tm) and bool(knowledge_profile),
    )
    _write_job_status(
        job_id,
        {
            "job_id": job_id,
            "state": "queued",
            "provider": provider,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "source_filename": file.filename,
            "source_url": f"/api/source/{job_id}",
            "download_url": f"/api/preview/{job_id}",
            "attachment_url": f"/api/files/{job_id}",
            "preview_url": f"/api/preview/{job_id}",
            "status_url": f"/api/jobs/{job_id}",
            "settings": {
                "source_language": normalize_language_code(source_language, fallback="en"),
                "target_language": normalize_language_code(target_language, fallback="zh"),
                "provider": provider,
                "model": model,
                "base_url": base_url,
                "layout_engine": layout_engine,
                "quality_mode": quality_mode,
                "thread_count": resolve_thread_count(quality_mode, thread_count),
                "preserve_toc": preserve_toc,
                "protected_pages": protected_pages or "",
                "knowledge_name": (knowledge_profile or {}).get("name") if knowledge_profile else None,
                "knowledge_source": "mcp" if knowledge_source == "mcp" else "local",
                "document_type": document_type or "",
                "keep_sections": list(doc_sections.normalize_keep_sections(keep_sections)),
                "knowledge_base_applied": bool(
                    knowledge_profile or (knowledge_base and knowledge_base.strip())
                ),
            },
            "stats": None,
            "error": None,
            "log_tail": "",
        },
    )
    background_tasks.add_task(
        _run_translation_job,
        job_id,
        provider,
        input_path,
        output_path,
        config,
    )

    return {
        "job_id": job_id,
        "state": "queued",
        "download_url": f"/api/preview/{job_id}",
        "attachment_url": f"/api/files/{job_id}",
        "preview_url": f"/api/preview/{job_id}",
        "source_url": f"/api/source/{job_id}",
        "status_url": f"/api/jobs/{job_id}",
    }


@app.get("/api/jobs")
def list_jobs(limit: int = 20) -> dict[str, object]:
    JOB_DIR.mkdir(parents=True, exist_ok=True)
    jobs: list[dict[str, object]] = []
    for path in JOB_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        jobs.append(_job_summary(data))
    jobs.sort(key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""), reverse=True)
    return {"jobs": jobs[: max(1, min(limit, 100))]}


@app.get("/api/jobs/{job_id}")
def get_job_status(job_id: str) -> dict[str, object]:
    _validate_job_id(job_id)
    path = _job_status_path(job_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Job not found.")
    return _read_json_retry(path)


@app.get("/api/jobs/{job_id}/report")
def get_job_report(job_id: str) -> dict[str, object]:
    _validate_job_id(job_id)
    path = _job_status_path(job_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Job not found.")
    return _build_quality_report(_read_json_retry(path))


@app.get("/api/files/{job_id}")
def get_output_pdf(job_id: str) -> FileResponse:
    return _pdf_response(job_id, inline=False)


@app.get("/api/preview/{job_id}")
def preview_output_pdf(job_id: str) -> FileResponse:
    return _pdf_response(job_id, inline=True)


@app.get("/api/source/{job_id}")
def preview_source_pdf(job_id: str) -> FileResponse:
    _validate_job_id(job_id)
    input_path = UPLOAD_DIR / f"{job_id}.pdf"
    if not input_path.exists():
        raise HTTPException(status_code=404, detail="Source PDF not found.")
    return FileResponse(
        input_path,
        media_type="application/pdf",
        filename=f"source-{job_id}.pdf",
        content_disposition_type="inline",
    )


def _delete_job_files(job_id: str) -> bool:
    """删除某任务的状态、上传、输出与工作目录，返回是否删到东西。"""
    found = False
    for path in (JOB_DIR / f"{job_id}.json", UPLOAD_DIR / f"{job_id}.pdf", OUTPUT_DIR / f"{job_id}.pdf"):
        if path.exists():
            found = True
            try:
                path.unlink()
            except OSError:
                pass
    work = WORK_DIR / job_id
    if work.exists():
        found = True
        shutil.rmtree(work, ignore_errors=True)
    return found


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str) -> dict[str, object]:
    _validate_job_id(job_id)
    if not _delete_job_files(job_id):
        raise HTTPException(status_code=404, detail="Job not found.")
    return {"deleted": job_id}


@app.delete("/api/jobs")
def clear_jobs(state: str | None = None) -> dict[str, object]:
    """清空任务；传 state=failed 只清失败任务。"""
    JOB_DIR.mkdir(parents=True, exist_ok=True)
    count = 0
    for path in list(JOB_DIR.glob("*.json")):
        job_id = path.stem
        if state:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if data.get("state") != state:
                continue
        if _delete_job_files(job_id):
            count += 1
    return {"deleted": count}


def _pdf_response(job_id: str, inline: bool) -> FileResponse:
    _validate_job_id(job_id)

    output_path = OUTPUT_DIR / f"{job_id}.pdf"
    if not output_path.exists():
        raise HTTPException(status_code=404, detail="Translated PDF not found.")

    return FileResponse(
        output_path,
        media_type="application/pdf",
        filename=f"translated-{job_id}.pdf",
        content_disposition_type="inline" if inline else "attachment",
    )


@app.get("/api/knowledge")
def list_knowledge() -> dict[str, object]:
    return {"profiles": knowledge.list_profiles()}


@app.get("/api/knowledge/{name}")
def get_knowledge(name: str) -> dict[str, object]:
    profile = knowledge.load_profile(name)
    if profile is None:
        raise HTTPException(status_code=404, detail="Knowledge profile not found.")
    return profile


@app.put("/api/knowledge/{name}")
def put_knowledge(name: str, payload: dict = Body(...)) -> dict[str, object]:
    if not name.strip():
        raise HTTPException(status_code=400, detail="Profile name is required.")
    return knowledge.save_profile(name, payload)


@app.delete("/api/knowledge/{name}")
def remove_knowledge(name: str) -> dict[str, object]:
    deleted = knowledge.delete_profile(name)
    if not deleted:
        raise HTTPException(status_code=404, detail="Knowledge profile not found.")
    return {"deleted": name}


@app.post("/api/knowledge/import")
def import_knowledge(payload: dict = Body(...)) -> dict[str, object]:
    name = str(payload.get("name") or "导入知识库").strip()
    return knowledge.save_profile(name, payload)


@app.post("/api/knowledge/import-csv")
def import_knowledge_csv(payload: dict = Body(...)) -> dict[str, object]:
    name = str(payload.get("name") or "导入术语").strip()
    glossary = knowledge.csv_to_glossary(str(payload.get("csv") or ""))
    if not glossary:
        raise HTTPException(status_code=400, detail="CSV 未解析到任何术语。")
    existing = knowledge.load_profile(name) or {}
    merged = knowledge.merge_glossary(existing.get("glossary") or [], glossary)
    data = {
        "name": name,
        "glossary": merged,
        "style_rules": existing.get("style_rules") or [],
        "do_not_translate": existing.get("do_not_translate") or [],
    }
    profile = knowledge.save_profile(name, data)
    return {**profile, "imported": len(glossary)}


@app.get("/api/knowledge/{name}/export.csv")
def export_knowledge_csv(name: str) -> PlainTextResponse:
    profile = knowledge.load_profile(name)
    if profile is None:
        raise HTTPException(status_code=404, detail="Knowledge profile not found.")
    return PlainTextResponse(knowledge.profile_to_csv(profile), media_type="text/csv")


@app.post("/api/knowledge/import-tbx")
def import_knowledge_tbx(payload: dict = Body(...)) -> dict[str, object]:
    name = str(payload.get("name") or "导入术语").strip()
    glossary = knowledge.tbx_to_glossary(str(payload.get("tbx") or ""))
    if not glossary:
        raise HTTPException(status_code=400, detail="TBX 未解析到任何术语。")
    existing = knowledge.load_profile(name) or {}
    data = {
        "name": name,
        "glossary": knowledge.merge_glossary(existing.get("glossary") or [], glossary),
        "style_rules": existing.get("style_rules") or [],
        "do_not_translate": existing.get("do_not_translate") or [],
        "tm": existing.get("tm") or [],
    }
    return {**knowledge.save_profile(name, data), "imported": len(glossary)}


@app.get("/api/knowledge/{name}/export.tbx")
def export_knowledge_tbx(name: str) -> PlainTextResponse:
    profile = knowledge.load_profile(name)
    if profile is None:
        raise HTTPException(status_code=404, detail="Knowledge profile not found.")
    return PlainTextResponse(knowledge.glossary_to_tbx(profile), media_type="application/xml")


@app.post("/api/knowledge/import-tmx")
def import_knowledge_tmx(payload: dict = Body(...)) -> dict[str, object]:
    name = str(payload.get("name") or "导入记忆").strip()
    tm = knowledge.tmx_to_tm(str(payload.get("tmx") or ""))
    if not tm:
        raise HTTPException(status_code=400, detail="TMX 未解析到任何句对。")
    existing = knowledge.load_profile(name) or {}
    data = {
        "name": name,
        "glossary": existing.get("glossary") or [],
        "style_rules": existing.get("style_rules") or [],
        "do_not_translate": existing.get("do_not_translate") or [],
        "tm": knowledge.merge_tm(existing.get("tm") or [], tm),
    }
    return {**knowledge.save_profile(name, data), "imported": len(tm)}


@app.get("/api/knowledge/{name}/export.tmx")
def export_knowledge_tmx(name: str) -> PlainTextResponse:
    profile = knowledge.load_profile(name)
    if profile is None:
        raise HTTPException(status_code=404, detail="Knowledge profile not found.")
    return PlainTextResponse(knowledge.tm_to_tmx(profile), media_type="application/xml")


app.mount("/", StaticFiles(directory=BASE_DIR / "static", html=True), name="static")


def _writeback_tm(config: Pdf2zhConfig, stats: object) -> None:
    """把翻译过程中捕获的句对合并回所选知识库的翻译记忆（保留最新 2000 条）。"""
    if not isinstance(stats, dict):
        return
    captured = stats.get("tm_captured") if isinstance(stats.get("tm_captured"), list) else []
    profile = config.knowledge_profile
    name = (profile or {}).get("name") if profile else None
    stats.pop("tm_captured", None)
    if not captured or not name:
        return
    current = knowledge.load_profile(name)
    if current is None:
        return
    merged = knowledge.merge_tm(current.get("tm") or [], captured)
    if len(merged) > 2000:
        merged = merged[-2000:]
    knowledge.save_profile(name, {**current, "tm": merged})
    stats["tm_written"] = len(captured)


async def _run_translation_job(
    job_id: str,
    provider: str,
    input_path: Path,
    output_path: Path,
    config: Pdf2zhConfig,
) -> None:
    _patch_job_status(job_id, state="running", started_at=_now_iso(), updated_at=_now_iso())

    def update_log(log_tail: str) -> None:
        _patch_job_status(job_id, state="running", updated_at=_now_iso(), log_tail=log_tail)

    try:
        if provider == "mock":
            stats = await asyncio.to_thread(copy_pdf_without_translation, input_path, output_path)
        else:
            stats = await translate_with_pdf2zh(
                input_path=input_path,
                output_path=output_path,
                work_dir=WORK_DIR / job_id,
                config=config,
                log_callback=update_log,
            )
        _writeback_tm(config, stats)
        _patch_job_status(
            job_id,
            state="succeeded",
            updated_at=_now_iso(),
            finished_at=_now_iso(),
            stats=stats,
            error=None,
        )
    except (Pdf2zhError, Exception) as exc:
        _patch_job_status(
            job_id,
            state="failed",
            updated_at=_now_iso(),
            finished_at=_now_iso(),
            error=str(exc),
        )


def _validate_job_id(job_id: str) -> None:
    if not job_id.replace("-", "").isalnum():
        raise HTTPException(status_code=400, detail="Invalid job id.")


def _job_status_path(job_id: str) -> Path:
    return JOB_DIR / f"{job_id}.json"


def _read_job_status(job_id: str) -> dict[str, object]:
    path = _job_status_path(job_id)
    return json.loads(path.read_text(encoding="utf-8"))


def _read_json_retry(path: Path, attempts: int = 12) -> dict[str, object]:
    """读 job 状态文件；容忍写入瞬间的文件锁/半写状态并重试。"""
    for attempt in range(attempts):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (PermissionError, json.JSONDecodeError):
            if attempt == attempts - 1:
                raise
            time.sleep(0.05 * (attempt + 1))
    raise RuntimeError("unreachable")


def _write_job_status(job_id: str, data: dict[str, object]) -> None:
    with _job_status_lock(job_id):
        JOB_DIR.mkdir(parents=True, exist_ok=True)
        path = _job_status_path(job_id)
        temp_path = JOB_DIR / f".{job_id}.{uuid.uuid4().hex}.tmp"
        try:
            temp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            _replace_with_retry(temp_path, path)
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except PermissionError:
                    pass


def _patch_job_status(job_id: str, **updates: object) -> None:
    with _job_status_lock(job_id):
        data = _read_job_status(job_id)
        data.update(updates)
        _write_job_status(job_id, data)


def _job_status_lock(job_id: str) -> threading.RLock:
    with _JOB_STATUS_LOCKS_LOCK:
        lock = _JOB_STATUS_LOCKS.get(job_id)
        if lock is None:
            lock = threading.RLock()
            _JOB_STATUS_LOCKS[job_id] = lock
        return lock


def _replace_with_retry(source: Path, target: Path, attempts: int = 12) -> None:
    for attempt in range(attempts):
        try:
            source.replace(target)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.05 * (attempt + 1))


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _job_summary(data: dict[str, object]) -> dict[str, object]:
    stats = data.get("stats") if isinstance(data.get("stats"), dict) else {}
    settings = data.get("settings") if isinstance(data.get("settings"), dict) else {}
    warnings = stats.get("quality_warnings") if isinstance(stats, dict) else []
    fallback_pages = stats.get("fallback_pages") if isinstance(stats.get("fallback_pages"), list) else []
    return {
        "job_id": data.get("job_id"),
        "state": data.get("state"),
        "source_filename": data.get("source_filename"),
        "created_at": data.get("created_at"),
        "updated_at": data.get("updated_at"),
        "finished_at": data.get("finished_at"),
        "pages": stats.get("pages") if isinstance(stats, dict) else None,
        "engine": stats.get("engine") if isinstance(stats, dict) else None,
        "quality_warnings_count": len(warnings) if isinstance(warnings, list) else 0,
        "fallback_pages": fallback_pages,
        "model": settings.get("model"),
        "quality_mode": settings.get("quality_mode"),
        "preview_url": data.get("preview_url"),
        "source_url": data.get("source_url") or f"/api/source/{data.get('job_id')}",
        "status_url": data.get("status_url"),
        "report_url": f"/api/jobs/{data.get('job_id')}/report",
    }


def _build_quality_report(data: dict[str, object]) -> dict[str, object]:
    stats = data.get("stats") if isinstance(data.get("stats"), dict) else {}
    settings = data.get("settings") if isinstance(data.get("settings"), dict) else {}
    warnings = stats.get("quality_warnings") if isinstance(stats, dict) and isinstance(stats.get("quality_warnings"), list) else []
    fallback_pages = stats.get("fallback_pages") if isinstance(stats, dict) and isinstance(stats.get("fallback_pages"), list) else []
    preserved_pages = stats.get("preserved_pages") if isinstance(stats, dict) and isinstance(stats.get("preserved_pages"), list) else []
    knowledge_applied = bool(stats.get("knowledge_base_applied") or settings.get("knowledge_base_applied"))
    glossary_hits = stats.get("glossary_hits") if isinstance(stats.get("glossary_hits"), int) else 0
    knowledge_name = settings.get("knowledge_name")
    source_used = stats.get("knowledge_source") or settings.get("knowledge_source") or "local"
    source_label = {
        "mcp": "MCP 检索",
        "mcp-fallback-local": "MCP→本地回退",
        "local": "本地知识库",
        "legacy": "旧版文本",
    }.get(str(source_used), "本地知识库")
    kept_sections = stats.get("kept_sections") if isinstance(stats.get("kept_sections"), dict) else {}
    doc_type_raw = stats.get("document_type") or settings.get("document_type") or ""
    doc_type_label = {
        "academic": "学术论文",
        "technical": "技术文档",
        "contract": "商务合同",
        "general": "通用",
    }.get(str(doc_type_raw), "")
    checks = [
        {
            "name": "页面生成",
            "status": "pass" if data.get("state") == "succeeded" and stats.get("pages") else "pending",
            "detail": f"{stats.get('pages', 0)} 页" if stats.get("pages") else "尚未生成译文 PDF",
        },
        {
            "name": "占位符/乱码扫描",
            "status": "pass" if not warnings else "warn",
            "detail": "未发现疑似异常" if not warnings else f"{len(warnings)} 页需要复查",
        },
        {
            "name": "异常页自动回退",
            "status": "pass" if fallback_pages else "idle",
            "detail": f"已回退 {', '.join(map(str, fallback_pages))} 页" if fallback_pages else "未触发",
        },
        {
            "name": "跨页连续性",
            "status": "pass" if stats.get("page_bridges") else "idle",
            "detail": f"识别 {stats.get('page_bridges', 0)} 处跨页上下文",
        },
        {
            "name": "知识库",
            "status": "pass" if knowledge_applied else "idle",
            "detail": (
                f"{knowledge_name or '用户知识库'} · {source_label} · 命中术语 {glossary_hits} 个"
                if knowledge_applied
                else "未应用"
            ),
        },
        {
            "name": "翻译记忆",
            "status": "pass" if stats.get("tm_written") else "idle",
            "detail": (
                f"本次回写 {stats.get('tm_written')} 条句对"
                if stats.get("tm_written")
                else "未回写"
            ),
        },
        {
            "name": "分段保留",
            "status": "pass" if kept_sections else "idle",
            "detail": (
                (f"{doc_type_label}：" if doc_type_label else "")
                + "；".join(
                    f"{label} {pgs[0]}-{pgs[-1]} 页" for label, pgs in kept_sections.items() if pgs
                )
                if kept_sections
                else (f"{doc_type_label} · 全文翻译" if doc_type_label else "未设置")
            ),
        },
    ]
    return {
        "job_id": data.get("job_id"),
        "state": data.get("state"),
        "source_filename": data.get("source_filename"),
        "settings": settings,
        "stats": stats,
        "checks": checks,
        "warnings": warnings,
        "fallback_pages": fallback_pages,
        "preserved_pages": preserved_pages,
        "error": data.get("error"),
    }


def thread_count_for_quality_mode(value: str | None) -> int:
    mapping = {
        "quality": 4,
        "balanced": 8,
        "fast": 16,
    }
    return mapping.get((value or "quality").strip().lower(), 4)


def resolve_thread_count(quality_mode: str | None, override: int) -> int:
    """显式并发优先；否则按质量模式取默认。范围钳制到 1..32。"""
    count = override if override and override > 0 else thread_count_for_quality_mode(quality_mode)
    return max(1, min(count, 32))


def normalize_language_code(value: str | None, fallback: str) -> str:
    if not value:
        return fallback
    normalized = value.strip().lower()
    mapping = {
        "中文": "zh",
        "简体中文": "zh",
        "zh-cn": "zh",
        "zh_hans": "zh",
        "english": "en",
        "英文": "en",
        "英语": "en",
        "日文": "ja",
        "日语": "ja",
        "韩文": "ko",
        "韩语": "ko",
    }
    return mapping.get(normalized, normalized or fallback)


def parse_page_list(value: str | None) -> tuple[int, ...]:
    if not value:
        return ()
    pages: set[int] = set()
    for raw_part in value.replace("，", ",").split(","):
        part = raw_part.strip()
        if not part:
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            start = int(start_text)
            end = int(end_text)
            pages.update(range(min(start, end), max(start, end) + 1))
        else:
            pages.add(int(part))
    return tuple(sorted(page for page in pages if page > 0))
