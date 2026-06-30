from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import fitz

from .knowledge import render_profile


@dataclass(frozen=True)
class Pdf2zhConfig:
    source_language: str = "en"
    target_language: str = "zh"
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
    thread_count: int = 1
    use_babeldoc: bool = True
    preserve_toc: bool = True
    protected_pages: tuple[int, ...] = ()
    prompt: str | None = None
    knowledge_base: str | None = None
    knowledge_profile: dict | None = None
    knowledge_source: str = "local"  # "local" | "mcp"


class Pdf2zhError(RuntimeError):
    pass


async def translate_with_pdf2zh(
    input_path: Path,
    output_path: Path,
    work_dir: Path,
    config: Pdf2zhConfig,
    log_callback: Callable[[str], None] | None = None,
) -> dict[str, object]:
    return await asyncio.to_thread(
        _translate_with_pdf2zh_sync,
        input_path,
        output_path,
        work_dir,
        config,
        log_callback,
    )


def _translate_with_pdf2zh_sync(
    input_path: Path,
    output_path: Path,
    work_dir: Path,
    config: Pdf2zhConfig,
    log_callback: Callable[[str], None] | None = None,
) -> dict[str, object]:
    if not config.api_key:
        raise Pdf2zhError("API key is required.")
    if not config.base_url:
        raise Pdf2zhError("Base URL is required.")
    if not config.model:
        raise Pdf2zhError("Model is required.")

    pdf2zh_cmd = shutil.which("pdf2zh")
    if not pdf2zh_cmd:
        raise Pdf2zhError("pdf2zh is not installed. Run: python -m pip install pdf2zh")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    home_dir = work_dir.parent.parent / "pdf2zh-home"
    pdf2zh_output_dir = work_dir / "out"
    home_dir.mkdir(parents=True, exist_ok=True)
    pdf2zh_output_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home_dir),
            "USERPROFILE": str(home_dir),
            "OPENAILIKED_BASE_URL": config.base_url.rstrip("/"),
            "OPENAILIKED_API_KEY": config.api_key,
            "OPENAILIKED_MODEL": config.model,
            "PYTHONIOENCODING": "utf-8",
        }
    )

    service = f"openailiked:{config.model}"
    if config.use_babeldoc:
        command = [
            _python_for_pdf2zh(pdf2zh_cmd),
            "-m",
            "app.pdf2zh_babeldoc_cli",
            str(input_path),
            "--service",
            service,
            "--lang-in",
            config.source_language,
            "--lang-out",
            config.target_language,
            "--output",
            str(pdf2zh_output_dir),
            "--thread",
            str(config.thread_count),
            "--ignore-cache",
        ]
    else:
        command = [
            pdf2zh_cmd,
            str(input_path),
            "--service",
            service,
            "--lang-in",
            config.source_language,
            "--lang-out",
            config.target_language,
            "--output",
            str(pdf2zh_output_dir),
            "--thread",
            str(config.thread_count),
            "--ignore-cache",
        ]
    document_context = build_document_context(input_path, config.target_language)
    knowledge_text, glossary_hits, knowledge_source = _resolve_knowledge(
        config, document_context, log_callback=log_callback
    )
    prompt_path = write_prompt_file(
        work_dir,
        config.prompt
        or default_translation_prompt(
            config.target_language,
            document_context,
            knowledge_text,
        ),
    )
    if prompt_path:
        command.extend(["--prompt", str(prompt_path)])

    process_output = _run_command(command, env, log_callback=log_callback)

    source_stem = input_path.stem
    mono_candidates = sorted(pdf2zh_output_dir.glob(f"{source_stem}*mono*.pdf"))
    if not mono_candidates:
        mono_candidates = sorted(pdf2zh_output_dir.glob("*.pdf"))
    if not mono_candidates:
        raise Pdf2zhError(
            "pdf2zh completed but no output PDF was found.\n"
            f"output:\n{process_output}"
        )

    shutil.copyfile(mono_candidates[0], output_path)
    fallback_pages: list[int] = []
    fallback_error = None
    initial_quality_warnings = scan_pdf_quality(output_path)
    if config.use_babeldoc and initial_quality_warnings:
        fallback_pages = [int(warning["page"]) for warning in initial_quality_warnings]
        try:
            fallback_output_path, fallback_output = run_legacy_fallback(
                input_path=input_path,
                work_dir=work_dir,
                config=config,
                env=env,
                pages=fallback_pages,
                prompt_path=prompt_path,
                log_callback=log_callback,
            )
            replace_pages(output_path, fallback_output_path, fallback_pages)
            process_output = f"{process_output}\n\n--- Legacy fallback ---\n{fallback_output}"
        except Exception as exc:
            fallback_error = str(exc)

    preserved_pages = preserve_pages(
        input_path,
        output_path,
        auto_toc=config.preserve_toc,
        protected_pages=config.protected_pages,
    )
    quality_warnings = scan_pdf_quality(output_path)
    return {
        "pages": _count_pages(output_path),
        "engine": "pdf2zh-babeldoc" if config.use_babeldoc else "pdf2zh",
        "preserved_pages": preserved_pages,
        "fallback_pages": fallback_pages,
        "fallback_error": fallback_error,
        "quality_warnings": quality_warnings,
        "context_terms": document_context["terms"],
        "page_bridges": len(document_context["page_bridges"]),
        "knowledge_base_applied": bool(knowledge_text),
        "glossary_hits": glossary_hits,
        "knowledge_source": knowledge_source,
        "log_tail": _tail(process_output),
    }


