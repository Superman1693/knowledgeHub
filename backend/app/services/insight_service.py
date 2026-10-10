"""知识加工：冗余检测、跨文档关联、思维导图、整理归档。

设计约束（来自 requirements.md「后续扩展路线图」）：
- 事实 / 观点 / 计划 / 推断必须分离，不得把推断写成用户观点；
- 冗余检测与关联走**向量计算**（不消耗对话模型），结果仅作提示，由用户决定是否处理；
- 思维导图与整理归档属 **AI 建议**，必须与知识库原文区分标注。
"""
from __future__ import annotations

import json
import uuid

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.ai.factory import get_provider
from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.models import Chunk, Document

logger = get_logger(__name__)

SNIPPET_LEN = 160


def _brief(content: str, length: int = SNIPPET_LEN) -> str:
    flat = " ".join(content.split())
    return flat[:length] + "…" if len(flat) > length else flat


# ---------------- 1. 冗余检测 ----------------

def find_duplicates(
    db: Session, threshold: float = 0.10, limit: int = 20
) -> list[dict]:
    """找出内容高度相似的片段对（余弦距离小于阈值）。

    纯向量计算、不调用对话模型。同一文档内与跨文档的重复都会列出，
    由用户判断是保留、合并还是删除 —— 系统不自动改动内容。
    """
    sql = text(
        """
        SELECT a.id AS a_id, a.content AS a_content, a.heading AS a_heading,
               da.id AS a_doc, da.title AS a_title,
               b.id AS b_id, b.content AS b_content, b.heading AS b_heading,
               dbb.id AS b_doc, dbb.title AS b_title,
               (a.embedding <=> b.embedding) AS distance
        FROM chunks a
        JOIN chunks b ON a.id < b.id
        JOIN documents da ON da.id = a.document_id
        JOIN documents dbb ON dbb.id = b.document_id
        WHERE a.embedding IS NOT NULL
          AND b.embedding IS NOT NULL
          AND (a.embedding <=> b.embedding) < :th
        ORDER BY distance ASC
        LIMIT :lim
        """
    )
    rows = db.execute(sql, {"th": threshold, "lim": limit}).mappings().all()
    return [
        {
            "distance": round(float(r["distance"]), 4),
            "similarity": round(1 - float(r["distance"]), 4),
            "same_document": r["a_doc"] == r["b_doc"],
            "left": {
                "chunk_id": str(r["a_id"]),
                "document_id": str(r["a_doc"]),
                "document_title": r["a_title"],
                "heading": r["a_heading"],
                "snippet": _brief(r["a_content"]),
            },
            "right": {
                "chunk_id": str(r["b_id"]),
                "document_id": str(r["b_doc"]),
                "document_title": r["b_title"],
                "heading": r["b_heading"],
                "snippet": _brief(r["b_content"]),
            },
        }
        for r in rows
    ]


# ---------------- 2. 跨文档知识关联 ----------------

def related_documents(
    db: Session, document_id: uuid.UUID, limit: int = 5
) -> list[dict]:
    """给定文档，找出与之内容最相近的其它文档（按片段平均余弦距离）。

    用于发现「同一主题散落在多篇笔记」的情况，帮助建立知识关联。
    """
    doc = db.get(Document, document_id)
    if not doc:
        raise NotFoundError("文档不存在")

    sql = text(
        """
        WITH src AS (
            SELECT embedding FROM chunks
            WHERE document_id = CAST(:did AS uuid) AND embedding IS NOT NULL
        )
        SELECT d.id, d.title, d.chunk_count,
               AVG(c.embedding <=> (SELECT embedding FROM src LIMIT 1)) AS avg_distance,
               COUNT(*) AS matched
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE c.document_id <> CAST(:did AS uuid)
          AND c.embedding IS NOT NULL
          AND (SELECT count(*) FROM src) > 0
        GROUP BY d.id, d.title, d.chunk_count
        ORDER BY avg_distance ASC
        LIMIT :lim
        """
    )
    rows = db.execute(sql, {"did": str(document_id), "lim": limit}).mappings().all()
    return [
        {
            "document_id": str(r["id"]),
            "document_title": r["title"],
            "chunk_count": r["chunk_count"],
            "similarity": round(1 - float(r["avg_distance"] or 1), 4),
        }
        for r in rows
    ]


# ---------------- 3. 思维导图（AI 生成 Mermaid） ----------------

MINDMAP_PROMPT = """你是知识结构整理助手。请把给定文档整理成一张思维导图。

要求：
1. 只使用 **Mermaid mindmap 语法**，第一行必须是 `mindmap`。
2. 层级用缩进表示，根节点是文档主题，向下展开 2~3 层，总节点数控制在 8~20 个。
3. 节点文字用文档中的**原词或短语**，不要自造概念、不要补充文档里没有的内容。
4. 节点文字尽量简短（不超过 12 个字），不要包含括号、引号、冒号等会破坏语法的字符。
5. 只输出 Mermaid 代码，不要任何解释、不要用 ``` 包裹。

示例格式：
mindmap
  root((Docker))
    基础概念
      镜像
      容器
    常用命令
      docker run
      docker ps
"""


