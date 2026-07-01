"""结构化翻译知识库（一期）。

数据模型、服务端存储（storage/knowledge/*.json）、旧纯文本兼容，
以及把知识库渲染成提示词片段（可按文档命中过滤术语）。
"""
from __future__ import annotations

import csv
import io
import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
KNOWLEDGE_DIR = BASE_DIR / "storage" / "knowledge"

SCHEMA_VERSION = 2
PROMPT_BUDGET = 6000


# --------------------------------------------------------------------------- #
# 默认知识库（首次启动种子）
# --------------------------------------------------------------------------- #
DEFAULT_PROFILES: list[dict[str, object]] = [
    {
        "name": "学术论文",
        "glossary": [
            {"src": "large language model", "dst": "大语言模型"},
            {"src": "scaling law", "dst": "缩放定律"},
            {"src": "pre-training", "dst": "预训练"},
            {"src": "fine-tuning", "dst": "微调"},
            {"src": "alignment", "dst": "对齐"},
        ],
        "style_rules": [
            "使用正式、流畅的学术中文，不要逐词硬翻，保持论文语气。",
            "模型名、数据集名、方法名和引用保留英文原文。",
            "首次出现的重要英文术语可采用“中文译名（English Term）”。",
        ],
        "do_not_translate": ["模型名", "数据集名", "方法名", "公式", "引用"],
    },
    {
        "name": "技术文档",
        "glossary": [
            {"src": "latency", "dst": "延迟"},
            {"src": "throughput", "dst": "吞吐量"},
            {"src": "deployment", "dst": "部署"},
        ],
        "style_rules": [
            "使用准确、简洁的技术中文。",
            "保留命令、代码、配置项、接口名和错误信息原文。",
            "不要扩写原文没有的操作步骤。",
        ],
        "do_not_translate": ["API", "SDK", "命令", "代码", "配置项", "错误信息"],
    },
    {
        "name": "商务合同",
        "glossary": [
            {"src": "party", "dst": "一方"},
            {"src": "agreement", "dst": "协议"},
            {"src": "liability", "dst": "责任"},
            {"src": "confidentiality", "dst": "保密"},
            {"src": "termination", "dst": "终止"},
        ],
        "style_rules": [
            "使用正式、稳健的法律/商务中文。",
            "保持条款编号、金额、日期和主体名称完全一致。",
            "不要弱化义务、限制、免责或条件。",
        ],
        "do_not_translate": ["条款编号", "金额", "日期", "主体名称"],
    },
    {
        # 原创整理的计算机 / AI 领域术语种子库（自建，无第三方版权）。
        "name": "计算机与AI",
        "glossary": [
            {"src": "large language model", "dst": "大语言模型", "domain": "AI"},
            {"src": "transformer", "dst": "Transformer", "domain": "AI", "status": "forbidden"},
            {"src": "attention", "dst": "注意力", "domain": "AI"},
            {"src": "self-attention", "dst": "自注意力", "domain": "AI"},
            {"src": "embedding", "dst": "嵌入", "domain": "AI"},
            {"src": "token", "dst": "词元", "domain": "NLP"},
            {"src": "tokenizer", "dst": "分词器", "domain": "NLP"},
            {"src": "fine-tuning", "dst": "微调", "domain": "AI"},
            {"src": "pre-training", "dst": "预训练", "domain": "AI"},
            {"src": "inference", "dst": "推理", "domain": "AI"},
            {"src": "prompt", "dst": "提示词", "domain": "AI"},
            {"src": "hallucination", "dst": "幻觉", "domain": "AI"},
            {"src": "reinforcement learning", "dst": "强化学习", "domain": "AI"},
            {"src": "gradient descent", "dst": "梯度下降", "domain": "ML"},
            {"src": "overfitting", "dst": "过拟合", "domain": "ML"},
            {"src": "regularization", "dst": "正则化", "domain": "ML"},
            {"src": "convolutional neural network", "dst": "卷积神经网络", "domain": "ML"},
            {"src": "recurrent neural network", "dst": "循环神经网络", "domain": "ML"},
            {"src": "backpropagation", "dst": "反向传播", "domain": "ML"},
            {"src": "benchmark", "dst": "基准测试", "domain": "AI"},
            {"src": "latency", "dst": "延迟", "domain": "系统"},
            {"src": "throughput", "dst": "吞吐量", "domain": "系统"},
            {"src": "concurrency", "dst": "并发", "domain": "系统"},
            {"src": "cache", "dst": "缓存", "domain": "系统"},
            {"src": "deployment", "dst": "部署", "domain": "工程"},
            {"src": "pipeline", "dst": "流水线", "domain": "工程"},
            {"src": "repository", "dst": "仓库", "domain": "工程"},
            {"src": "dependency", "dst": "依赖", "domain": "工程"},
            {"src": "middleware", "dst": "中间件", "domain": "工程"},
            {"src": "endpoint", "dst": "端点", "domain": "工程"},
            {"src": "load balancing", "dst": "负载均衡", "domain": "系统"},
            {"src": "scalability", "dst": "可扩展性", "domain": "系统"},
            {"src": "API", "dst": "API", "domain": "工程", "status": "forbidden"},
            {"src": "SDK", "dst": "SDK", "domain": "工程", "status": "forbidden"},
        ],
        "style_rules": [
            "使用准确、简洁的技术中文。",
            "保留命令、代码、配置项、接口名、库名和错误信息原文。",
            "首次出现的重要英文术语可采用“中文译名（English Term）”。",
        ],
        "do_not_translate": ["代码", "命令", "配置项", "接口名", "库名", "公式"],
    },
]