def copy_pdf_without_translation(input_path: Path, output_path: Path) -> dict[str, object]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(input_path, output_path)
    return {
        "pages": _count_pages(output_path),
        "engine": "copy",
        "text_blocks": 0,
    }


def default_translation_prompt(
    target_language: str,
    document_context: dict[str, object] | None = None,
    knowledge_base: str | None = None,
) -> str:
    context_block = ""
    if document_context:
        title = document_context.get("title") or ""
        abstract = document_context.get("abstract") or ""
        terms = document_context.get("terms") or []
        page_bridges = document_context.get("page_bridges") or []
        if title or abstract or terms or page_bridges:
            context_block = (
                "Document-level shared context. Apply this consistently across every "
                "independent text block in this PDF:\n"
            )
            if title:
                context_block += f"- Title / topic: {title}\n"
            if abstract:
                context_block += f"- Abstract gist: {abstract}\n"
            if terms:
                context_block += "- Recurring terms to keep consistent: " + ", ".join(terms[:40]) + "\n"
            if page_bridges:
                context_block += (
                    "- Cross-page continuity hints. These show source text that appears "
                    "around page breaks; use them only to keep sentence logic and pronoun "
                    "references coherent when translating a matching fragment:\n"
                )
                for bridge in page_bridges[:24]:
                    context_block += (
                        f"  Page {bridge['from_page']} -> {bridge['to_page']}: "
                        f"...{bridge['tail']} || {bridge['head']}...\n"
                    )
            context_block += "\n"

    knowledge_block = ""
    if knowledge_base:
        knowledge_block = (
            "User/project translation knowledge base. These instructions have higher "
            "priority than the automatically extracted document context, unless they "
            "conflict with placeholder/formula preservation rules:\n"
            f"{knowledge_base}\n\n"
        )

    return (
        "You are a professional PDF translation engine. Translate from ${lang_in} "
        "to ${lang_out}. Output only the translated text.\n"
        f"{context_block}"
        f"{knowledge_block}"
        "Rules:\n"
        "1. Preserve every placeholder and formula token exactly, including {{v0}}, "
        "{{v1}}, {v*}, <b0>, </b0>, HTML-like tags, citations, numbers, units, "
        "figure/table labels, and math symbols.\n"
        "2. Do not translate, transliterate, split, reorder, or explain placeholder "
        "fragments.\n"
        "3. Preserve the full meaning of each sentence. Repair normal PDF hyphenation "
        "mentally, but do not invent content.\n"
        "4. Use concise, publication-quality Simplified Chinese when ${lang_out} is "
        "zh or Chinese.\n\n"
        "5. Rewrite, not word-for-word translate: reorganize sentence rhythm and word "
        "order naturally for the target language while keeping all facts, numbers, "
        "logical relations, and citations intact.\n"
        "6. Maintain terminology consistency with the document-level context. For "
        "specialized terms, use the standard target-language translation; when a "
        "source term is important or ambiguous, keep the original in parentheses on "
        "first mention.\n"
        "7. Match the register of an academic paper: rigorous, formal, citation-aware, "
        "and free of casual wording or unexplained embellishment.\n\n"
        "8. Treat page boundaries carefully. If the source text starts or ends in the "
        "middle of a sentence or paragraph, translate it as a continuing fragment; do "
        "not force a full-sentence ending, add a summary, or restart the logic. Use the "
        "cross-page continuity hints only as context, not as extra text to translate.\n\n"
        "Source Text:\n${text}\n\nTranslated Text:"
    )


