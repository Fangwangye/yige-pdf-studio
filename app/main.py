from __future__ import annotations

import asyncio
import json
import shutil
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .pdf2zh_engine import (
    Pdf2zhConfig,
    Pdf2zhError,
    copy_pdf_without_translation,
    translate_with_pdf2zh,
)


BASE_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = BASE_DIR / "storage"
UPLOAD_DIR = STORAGE_DIR / "uploads"
OUTPUT_DIR = STORAGE_DIR / "outputs"
WORK_DIR = STORAGE_DIR / "work"
JOB_DIR = STORAGE_DIR / "jobs"
_JOB_STATUS_LOCKS: dict[str, threading.RLock] = {}
_JOB_STATUS_LOCKS_LOCK = threading.Lock()

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
    preserve_toc: bool = Form(True),
    protected_pages: str | None = Form(None),
    knowledge_base: str | None = Form(None),
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

    config = Pdf2zhConfig(
        source_language=normalize_language_code(source_language, fallback="en"),
        target_language=normalize_language_code(target_language, fallback="zh"),
        api_key=api_key,
        base_url=base_url,
        model=model,
        use_babeldoc=layout_engine != "legacy",
        preserve_toc=preserve_toc,
        protected_pages=parse_page_list(protected_pages),
        knowledge_base=knowledge_base,
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
            "download_url": f"/api/preview/{job_id}",
            "attachment_url": f"/api/files/{job_id}",
            "preview_url": f"/api/preview/{job_id}",
            "status_url": f"/api/jobs/{job_id}",
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
        "status_url": f"/api/jobs/{job_id}",
    }


@app.get("/api/jobs/{job_id}")
def get_job_status(job_id: str) -> dict[str, object]:
    _validate_job_id(job_id)
    path = _job_status_path(job_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Job not found.")
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/api/files/{job_id}")
def get_output_pdf(job_id: str) -> FileResponse:
    return _pdf_response(job_id, inline=False)


@app.get("/api/preview/{job_id}")
def preview_output_pdf(job_id: str) -> FileResponse:
    return _pdf_response(job_id, inline=True)


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


app.mount("/", StaticFiles(directory=BASE_DIR / "static", html=True), name="static")


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
