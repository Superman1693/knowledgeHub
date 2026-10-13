"""项目开发辅助：代码评审、故障排查、需求拆解、项目时间线。

约束（requirements.md 扩展路线图）：
- 代码评审必须区分「知识库已记录的规范」与「AI 新提出的建议」；
- 故障排查未经验证时不得把可能原因说成确定根因，必须标注「待验证」；
- 时间线无法从原文确认日期时标注为未知，不得推测。
"""
from __future__ import annotations

import json
import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.factory import get_provider
from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models import Chunk, Document
from app.rag.indexer import embed_query
from app.rag.retriever import hybrid_search

logger = get_logger(__name__)

CONTEXT_TOP_K = 6


def _parse_json(raw: str, expect: type) -> object:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = "\n".join(
            ln for ln in text.splitlines() if not ln.strip().startswith("```")
        )
    if expect is list:
        start, end = text.find("["), text.rfind("]")
    else:
        start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        logger.warning("模型未返回可解析的 JSON")
        return expect()
    try:
        parsed = json.loads(text[start : end + 1])
        return parsed if isinstance(parsed, expect) else expect()
    except json.JSONDecodeError:
        logger.warning("JSON 解析失败")
        return expect()


async def _search_context(db: Session, query: str, top_k: int = CONTEXT_TOP_K) -> list[dict]:
    """检索知识库作为依据，返回带来源的信息列表。

    隐私：检索结果会交给对话模型，因此**强制 `ai_only=True`**——
    与 RAG 问答一致，标记为「不允许 AI 读取」的笔记在 SQL 层即被排除。
    """
    vec = await embed_query(query)
    hits = hybrid_search(db, query, vec, top_k=top_k, ai_only=True)
    return [
        {
            "document_title": h.document_title,
            "document_id": str(h.document_id),
            "chunk_id": str(h.chunk_id),
            "heading": h.heading,
            "content": h.parent_content or h.snippet,
        }
        for h in hits
    ]


def _context_text(context: list[dict]) -> str:
    if not context:
        return "（知识库中没有检索到相关资料）"
    return "\n\n".join(
        f"[{i}] 《{c['document_title']}》{('· ' + c['heading']) if c['heading'] else ''}\n{c['content'][:1200]}"
        for i, c in enumerate(context, start=1)
    )


# ---------------- 1. 代码评审 ----------------

REVIEW_PROMPT = """你是资深工程师，正在评审代码。

只输出一个 JSON 对象，不要解释、不要用 ``` 包裹：
{
  "from_knowledge": [
    {"point": "评审意见", "basis": "依据的知识库条目编号", "level": "high|medium|low"}
  ],
  "suggestions": [
    {"point": "AI 新提出的建议", "reason": "理由", "level": "high|medium|low"}
  ],
  "summary": "一句话总评"
}

**硬性要求**：
1. `from_knowledge` 只放**能在知识库资料中找到依据**的意见，`basis` 必须写资料编号（如 [2]）。
2. `suggestions` 放通用工程经验类的建议，**这些不是知识库记录**，必须分开列出。
3. 不要编造知识库里没有的规范；若知识库无相关资料，`from_knowledge` 返回空数组。
"""


async def review_code(
    db: Session, code: str, language: str | None = None, focus: str | None = None
) -> dict:
    """代码评审：明确区分「知识库规范」与「AI 建议」。"""
    if not code.strip():
        raise ValidationError("代码内容不能为空")

    query = focus or f"{language or ''} 代码规范 最佳实践".strip()
    context = await _search_context(db, query)
    messages = [
        {"role": "system", "content": REVIEW_PROMPT},
        {
            "role": "user",
            "content": (
                f"语言：{language or '未指定'}\n"
                f"关注点：{focus or '综合'}\n\n"
                f"知识库资料：\n{_context_text(context)}\n\n"
                f"待评审代码：\n```\n{code[:6000]}\n```"
            ),
        },
    ]
    provider = get_provider()
    raw = await provider.chat(messages, stream=False)
    data = _parse_json(str(raw), dict)

    return {
        "language": language,
        "from_knowledge": data.get("from_knowledge") or [],
        "suggestions": data.get("suggestions") or [],
        "summary": str(data.get("summary") or "").strip(),
        "context_count": len(context),
        "note": (
            "from_knowledge 为知识库已有规范的核对结果；"
            "suggestions 是 AI 基于通用工程经验提出的新建议，两者性质不同"
        ),
    }