def build_document_context(input_path: Path, target_language: str) -> dict[str, object]:
    doc = fitz.open(input_path)
    try:
        all_page_texts = [page.get_text("text") for page in doc]
    finally:
        doc.close()

    page_texts = all_page_texts[:12]
    full_text = "\n".join(all_page_texts)
    front_text = "\n".join(page_texts)
    title = _extract_title(front_text)
    abstract = _extract_abstract(front_text)
    terms = _extract_recurring_terms(full_text)
    page_bridges = _extract_page_bridges(all_page_texts)
    return {
        "title": _compact_text(title, 220),
        "abstract": _compact_text(abstract, 800),
        "terms": terms,
        "page_bridges": page_bridges,
        "target_language": target_language,
        "full_text": full_text,
    }


def _resolve_knowledge(
    config: "Pdf2zhConfig",
    document_context: dict[str, object],
    log_callback: Callable[[str], None] | None = None,
) -> tuple[str, int, str]:
    """决定本次翻译注入的知识库文本、命中术语数与实际使用的来源。

    来源优先级：
    - knowledge_source == "mcp"：MCP 实时检索；失败/为空时回退本地结构化知识库。
    - 否则：本地结构化知识库（按文档命中过滤）；再退旧版纯文本。
    """
    document_text = str(document_context.get("full_text") or "")

    def _local() -> tuple[str, int, str]:
        if config.knowledge_profile:
            text, hits = render_profile(config.knowledge_profile, document_text)
            return text, hits, "local"
        return normalize_knowledge_base(config.knowledge_base), 0, "legacy"

    if config.knowledge_source == "mcp":
        try:
            from .mcp_client import retrieve_knowledge

            domain = (config.knowledge_profile or {}).get("name", "") if config.knowledge_profile else ""
            text, hits = retrieve_knowledge(document_text, domain=domain)
            if text:
                if log_callback:
                    log_callback(f"MCP 知识检索命中 {hits} 个术语。")
                return text, hits, "mcp"
            if log_callback:
                log_callback("MCP 检索为空，回退本地知识库。")
        except Exception as exc:  # noqa: BLE001 —— 任何失败都回退，不阻塞翻译
            if log_callback:
                log_callback(f"MCP 检索失败，回退本地知识库：{exc}")
        text, hits, _ = _local()
        return text, hits, "mcp-fallback-local"

    return _local()