# --------------------------------------------------------------------------- #
# 规范化
# --------------------------------------------------------------------------- #
def _now() -> str:
    return datetime.now(UTC).isoformat()


def _clean_str(value: object, limit: int = 400) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    return text[:limit]


TERM_STATUSES = ("preferred", "forbidden", "deprecated")


def normalize_glossary(raw: object) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    if not isinstance(raw, list):
        return entries
    for item in raw:
        if not isinstance(item, dict):
            continue
        src = _clean_str(item.get("src"), 200)
        dst = _clean_str(item.get("dst"), 200)
        if not src:
            continue
        status = _clean_str(item.get("status"), 20).lower()
        if status not in TERM_STATUSES:
            status = "preferred"
        entries.append(
            {
                "src": src,
                "dst": dst,
                "domain": _clean_str(item.get("domain"), 60),
                "pos": _clean_str(item.get("pos"), 30),
                "definition": _clean_str(item.get("definition"), 400),
                "status": status,
                "case_sensitive": bool(item.get("case_sensitive", False)),
                "note": _clean_str(item.get("note"), 200),
            }
        )
    return entries


def _normalize_str_list(raw: object, limit: int = 60) -> list[str]:
    if isinstance(raw, str):
        raw = [line for line in raw.splitlines()]
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        text = _clean_str(item, 400)
        if text:
            out.append(text)
        if len(out) >= limit:
            break
    return out


def normalize_profile(payload: dict[str, object], name: str | None = None) -> dict[str, object]:
    """把任意输入（含旧版纯文本）规范成结构化 KnowledgeProfile。"""
    payload = payload if isinstance(payload, dict) else {}
    resolved_name = _clean_str(name or payload.get("name"), 120) or "未命名知识库"

    # 旧版纯文本兼容：{name, content} → 解析 术语/风格/禁译 段落
    if "content" in payload and not payload.get("glossary") and not payload.get("style_rules"):
        parsed = parse_legacy_text(str(payload.get("content") or ""))
        glossary = parsed["glossary"]
        style_rules = parsed["style_rules"]
        do_not_translate = parsed["do_not_translate"]
    else:
        glossary = normalize_glossary(payload.get("glossary"))
        style_rules = _normalize_str_list(payload.get("style_rules"))
        do_not_translate = _normalize_str_list(payload.get("do_not_translate"))

    return {
        "name": resolved_name,
        "version": SCHEMA_VERSION,
        "glossary": glossary,
        "style_rules": style_rules,
        "do_not_translate": do_not_translate,
        "updated_at": _now(),
    }