async def build_mindmap(db: Session, document_id: uuid.UUID) -> dict:
    """用 AI 把文档结构化为 Mermaid 思维导图。

    返回内容标注为「AI 整理」，节点取自文档原文，不额外补充知识库之外的信息。
    """
    doc = db.get(Document, document_id)
    if not doc:
        raise NotFoundError("文档不存在")
    content = (doc.content_text or "").strip()
    if not content:
        raise NotFoundError("文档内容为空，无法生成思维导图")

    chunks = (
        db.execute(
            select(Chunk)
            .where(Chunk.document_id == document_id, Chunk.embedding.is_not(None))
            .order_by(Chunk.chunk_index)
        )
        .scalars()
        .all()
    )
    # 优先用各片段的小标题拼出骨架，帮助模型把握层级
    outline = "\n".join(
        f"- {c.heading}" for c in chunks if c.heading
    ) or "（文档无小标题）"

    messages = [
        {"role": "system", "content": MINDMAP_PROMPT},
        {
            "role": "user",
            "content": (
                f"文档标题：{doc.title}\n\n"
                f"文档中的小标题（可用于搭建层级）：\n{outline}\n\n"
                f"文档内容（节选）：\n{content[:4000]}"
            ),
        },
    ]
    provider = get_provider()
    raw = await provider.chat(messages, stream=False)
    code = _clean_mermaid(str(raw))
    return {
        "document_id": str(document_id),
        "document_title": doc.title,
        "mermaid": code,
        "note": "由 AI 依据文档内容整理，节点取自原文，未补充知识库之外的信息",
    }


def _clean_mermaid(raw: str) -> str:
    """清理模型输出中的代码围栏与多余空行。"""
    lines = [ln.rstrip() for ln in (raw or "").strip().splitlines()]
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    cleaned = [ln for ln in lines if ln.strip()]
    if cleaned and not cleaned[0].strip().lower().startswith("mindmap"):
        cleaned.insert(0, "mindmap")
    return "\n".join(cleaned)


# ---------------- 4. 笔记整理归档（AI 建议） ----------------

ORGANIZE_PROMPT = """你是知识库整理助手。请为给定文档给出归档建议。

只输出一个 JSON 对象，不要任何解释、不要用 ``` 包裹。字段：
{
  "suggested_title": "更清晰的文件标题（不超过 20 字）",
  "category": "建议的分类名（2~6 字，如「后端开发」）",
  "tags": ["标签1", "标签2", "标签3"],
  "summary": "两句话以内的内容摘要",
  "reason": "为什么这样归档（一句话）"
}

要求：
- 分类与标签必须基于文档**实际内容**，不要编造文档里没有的主题；
- 标签 3~6 个，每个 2~8 字，是能概括主题的概念词（不要 font、color 这类代码符号）；
- 若文档内容不足以判断，请把该字段留空字符串或空数组，不要猜测。
"""


async def organize_document(db: Session, document_id: uuid.UUID) -> dict:
    """为文档生成归档建议（标题 / 分类 / 标签 / 摘要）。

    这是 **AI 建议**，不会自动写入；用户在前端确认后才应用到文档与标签。
    """
    doc = db.get(Document, document_id)
    if not doc:
        raise NotFoundError("文档不存在")
    content = (doc.content_text or "").strip()
    if not content:
        raise NotFoundError("文档内容为空，无法生成归档建议")

    messages = [
        {"role": "system", "content": ORGANIZE_PROMPT},
        {
            "role": "user",
            "content": f"当前标题：{doc.title}\n\n文档内容（节选）：\n{content[:3500]}",
        },
    ]
    provider = get_provider()
    raw = await provider.chat(messages, stream=False)
    data = _parse_json_object(str(raw))

    return {
        "document_id": str(document_id),
        "current_title": doc.title,
        "suggested_title": str(data.get("suggested_title") or "").strip(),
        "category": str(data.get("category") or "").strip(),
        "tags": [
            str(t).strip()
            for t in (data.get("tags") or [])
            if isinstance(t, str) and str(t).strip()
        ][:6],
        "summary": str(data.get("summary") or "").strip(),
        "reason": str(data.get("reason") or "").strip(),
        "note": "以上为 AI 建议，不会自动修改文档；确认后再应用",
    }


def _parse_json_object(raw: str) -> dict:
    """从模型输出中容错解析 JSON 对象。"""
    text_ = (raw or "").strip()
    if text_.startswith("```"):
        text_ = "\n".join(
            ln for ln in text_.splitlines() if not ln.strip().startswith("```")
        )
    start, end = text_.find("{"), text_.rfind("}")
    if start == -1 or end == -1 or end <= start:
        logger.warning("整理归档：模型未返回可解析的 JSON")
        return {}
    try:
        parsed = json.loads(text_[start : end + 1])
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        logger.warning("整理归档：JSON 解析失败")
        return {}