def _extract_title(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""

    filtered = [
        line
        for line in lines[:30]
        if not line.lower().startswith(("arxiv:", "abstract", "contents"))
        and not re.fullmatch(r"[\d\s.]+", line)
        and len(line) >= 8
    ]
    return " ".join(filtered[:2])


def _extract_abstract(text: str) -> str:
    match = re.search(
        r"\bAbstract\b\s*(.+?)(?:\n\s*(?:1\s+Introduction|Introduction|Contents)\b)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return ""
    return match.group(1)


def _extract_recurring_terms(text: str, limit: int = 50) -> list[str]:
    stop_words = {
        "The",
        "This",
        "That",
        "These",
        "Those",
        "Figure",
        "Table",
        "Appendix",
        "Section",
        "Introduction",
        "Conclusion",
        "References",
        "Abstract",
        "URL",
        "PROMPT",
        "FILENAME",
        "LICENSE",
        "OPTIONS",
    }
    patterns = [
        r"\b[A-Z][A-Za-z0-9]+(?:[- ][A-Z]?[A-Za-z0-9]+){1,5}\b",
        r"\b[A-Z]{2,}(?:[- ][A-Z0-9]{2,})*\b",
        r"\b[a-z]+(?:-[a-z]+){1,4}\b",
    ]
    counts: dict[str, int] = {}
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            term = _compact_text(match.group(0), 80)
            if not _is_useful_term(term, stop_words):
                continue
            counts[term] = counts.get(term, 0) + 1

    ranked = sorted(counts.items(), key=lambda item: (item[1], len(item[0])), reverse=True)
    return [term for term, count in ranked if count >= 2][:limit]


def _is_useful_term(term: str, stop_words: set[str]) -> bool:
    lowered = term.lower()
    if any(noise in lowered for noise in ["http", "www.", "url", "filename", "prompt"]):
        return False
    if term in stop_words:
        return False
    words = term.split()
    if words and words[0] in stop_words:
        return False
    if len(term) < 3 or len(term) > 80:
        return False
    if re.fullmatch(r"\d+(?:[- ]\d+)*", term):
        return False
    return any(char.isupper() for char in term) or "-" in term


def _compact_text(value: str, limit: int) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def _extract_page_bridges(page_texts: list[str], limit: int = 24) -> list[dict[str, object]]:
    bridges: list[dict[str, object]] = []
    for index in range(len(page_texts) - 1):
        tail = _page_tail_fragment(page_texts[index])
        head = _page_head_fragment(page_texts[index + 1])
        if not tail or not head:
            continue
        if not _looks_like_continued_text(tail, head):
            continue
        bridges.append(
            {
                "from_page": index + 1,
                "to_page": index + 2,
                "tail": _compact_text(tail, 180),
                "head": _compact_text(head, 180),
            }
        )
        if len(bridges) >= limit:
            break
    return bridges


def _page_tail_fragment(text: str) -> str:
    lines = _content_lines(text)
    if not lines:
        return ""
    candidates = _drop_page_number_lines(lines)
    return " ".join(candidates[-3:])


def _page_head_fragment(text: str) -> str:
    lines = _content_lines(text)
    if not lines:
        return ""
    candidates = _drop_page_number_lines(lines)
    return " ".join(candidates[:3])


def _content_lines(text: str) -> list[str]:
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    return [
        line
        for line in lines
        if not line.lower().startswith(("arxiv:", "contents", "references"))
        and not re.fullmatch(r"\d+", line)
        and not _is_visual_caption_line(line)
    ]


def _drop_page_number_lines(lines: list[str]) -> list[str]:
    return [line for line in lines if not re.fullmatch(r"\d{1,4}", line.strip())]


def _looks_like_continued_text(tail: str, head: str) -> bool:
    if len(tail) < 20 or len(head) < 20:
        return False
    if _is_section_heading(head) or _is_section_heading(tail):
        return False
    tail_ends_open = not re.search(r"[.!?。！？:：;；)]\s*$", tail)
    head_starts_continuation = bool(re.match(r"^[a-z,;:)\]]", head.strip()))
    tail_has_hyphenation = bool(re.search(r"-\s*$", tail))
    return tail_ends_open or head_starts_continuation or tail_has_hyphenation


def _is_section_heading(value: str) -> bool:
    stripped = value.strip()
    if re.match(r"^\d+(?:\.\d+)*\.?\s+[A-Z\u4e00-\u9fff]", stripped):
        return True
    if re.match(r"^(Appendix|References|Acknowledg|Abstract|Conclusion)\b", stripped, flags=re.IGNORECASE):
        return True
    return False


def _is_visual_caption_line(value: str) -> bool:
    stripped = value.strip()
    if re.match(r"^\([a-z]\)\s+", stripped, flags=re.IGNORECASE):
        return True
    if re.match(r"^(Figure|Fig\.|Table)\s+\d+\b", stripped, flags=re.IGNORECASE):
        return True
    if re.match(r"^(Category|Subcategory|Metric|Dataset)\b", stripped, flags=re.IGNORECASE):
        return True
    return False


def write_prompt_file(work_dir: Path, prompt: str | None) -> Path | None:
    if not prompt:
        return None
    prompt_path = work_dir / "prompt.txt"
    prompt_path.write_text(prompt, encoding="utf-8")
    return prompt_path


def normalize_knowledge_base(value: str | None, limit: int = 6000) -> str:
    if not value:
        return ""
    normalized = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    normalized = "\n".join(line.rstrip() for line in normalized.splitlines())
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip() + "\n[Knowledge base truncated to fit prompt budget.]"


def _python_for_pdf2zh(pdf2zh_cmd: str) -> str:
    pdf2zh_path = Path(pdf2zh_cmd)
    scripts_dir = pdf2zh_path.parent
    candidate = scripts_dir.parent / ("python.exe" if os.name == "nt" else "python")
    if candidate.exists():
        return str(candidate)
    return sys.executable


def run_legacy_fallback(
    input_path: Path,
    work_dir: Path,
    config: Pdf2zhConfig,
    env: dict[str, str],
    pages: list[int],
    prompt_path: Path | None,
    log_callback: Callable[[str], None] | None = None,
) -> tuple[Path, str]:
    pdf2zh_cmd = shutil.which("pdf2zh")
    if not pdf2zh_cmd:
        raise Pdf2zhError("pdf2zh is not installed. Run: python -m pip install pdf2zh")

    fallback_dir = work_dir / "legacy-fallback"
    fallback_dir.mkdir(parents=True, exist_ok=True)
    command = [
        pdf2zh_cmd,
        str(input_path),
        "--service",
        f"openailiked:{config.model}",
        "--lang-in",
        config.source_language,
        "--lang-out",
        config.target_language,
        "--output",
        str(fallback_dir),
        "--thread",
        "1",
        "--pages",
        ",".join(str(page) for page in pages),
        "--ignore-cache",
    ]
    if prompt_path:
        command.extend(["--prompt", str(prompt_path)])

    process_output = _run_command(command, env, log_callback=log_callback)
    source_stem = input_path.stem
    mono_candidates = sorted(fallback_dir.glob(f"{source_stem}*mono*.pdf"))
    if not mono_candidates:
        mono_candidates = sorted(fallback_dir.glob("*.pdf"))
    if not mono_candidates:
        raise Pdf2zhError("pdf2zh fallback completed but no output PDF was found.")
    return mono_candidates[0], process_output


def replace_pages(target_path: Path, source_path: Path, pages: list[int]) -> None:
    target = fitz.open(target_path)
    source = fitz.open(source_path)
    try:
        valid_pages = [
            page
            for page in sorted(set(pages))
            if 1 <= page <= len(target) and page <= len(source)
        ]
        if not valid_pages:
            return
        for page in valid_pages:
            page_index = page - 1
            target.delete_page(page_index)
            target.insert_pdf(source, from_page=page_index, to_page=page_index, start_at=page_index)
        temp_path = target_path.with_suffix(".fallback.tmp.pdf")
        target.save(temp_path, garbage=4, deflate=True)
    finally:
        target.close()
        source.close()
    temp_path.replace(target_path)


def _run_command(
    command: list[str],
    env: dict[str, str],
    log_callback: Callable[[str], None] | None = None,
) -> str:
    process = subprocess.Popen(
        command,
        cwd=str(Path(__file__).resolve().parent.parent),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    output_lines: list[str] = []
    assert process.stdout is not None
    try:
        for line in process.stdout:
            output_lines.append(line)
            if log_callback:
                log_callback(_tail("".join(output_lines), limit=3000))
        return_code = process.wait(timeout=60 * 60)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        raise Pdf2zhError("pdf2zh timed out after 60 minutes.") from exc

    process_output = "".join(output_lines)
    if return_code != 0:
        raise Pdf2zhError(_format_process_error(return_code, process_output))
    return process_output


def _count_pages(path: Path) -> int:
    doc = fitz.open(path)
    try:
        return len(doc)
    finally:
        doc.close()


def scan_pdf_quality(path: Path) -> list[dict[str, object]]:
    doc = fitz.open(path)
    warnings: list[dict[str, object]] = []
    placeholder_pattern = re.compile(r"(\{\{?v[\d*]*\}?\}?|</?b\d+>)")
    mojibake_chars = set("ÃÂÄÅÐÑÒÓÔÕÖØÙÚÛÜÝÞßàáâãäåæçèéêëìíîïðñòóôõöøùúûüýþÿ�")
    try:
        for page_index, page in enumerate(doc, start=1):
            text = page.get_text("text")
            if not text.strip():
                continue

            reasons: list[str] = []
            placeholders = placeholder_pattern.findall(text)
            replacement_count = text.count("\ufffd")
            mojibake_count = sum(1 for char in text if char in mojibake_chars)

            if placeholders:
                reasons.append("unresolved translation placeholder")
            if replacement_count:
                reasons.append("replacement character")
            if mojibake_count >= 10:
                reasons.append("mojibake-like characters")

            if reasons:
                warnings.append(
                    {
                        "page": page_index,
                        "reasons": reasons,
                        "placeholder_count": len(placeholders),
                        "replacement_count": replacement_count,
                        "mojibake_like_count": mojibake_count,
                    }
                )
    finally:
        doc.close()
    return warnings


def preserve_pages(
    input_path: Path,
    output_path: Path,
    auto_toc: bool = True,
    protected_pages: tuple[int, ...] = (),
    max_scan_pages: int = 8,
) -> list[int]:
    page_indexes = set(detect_toc_pages(input_path, max_scan_pages=max_scan_pages) if auto_toc else [])
    page_indexes.update(page - 1 for page in protected_pages if page > 0)
    if not page_indexes:
        return []

    source = fitz.open(input_path)
    target = fitz.open(output_path)
    valid_page_indexes = [
        page_index
        for page_index in sorted(page_indexes)
        if page_index < len(source) and page_index < len(target)
    ]
    if not valid_page_indexes:
        source.close()
        target.close()
        return []

    try:
        for page_index in valid_page_indexes:
            target.delete_page(page_index)
            target.insert_pdf(source, from_page=page_index, to_page=page_index, start_at=page_index)

        temp_path = output_path.with_suffix(".toc.tmp.pdf")
        target.save(temp_path, garbage=4, deflate=True)
    finally:
        source.close()
        target.close()

    temp_path.replace(output_path)
    return [page_index + 1 for page_index in valid_page_indexes]


def detect_toc_pages(input_path: Path, max_scan_pages: int = 8) -> list[int]:
    doc = fitz.open(input_path)
    toc_pages: list[int] = []
    try:
        for page_index in range(min(max_scan_pages, len(doc))):
            text = doc[page_index].get_text("text")
            if _looks_like_toc_page(text):
                toc_pages.append(page_index)
    finally:
        doc.close()
    return toc_pages


def _looks_like_toc_page(text: str) -> bool:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return False

    joined = "\n".join(lines).lower()
    has_title = any(
        marker in joined
        for marker in ["contents", "table of contents", "目录", "目 录"]
    )
    numbered_entries = sum(1 for line in lines if _is_toc_like_line(line))
    page_number_lines = sum(1 for line in lines if line.isdigit())
    dotted_entries = sum(1 for line in lines if "." in line and any(char.isdigit() for char in line[-4:]))

    if not has_title:
        return False
    return numbered_entries >= 1 or page_number_lines >= 3 or dotted_entries >= 1


def _is_toc_like_line(line: str) -> bool:
    stripped = line.strip()
    if len(stripped) < 3:
        return False
    starts_section = stripped[0].isdigit() or stripped[:2].upper().startswith("A.")
    ends_page = stripped[-1].isdigit()
    has_section_number = "." in stripped[:12] or stripped[0].isdigit()
    return starts_section and ends_page and has_section_number


def _format_process_error(return_code: int, process_output: str) -> str:
    return (
        "pdf2zh failed.\n"
        f"exit_code: {return_code}\n"
        f"output:\n{_tail(process_output)}"
    )


def _tail(value: str, limit: int = 4000) -> str:
    value = value.strip()
    if len(value) <= limit:
        return value
    return value[-limit:]
