"""学习辅助：模拟面试、评分点评、错题管理、快捷复习。

约束（requirements.md 扩展路线图）：
- 题目与参考答案均**依据知识库片段**生成，并保留来源引用，便于追溯；
- 错题本只收录用户**真实提交**且得分未达标的记录，绝不虚构用户答错的题目；
- 评分只依据参考答案给分，不虚高、不编造考生没说过的话。
"""
from __future__ import annotations

import json
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.factory import get_provider
from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models import Chunk, Document
from app.models.learning import QuizRecord

logger = get_logger(__name__)

PASS_SCORE = 60  # 低于此分计入错题本


# ---------------- 通用：JSON 容错解析 ----------------

def _parse_json(raw: str, expect: type) -> object:
    """从模型输出中提取 JSON（支持对象或数组）。"""
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


# ---------------- 1. 出题（面试 / 复习共用） ----------------

QUESTION_PROMPT = """你是技术面试官。请依据给定的知识库资料出题。

要求：
1. **只依据资料内容出题**，不要考察资料里没有的知识点。
2. 每道题给出参考答案，答案同样必须来自资料。
3. 只输出 JSON 数组，不要解释、不要用 ``` 包裹：
[
  {"question": "题目", "reference_answer": "参考答案", "chunk_index": 1}
]
chunk_index 是该题依据的资料编号（对应下方 [n] 标号）。
"""


def _pick_chunks(db: Session, count: int, direction: str | None) -> list[Chunk]:
    """从知识库中挑选出题素材（优先语义相关、且内容较完整的片段）。

    隐私与一致性：出题素材会被整段发送给对话模型，因此**必须在 SQL 层**
    排除回收站文档（`deleted_at`）与「不允许 AI 读取」的笔记（`ai_enabled=false`），
    而不是只靠提示词约束——与 RAG 问答的隐私口径保持一致。
    """
    base = (
        select(Chunk)
        .join(Document, Document.id == Chunk.document_id)
        .where(
            Chunk.embedding.is_not(None),
            Document.deleted_at.is_(None),
            Document.ai_enabled.is_(True),
        )
    )
    stmt = base
    if direction:
        stmt = stmt.where(Chunk.content.ilike(f"%{direction}%"))
    rows = list(db.execute(stmt.limit(count * 4)).scalars().all())
    if not rows and direction:  # 方向没匹配到就退回全库（仍保持隐私过滤）
        rows = list(db.execute(base.limit(count * 4)).scalars().all())
    rows.sort(key=lambda c: len(c.content), reverse=True)
    return rows[:count]


async def generate_questions(
    db: Session,
    count: int = 5,
    direction: str | None = None,
    difficulty: str = "medium",
    mode: str = "interview",
) -> dict:
    """依据知识库生成面试题 / 复习题。"""
    count = max(1, min(count, 10))
    chunks = _pick_chunks(db, count, direction)
    if not chunks:
        raise ValidationError("知识库中还没有可用于出题的内容，请先导入文档")

    doc_ids = {c.document_id for c in chunks}
    titles = {
        d.id: d.title
        for d in db.execute(
            select(Document).where(Document.id.in_(doc_ids))
        )
        .scalars()
        .all()
    }

    material = "\n\n".join(
        f"[{i}] （来自《{titles.get(c.document_id, '未知文档')}》"
        f"{'· ' + c.heading if c.heading else ''}）\n{c.content[:900]}"
        for i, c in enumerate(chunks, start=1)
    )
    level = {"easy": "基础", "medium": "中等", "hard": "进阶"}.get(
        difficulty, "中等"
    )

    messages = [
        {"role": "system", "content": QUESTION_PROMPT},
        {
            "role": "user",
            "content": (
                f"难度：{level}\n"
                f"方向：{direction or '综合'}\n"
                f"请出 {count} 道题。\n\n知识库资料：\n{material}"
            ),
        },
    ]
    provider = get_provider()
    raw = await provider.chat(messages, stream=False)
    items = _parse_json(str(raw), list)

    questions: list[dict] = []
    for item in items:
        if not isinstance(item, dict) or not item.get("question"):
            continue
        idx = item.get("chunk_index")
        chunk = (
            chunks[int(idx) - 1]
            if isinstance(idx, int) and 1 <= idx <= len(chunks)
            else None
        )
        questions.append(
            {
                "question": str(item["question"]).strip(),
                "reference_answer": str(item.get("reference_answer") or "").strip(),
                "source_chunk_id": str(chunk.id) if chunk else None,
                "source_document_id": str(chunk.document_id) if chunk else None,
                "source_document_title": titles.get(chunk.document_id) if chunk else None,
            }
        )

    if not questions:
        raise ValidationError("未能生成有效题目，请稍后重试或检查模型配置")

    return {
        "mode": mode,
        "direction": direction,
        "difficulty": difficulty,
        "total": len(questions),
        "questions": questions,
        "note": "题目与参考答案均依据知识库资料生成，来源已标注",
    }


