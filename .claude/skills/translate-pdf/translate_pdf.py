#!/usr/bin/env python3
"""译格 PDF Studio · 翻译流水线 Skill 入口（三期）。

复用运行中的 HTTP API：创建任务 → 轮询状态 → 取质检报告，输出结构化结果。
只用标准库，无需额外依赖。需要后端已在运行（默认 http://127.0.0.1:8010）。

示例：
    python translate_pdf.py --file paper.pdf --provider argos
    python translate_pdf.py --file paper.pdf --provider openai_compatible \\
        --base-url https://api.deepseek.com/v1 --model deepseek-v4-pro \\
        --api-key sk-xxx --knowledge 学术论文
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path


def _post_multipart(url: str, fields: dict[str, str], file_field: str, file_path: Path) -> dict:
    boundary = uuid.uuid4().hex
    parts: list[bytes] = []
    for key, value in fields.items():
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
        parts.append(f"{value}\r\n".encode())
    parts.append(f"--{boundary}\r\n".encode())
    parts.append(
        f'Content-Disposition: form-data; name="{file_field}"; filename="{file_path.name}"\r\n'.encode()
    )
    parts.append(b"Content-Type: application/pdf\r\n\r\n")
    parts.append(file_path.read_bytes())
    parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url) as resp:
        return json.load(resp)


def main() -> int:
    parser = argparse.ArgumentParser(description="Translate a PDF via 译格 PDF Studio API.")
    parser.add_argument("--file", required=True, help="待翻译 PDF 路径")
    parser.add_argument("--server", default="http://127.0.0.1:8010", help="后端地址")
    parser.add_argument("--source", default="en")
    parser.add_argument("--target", default="zh")
    parser.add_argument(
        "--provider",
        default="argos",
        choices=["argos", "openai_compatible", "mock"],
        help="argos=离线无需Key；openai_compatible=需Key；mock=仅复制版式",
    )
    parser.add_argument("--knowledge", default="", help="知识库配置名（仅 openai_compatible 生效）")
    parser.add_argument("--knowledge-source", default="local", choices=["local", "mcp"])
    parser.add_argument("--quality", default="quality", choices=["quality", "balanced", "fast"])
    parser.add_argument("--base-url", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--timeout", type=float, default=1800.0, help="最长等待秒数")
    args = parser.parse_args()

    pdf_path = Path(args.file).expanduser().resolve()
    if not pdf_path.exists():
        print(json.dumps({"ok": False, "error": f"文件不存在：{pdf_path}"}, ensure_ascii=False))
        return 2
    server = args.server.rstrip("/")

    # 健康检查
    try:
        _get_json(f"{server}/api/jobs?limit=1")
    except (urllib.error.URLError, OSError) as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": f"无法连接后端 {server}：{exc}. 请先启动："
                    "python -m uvicorn app.main:app --host 127.0.0.1 --port 8010",
                },
                ensure_ascii=False,
            )
        )
        return 3

    fields = {
        "provider": args.provider,
        "source_language": args.source,
        "target_language": args.target,
        "quality_mode": args.quality,
        "knowledge_name": args.knowledge,
        "knowledge_source": args.knowledge_source,
        "base_url": args.base_url,
        "model": args.model,
        "api_key": args.api_key,
    }
    try:
        created = _post_multipart(f"{server}/api/translate", fields, "file", pdf_path)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "ignore")
        print(json.dumps({"ok": False, "error": f"创建任务失败：{detail}"}, ensure_ascii=False))
        return 4

    job_id = created["job_id"]
    status_url = f"{server}{created['status_url']}"
    print(f"[skill] 任务已创建 job_id={job_id}，轮询中…", file=sys.stderr)

    deadline = time.monotonic() + args.timeout
    job: dict = {}
    while time.monotonic() < deadline:
        time.sleep(args.poll_interval)
        try:
            job = _get_json(f"{status_url}?t={uuid.uuid4().hex}")
        except (urllib.error.URLError, OSError):
            continue
        state = job.get("state")
        if state in ("queued", "running"):
            tail = (job.get("log_tail") or "").strip().splitlines()[-1:] or [""]
            print(f"[skill] {state} … {tail[0][:80]}", file=sys.stderr)
            continue
        break
    else:
        print(json.dumps({"ok": False, "job_id": job_id, "error": "等待超时"}, ensure_ascii=False))
        return 5

    state = job.get("state")
    if state != "succeeded":
        print(
            json.dumps(
                {"ok": False, "job_id": job_id, "state": state, "error": job.get("error")},
                ensure_ascii=False,
            )
        )
        return 6

    report = {}
    try:
        report = _get_json(f"{server}/api/jobs/{job_id}/report")
    except (urllib.error.URLError, OSError):
        pass

    stats = job.get("stats") or {}
    result = {
        "ok": True,
        "job_id": job_id,
        "state": state,
        "source_filename": job.get("source_filename"),
        "download_url": f"{server}/api/files/{job_id}",
        "preview_url": f"{server}/api/preview/{job_id}",
        "output_pdf": f"storage/outputs/{job_id}.pdf",
        "stats": {
            "pages": stats.get("pages"),
            "engine": stats.get("engine"),
            "glossary_hits": stats.get("glossary_hits"),
            "knowledge_source": stats.get("knowledge_source"),
            "fallback_pages": stats.get("fallback_pages"),
            "quality_warnings": [w.get("page") for w in (stats.get("quality_warnings") or [])],
        },
        "checks": [
            {"name": c.get("name"), "status": c.get("status"), "detail": c.get("detail")}
            for c in (report.get("checks") or [])
        ],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