# ---------------- 2. 故障排查 ----------------

TROUBLESHOOT_PROMPT = """你是故障排查助手。

只输出一个 JSON 对象，不要解释、不要用 ``` 包裹：
{
  "confirmed": [
    {"cause": "已确认的原因", "basis": "知识库资料编号", "action": "处理方式"}
  ],
  "possible": [
    {"cause": "可能的原因", "verify": "如何验证这一点", "action": "验证后如何处理"}
  ],
  "need_more_info": ["还需要用户补充的信息"]
}

**硬性要求**：
1. `confirmed` 只放**知识库资料中明确记录**的原因，必须给出资料编号。
2. `possible` 是**推测**，每条都必须写明「如何验证」；**未经验证不得当作确定根因**。
3. 知识库没有相关资料时，`confirmed` 返回空数组，全部放到 `possible` 并说明需自行验证。
"""


async def troubleshoot(db: Session, symptom: str, context_hint: str | None = None) -> dict:
    """故障排查：区分「知识库已记录」与「待验证的推测」。"""
    if not symptom.strip():
        raise ValidationError("请描述故障现象")

    query = f"{symptom} {context_hint or ''}".strip()
    context = await _search_context(db, query)
    messages = [
        {"role": "system", "content": TROUBLESHOOT_PROMPT},
        {
            "role": "user",
            "content": (
                f"故障现象：{symptom}\n"
                f"环境/上下文：{context_hint or '未提供'}\n\n"
                f"知识库资料：\n{_context_text(context)}"
            ),
        },
    ]
    provider = get_provider()
    raw = await provider.chat(messages, stream=False)
    data = _parse_json(str(raw), dict)

    return {
        "confirmed": data.get("confirmed") or [],
        "possible": data.get("possible") or [],
        "need_more_info": data.get("need_more_info") or [],
        "context_count": len(context),
        "note": "confirmed 有知识库依据；possible 为推测，必须先验证再据此处理",
    }


# ---------------- 3. 需求拆解 ----------------

BREAKDOWN_PROMPT = """你是技术负责人，正在把需求拆解为可执行任务。

只输出一个 JSON 对象，不要解释、不要用 ``` 包裹：
{
  "goal": "需求目标（一句话）",
  "tasks": [
    {"title": "任务标题", "detail": "具体做什么", "acceptance": "验收标准",
     "basis": "知识库依据编号，没有依据则填空字符串"}
  ],
  "risks": ["风险或不确定点"],
  "assumptions": ["我做的假设（这些不是用户原话）"]
}

**硬性要求**：
1. 任务是**计划**，不是已完成的事实，不要写成「已完成」。
2. `basis` 只填真正来自知识库资料的编号；凭空推断的填 ""。
3. `assumptions` 必须列出你为完成拆解而做的假设，与用户原话区分开。
"""


async def breakdown_requirement(db: Session, requirement: str) -> dict:
    """需求拆解：产出任务清单，明确区分「知识库依据」与「AI 假设」。"""
    if not requirement.strip():
        raise ValidationError("需求描述不能为空")

    context = await _search_context(db, requirement)
    messages = [
        {"role": "system", "content": BREAKDOWN_PROMPT},
        {
            "role": "user",
            "content": (
                f"需求原文：{requirement}\n\n"
                f"知识库资料：\n{_context_text(context)}"
            ),
        },
    ]
    provider = get_provider()
    raw = await provider.chat(messages, stream=False)
    data = _parse_json(str(raw), dict)

    return {
        "goal": str(data.get("goal") or "").strip(),
        "tasks": data.get("tasks") or [],
        "risks": data.get("risks") or [],
        "assumptions": data.get("assumptions") or [],
        "context_count": len(context),
        "note": "tasks 是待执行的计划（非已完成）；assumptions 是 AI 的假设，非用户原话",
    }