# ---------------- 2. 评分点评 ----------------

GRADE_PROMPT = """你是面试官。请为考生的作答评分。

只输出一个 JSON 对象，不要解释、不要用 ``` 包裹：
{"score": 0到100的整数, "feedback": "具体点评", "missing": ["遗漏的要点"]}

要求：
1. 只依据「参考答案」给分，答对多少给多少，**不要虚高也不要刻意压低**。
2. 点评要具体指出答对之处与缺失之处。
3. 不要编造考生没有说过的内容；考生未作答就给 0 分并说明原因。
"""


async def grade_answer(
    db: Session,
    question: str,
    reference_answer: str,
    user_answer: str,
    direction: str | None = None,
    difficulty: str | None = None,
    source_chunk_id: uuid.UUID | None = None,
    source_document_id: uuid.UUID | None = None,
) -> dict:
    """评分并写入答题记录（低于 PASS_SCORE 自动进入错题本）。"""
    if not question.strip():
        raise ValidationError("题目不能为空")

    messages = [
        {"role": "system", "content": GRADE_PROMPT},
        {
            "role": "user",
            "content": (
                f"题目：{question}\n\n"
                f"参考答案：{reference_answer or '（无）'}\n\n"
                f"考生作答：{user_answer.strip() or '（未作答）'}"
            ),
        },
    ]
    provider = get_provider()
    raw = await provider.chat(messages, stream=False)
    data = _parse_json(str(raw), dict)

    try:
        score = int(data.get("score", 0))
    except (TypeError, ValueError):
        score = 0
    score = max(0, min(score, 100))
    missing = [
        str(m).strip() for m in (data.get("missing") or []) if str(m).strip()
    ][:6]

    record = QuizRecord(
        question=question.strip(),
        reference_answer=reference_answer or None,
        user_answer=user_answer.strip() or None,
        score=score,
        feedback=str(data.get("feedback") or "").strip() or None,
        direction=direction,
        difficulty=difficulty,
        mode="interview" if direction else "review",
        source_chunk_id=source_chunk_id,
        source_document_id=source_document_id,
        mastered=score >= PASS_SCORE,
        tags=missing or None,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    return {
        "record_id": str(record.id),
        "score": score,
        "passed": score >= PASS_SCORE,
        "feedback": record.feedback,
        "missing": missing,
        "note": "评分依据参考答案，未编造作答内容",
    }


# ---------------- 3. 错题管理 ----------------

def list_mistakes(
    db: Session, include_mastered: bool = False, limit: int = 50
) -> list[dict]:
    """错题列表：只含**真实提交过**且得分低于及格线的记录。"""
    stmt = select(QuizRecord).where(
        QuizRecord.user_answer.is_not(None),
        QuizRecord.score.is_not(None),
        QuizRecord.score < PASS_SCORE,
    )
    if not include_mastered:
        stmt = stmt.where(QuizRecord.mastered.is_(False))
    rows = (
        db.execute(stmt.order_by(QuizRecord.created_at.desc()).limit(limit))
        .scalars()
        .all()
    )
    return [_record_out(r) for r in rows]


def _record_out(r: QuizRecord) -> dict:
    return {
        "id": str(r.id),
        "question": r.question,
        "reference_answer": r.reference_answer,
        "user_answer": r.user_answer,
        "score": r.score,
        "feedback": r.feedback,
        "direction": r.direction,
        "difficulty": r.difficulty,
        "mastered": r.mastered,
        "missing": r.tags or [],
        "source_document_id": str(r.source_document_id) if r.source_document_id else None,
        "created_at": r.created_at.isoformat(),
    }


def set_mastered(db: Session, record_id: uuid.UUID, mastered: bool) -> dict:
    record = db.get(QuizRecord, record_id)
    if not record:
        raise NotFoundError("记录不存在")
    record.mastered = mastered
    db.commit()
    db.refresh(record)
    return _record_out(record)


def delete_record(db: Session, record_id: uuid.UUID) -> None:
    record = db.get(QuizRecord, record_id)
    if not record:
        raise NotFoundError("记录不存在")
    db.delete(record)
    db.commit()


# ---------------- 4. 快捷复习 ----------------

def review_stats(db: Session) -> dict:
    """复习概览：错题数、已掌握数、平均分。"""
    rows = (
        db.execute(
            select(QuizRecord).where(
                QuizRecord.user_answer.is_not(None), QuizRecord.score.is_not(None)
            )
        )
        .scalars()
        .all()
    )
    mistakes = [r for r in rows if (r.score or 0) < PASS_SCORE]
    return {
        "total_answered": len(rows),
        "mistakes": len(mistakes),
        "mistakes_pending": len([r for r in mistakes if not r.mastered]),
        "mastered": len([r for r in rows if r.mastered]),
        "average_score": (
            round(sum(r.score or 0 for r in rows) / len(rows), 1) if rows else 0
        ),
        "pass_score": PASS_SCORE,
    }