def parse_legacy_text(content: str) -> dict[str, object]:
    """尽力把旧版纯文本（术语：/风格：/禁译：）解析成结构化数据。"""
    glossary: list[dict[str, object]] = []
    style_rules: list[str] = []
    do_not_translate: list[str] = []
    section = "style"  # 默认归入风格
    for raw_line in content.replace("\r\n", "\n").split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        header = line.rstrip("：:").strip()
        if header in ("术语", "术语对照", "glossary"):
            section = "glossary"
            continue
        if header in ("风格", "风格规则", "style"):
            section = "style"
            continue
        if header in ("禁译", "禁译表", "do not translate", "保留原文"):
            section = "dnt"
            continue
        if section == "glossary" and ("=" in line or "＝" in line):
            src, dst = re.split(r"=|＝", line, maxsplit=1)
            src, dst = src.strip(), dst.strip()
            if src:
                glossary.append({"src": src, "dst": dst, "case_sensitive": False, "note": ""})
        elif section == "dnt":
            for part in re.split(r"[，,、]", line):
                part = part.strip()
                if part:
                    do_not_translate.append(part)
        else:
            style_rules.append(line)
    return {
        "glossary": normalize_glossary(glossary),
        "style_rules": _normalize_str_list(style_rules),
        "do_not_translate": _normalize_str_list(do_not_translate),
    }


# --------------------------------------------------------------------------- #
# 存储 CRUD
# --------------------------------------------------------------------------- #
def _safe_filename(name: str) -> str:
    slug = re.sub(r'[\\/:*?"<>|]+', "-", name).strip().strip(".")
    return (slug or "knowledge")[:120]


def _profile_path(name: str) -> Path:
    return KNOWLEDGE_DIR / f"{_safe_filename(name)}.json"


def _atomic_write(path: Path, data: dict[str, object]) -> None:
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    temp = KNOWLEDGE_DIR / f".{uuid.uuid4().hex}.tmp"
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def ensure_seeded() -> None:
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    if any(KNOWLEDGE_DIR.glob("*.json")):
        return
    for seed in DEFAULT_PROFILES:
        save_profile(seed["name"], seed)


def list_profiles() -> list[dict[str, object]]:
    ensure_seeded()
    items: list[dict[str, object]] = []
    for path in KNOWLEDGE_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        items.append(
            {
                "name": data.get("name"),
                "version": data.get("version"),
                "glossary_count": len(data.get("glossary") or []),
                "updated_at": data.get("updated_at"),
            }
        )
    items.sort(key=lambda it: str(it.get("name") or ""))
    return items


def load_profile(name: str) -> dict[str, object] | None:
    path = _profile_path(name)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
    # 兜底：按 name 字段扫描
    for candidate in KNOWLEDGE_DIR.glob("*.json"):
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("name") == name:
            return data
    return None


def save_profile(name: str, payload: dict[str, object]) -> dict[str, object]:
    profile = normalize_profile(payload, name=name)
    _atomic_write(_profile_path(profile["name"]), profile)
    return profile


def delete_profile(name: str) -> bool:
    path = _profile_path(name)
    if path.exists():
        path.unlink()
        return True
    for candidate in KNOWLEDGE_DIR.glob("*.json"):
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("name") == name:
            candidate.unlink()
            return True
    return False


# --------------------------------------------------------------------------- #
# 渲染为提示词片段（可按文档命中过滤）
# --------------------------------------------------------------------------- #
def filter_glossary_hits(
    glossary: list[dict[str, object]], document_text: str
) -> list[dict[str, object]]:
    if not document_text:
        return list(glossary)
    lowered = document_text.lower()
    hits: list[dict[str, object]] = []
    for entry in glossary:
        src = str(entry.get("src") or "")
        if not src:
            continue
        if entry.get("case_sensitive"):
            found = src in document_text
        else:
            found = src.lower() in lowered
        if found:
            hits.append(entry)
    return hits