# ---------------- 4. 项目时间线 ----------------

_DATE_PATTERNS = [
    re.compile(r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})"),
    re.compile(r"(20\d{2})[-/年](\d{1,2})月?"),
    re.compile(r"(20\d{2})年"),
]


def extract_dates(text: str) -> list[str]:
    """从文本中提取可确认的日期（仅识别明确写出的年/月/日）。"""
    found: list[str] = []
    for line in (text or "").splitlines():
        for pat in _DATE_PATTERNS:
            m = pat.search(line)
            if m:
                groups = [g for g in m.groups() if g]
                found.append("-".join(g.zfill(2) for g in groups))
                break
    return found


async def build_timeline(
    db: Session, document_id: uuid.UUID | None = None, query: str | None = None
) -> dict:
    """项目时间线：从文档中提取事件与日期。

    **无法从原文确认日期的事件一律标记 date_known=false**，不推测时间。
    """
    if document_id:
        doc = db.get(Document, document_id)
        if not doc:
            raise NotFoundError("文档不存在")
        docs = [doc]
    elif query:
        hits = await _search_context(db, query, top_k=10)
        ids = {uuid.UUID(h["document_id"]) for h in hits}
        docs = list(
            db.execute(select(Document).where(Document.id.in_(ids))).scalars().all()
        ) if ids else []
    else:
        docs = list(
            db.execute(select(Document).order_by(Document.created_at.desc()).limit(5))
            .scalars()
            .all()
        )

    if not docs:
        raise ValidationError("没有可用于构建时间线的文档")

    material_parts: list[str] = []
    for d in docs:
        text = (d.content_text or "")[:4000]
        dates = extract_dates(text)
        material_parts.append(
            f"《{d.title}》\n"
            f"（该文档中可识别的日期：{'、'.join(dates) if dates else '无'}）\n"
            f"{text}"
        )

    messages = [
        {
            "role": "system",
            "content": (
                "请从给定资料中提取项目事件，输出 JSON 数组，不要解释、不要用 ``` 包裹：\n"
                '[{"date": "YYYY-MM-DD 或空字符串", "date_known": true/false, '
                '"event": "事件描述", "source": "来自哪篇文档"}]\n'
                "**硬性要求**：\n"
                "1. 只有资料中**明确写出日期**的事件才能 date_known=true。\n"
                "2. 无法确认日期的事件 date 留空、date_known=false，**严禁推测日期**。\n"
                "3. 事件描述用资料中的原意，不要编造资料里没有的事件。"
            ),
        },
        {"role": "user", "content": "\n\n".join(material_parts)[:12000]},
    ]
    provider = get_provider()
    raw = await provider.chat(messages, stream=False)
    items = _parse_json(str(raw), list)

    events = []
    for it in items:
        if not isinstance(it, dict) or not it.get("event"):
            continue
        known = bool(it.get("date_known")) and bool(str(it.get("date") or "").strip())
        events.append(
            {
                "date": str(it.get("date") or "").strip() if known else "",
                "date_known": known,
                "event": str(it["event"]).strip(),
                "source": str(it.get("source") or "").strip(),
            }
        )
    events.sort(key=lambda e: (not e["date_known"], e["date"] or "9999"))

    return {
        "documents": [d.title for d in docs],
        "total": len(events),
        "events": events,
        "undated": len([e for e in events if not e["date_known"]]),
        "note": "date_known=false 表示原文未写明日期，系统不做推测",
    }