def render_profile(
    profile: dict[str, object] | None, document_text: str | None = None
) -> tuple[str, int]:
    """渲染知识库为提示词文本，返回 (文本, 命中术语数)。"""
    if not profile:
        return "", 0
    glossary = profile.get("glossary") or []
    if document_text is not None:
        glossary = filter_glossary_hits(glossary, document_text)
    style_rules = profile.get("style_rules") or []
    do_not_translate = list(profile.get("do_not_translate") or [])

    # status=forbidden 的术语当作禁译（保留原文），不作为对照译法
    forbidden = [e for e in glossary if e.get("status") == "forbidden"]
    translate_terms = [e for e in glossary if e.get("status") != "forbidden"]
    do_not_translate.extend(str(e.get("src")) for e in forbidden if e.get("src"))

    blocks: list[str] = []
    if translate_terms:
        lines = ["术语对照（出现在本文档中，翻译时必须遵守）:"]
        for entry in translate_terms:
            dst = entry.get("dst") or ""
            note = entry.get("note") or ""
            domain = entry.get("domain") or ""
            tags = "、".join(x for x in [domain, note] if x)
            suffix = f"  // {tags}" if tags else ""
            lines.append(f"- {entry.get('src')} = {dst}{suffix}")
        blocks.append("\n".join(lines))
    if style_rules:
        blocks.append("风格要求:\n" + "\n".join(f"- {rule}" for rule in style_rules))
    if do_not_translate:
        blocks.append("禁译（保留原文）:\n" + "、".join(str(x) for x in do_not_translate))

    text = "\n\n".join(blocks).strip()
    if len(text) > PROMPT_BUDGET:
        text = text[:PROMPT_BUDGET].rstrip() + "\n[Knowledge base truncated to fit prompt budget.]"
    return text, len(translate_terms)


# --------------------------------------------------------------------------- #
# CSV 导入 / 导出（标准格式互通第一步）
# --------------------------------------------------------------------------- #
CSV_FIELDS = ["src", "dst", "domain", "pos", "status", "note"]
_CSV_ALIASES = {
    "src": {"src", "source", "english", "en", "原文", "term", "源"},
    "dst": {"dst", "target", "chinese", "zh", "译文", "translation", "目标"},
    "domain": {"domain", "领域", "field", "subject", "学科"},
    "pos": {"pos", "词性", "part_of_speech"},
    "status": {"status", "状态"},
    "note": {"note", "备注", "comment", "notes"},
}


def profile_to_csv(profile: dict[str, object]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(CSV_FIELDS)
    for entry in profile.get("glossary") or []:
        writer.writerow([entry.get(field, "") for field in CSV_FIELDS])
    return out.getvalue()


def merge_glossary(
    base: list[dict[str, object]], incoming: list[dict[str, object]]
) -> list[dict[str, object]]:
    """按 src（忽略大小写）去重合并，incoming 覆盖 base。"""
    by_key: dict[str, dict[str, object]] = {}
    for entry in normalize_glossary(base):
        by_key[str(entry.get("src", "")).lower()] = entry
    for entry in normalize_glossary(incoming):
        by_key[str(entry.get("src", "")).lower()] = entry
    return list(by_key.values())


def csv_to_glossary(text: str) -> list[dict[str, object]]:
    """解析 CSV：识别表头（含中英列名）；无表头则按 src,dst,domain,note 顺序。"""
    rows = list(csv.reader(io.StringIO(text.replace("\r\n", "\n"))))
    if not rows:
        return []
    header = [h.strip().lower() for h in rows[0]]
    all_aliases = set().union(*_CSV_ALIASES.values())
    raw: list[dict[str, object]] = []
    if any(h in all_aliases for h in header):
        col: dict[str, int] = {}
        for i, name in enumerate(header):
            for field, aliases in _CSV_ALIASES.items():
                if name in aliases:
                    col[field] = i
        for row in rows[1:]:
            def cell(field: str, _row: list[str] = None) -> str:  # noqa: ANN001
                r = _row if _row is not None else row
                i = col.get(field)
                return r[i].strip() if i is not None and i < len(r) else ""

            if cell("src"):
                raw.append({field: cell(field) for field in CSV_FIELDS})
    else:
        for row in rows:
            if not row or not row[0].strip():
                continue
            raw.append(
                {
                    "src": row[0].strip(),
                    "dst": row[1].strip() if len(row) > 1 else "",
                    "domain": row[2].strip() if len(row) > 2 else "",
                    "note": row[3].strip() if len(row) > 3 else "",
                }
            )
    return normalize_glossary(raw)
