"""标签服务：CRUD、文档绑定、标签推荐、相似标签检测。"""
from __future__ import annotations

import re
import uuid
from collections import Counter

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.factory import get_provider
from app.core.exceptions import NotFoundError, ValidationError
from app.models import Document, Tag

# 中文词组 / 英文标识符
TOKEN_RE = re.compile(r"[\u4e00-\u9fff]{2,6}|[A-Za-z][A-Za-z0-9_+.#-]{1,24}")
STOPWORDS = {
    "the", "and", "for", "with", "this", "that", "from", "are", "was",
    "to", "in", "on", "at", "of", "by", "or", "as", "be", "is", "it",
    "we", "us", "an", "do", "so", "no", "up", "out", "all", "any", "you",
    "一个", "我们", "可以", "这个", "那个", "因为", "所以", "如果", "但是",
    "然后", "以及", "进行", "使用", "通过", "需要", "就是", "已经", "或者",
}

# 代码噪声：CSS 属性/取值、JS 关键字、HTML 标签名与常见文档词。
# 这些词在代码类文档里词频极高，但作为「标签」毫无语义价值
# （实测 vue.md 曾推荐出 font、style、color、rgb、rgba、const 这类噪声）。
CODE_NOISE = {
    # CSS 属性与取值
    "font", "style", "color", "background", "margin", "padding", "display", "border",
    "width", "height", "position", "top", "left", "right", "bottom", "flex", "grid",
    "align", "justify", "text", "line", "size", "weight", "family", "radius", "shadow",
    "rgba", "rgb", "hsl", "calc", "url", "px", "rem", "vh", "vw", "important",
    "block", "none", "inline", "absolute", "relative", "fixed", "center", "solid",
    # JS / TS 关键字与内置类型
    "const", "let", "var", "function", "return", "import", "export", "default",
    "class", "extends", "async", "await", "this", "new", "typeof", "instanceof",
    "true", "false", "null", "undefined", "if", "else", "for", "while", "try",
    "catch", "switch", "case", "break", "continue", "interface", "enum",
    "public", "private", "static", "void", "string", "number", "boolean", "object",
    # HTML 标签名 / 属性 / 通用词
    "div", "span", "html", "body", "head", "script", "link", "meta", "href", "src",
    "alt", "title", "value", "name", "target", "http", "https", "www", "com", "cn",
    # 文档常见词
    "docs", "doc", "readme", "todo", "note", "markdown", "example", "content",
    # 通用技术词：词频高但作为标签没有区分度
    "path", "next", "see", "message", "module", "property", "file", "dir",
    "folder", "list", "item", "index", "main", "app", "test", "build",
    "config", "setup", "start", "end", "data", "info", "error", "log", "user",
}
# 十六进制颜色值（如 DF2A3F、2a3f）
_HEX_COLOR_RE = re.compile(r"^[0-9A-Fa-f]{3,8}$")


def _is_noise(token: str) -> bool:
    """判断候选词是否为噪声：代码片段、颜色值、纯数字或停用词。"""
    low = token.lower()
    if low in STOPWORDS or low in CODE_NOISE:
        return True
    # 复合形式（background-color、border.radius）逐段判断
    for part in re.split(r"[-.#_+]", low):
        if part and part in CODE_NOISE:
            return True
    if token.isdigit():
        return True
    # 十六进制颜色：必须含数字，避免误杀 add / face 这类正常英文词
    if _HEX_COLOR_RE.match(token) and any(c.isdigit() for c in token):
        return True
    return False


def list_tags(db: Session) -> list[tuple[Tag, int]]:
    """列出标签及其文档数。

    计数**排除回收站文档**，与 `category_service._doc_counts` 口径一致；
    否则删除的文档仍让标签计数虚高（标签管理页与文档列表对不上）。
    使用 `outerjoin(...and_(...))` 把过滤写进 JOIN 的 ON 子句，
    这样没有任何存活文档的标签仍会以计数 0 出现在列表里。
    """
    rows = db.execute(
        select(Tag, func.count(Document.id))
        .outerjoin(Tag.documents.and_(Document.deleted_at.is_(None)))
        .group_by(Tag.id)
        .order_by(Tag.name)
    ).all()
    return [(tag, count) for tag, count in rows]


def get_tag(db: Session, tag_id: uuid.UUID) -> Tag:
    tag = db.get(Tag, tag_id)
    if not tag:
        raise NotFoundError("标签不存在")
    return tag


def create_tag(db: Session, name: str) -> Tag:
    name = name.strip()
    if not name:
        raise ValidationError("标签名不能为空")
    exists = db.execute(select(Tag).where(Tag.name == name)).scalars().first()
    if exists:
        raise ValidationError(f"标签已存在：{name}")
    tag = Tag(name=name)
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag


def update_tag(db: Session, tag_id: uuid.UUID, name: str) -> Tag:
    tag = get_tag(db, tag_id)
    name = name.strip()
    dup = db.execute(
        select(Tag).where(Tag.name == name, Tag.id != tag_id)
    ).scalars().first()
    if dup:
        raise ValidationError(f"标签名已被占用：{name}")
    tag.name = name
    db.commit()
    db.refresh(tag)
    return tag


def delete_tag(db: Session, tag_id: uuid.UUID) -> None:
    tag = get_tag(db, tag_id)
    db.delete(tag)
    db.commit()


def merge_tags(db: Session, source_id: uuid.UUID, target_id: uuid.UUID) -> dict:
    """把「来源标签」合并进「目标标签」，随后删除来源标签。

    用于收拾 `vue` / `Vue` / `vuejs` 这类同一概念的重复标签。
    此前只有「相似检测」，检测出来却没有合并入口，用户只能一篇篇手工改。

    关键处理：某篇文档**同时**挂了两个标签时，直接改挂会撞
    `document_tags` 的 `(document_id, tag_id)` 主键 → 必须先解除来源关联，
    再决定是否新挂目标标签。
    """
    if source_id == target_id:
        raise ValidationError("不能把标签合并到它自己")
    source = get_tag(db, source_id)
    target = get_tag(db, target_id)

    source_name = source.name
    target_doc_ids = {d.id for d in target.documents}
    moved = 0
    for doc in list(source.documents):
        doc.tags.remove(source)
        if doc.id not in target_doc_ids:
            doc.tags.append(target)
            moved += 1

    db.delete(source)
    db.commit()
    return {
        "merged": source_name,
        "target_id": str(target_id),
        "target_name": target.name,
        "moved": moved,
    }


def set_document_tags(db: Session, document_id: uuid.UUID, names: list[str]) -> list[Tag]:
    """设置文档标签（覆盖式）：不存在的标签自动创建。"""
    doc = db.get(Document, document_id)
    if not doc:
        raise NotFoundError("文档不存在")
    tags: list[Tag] = []
    seen: set[uuid.UUID] = set()
    for raw in names:
        name = raw.strip()
        if not name:
            continue
        tag = db.execute(select(Tag).where(Tag.name == name)).scalars().first()
        if not tag:
            tag = Tag(name=name)
            db.add(tag)
            db.flush()
        # 去重：document_tags 主键为 (document_id, tag_id)，
        # 重复名（如前端重复选择、AI 推荐结果重复）会触发 UniqueViolation → 500
        if tag.id in seen:
            continue
        seen.add(tag.id)
        tags.append(tag)
    doc.tags = tags
    db.commit()
    return tags


def suggest_tags(
    db: Session, document_id: uuid.UUID | None, text: str | None, limit: int = 8
) -> list[str]:
    """基于内容推荐标签（确定性启发式，仅作建议）。"""
    content = text or ""
    if document_id and not content:
        doc = db.get(Document, document_id)
        if doc:
            content = doc.content_text or ""
    if not content:
        return []

    existing = [t.name for t in db.execute(select(Tag)).scalars().all()]
    result: list[str] = []

    # 1) 内容中命中的已有标签优先
    for name in existing:
        if name and name in content and name not in result:
            result.append(name)

    # 2) 词频候选（过滤代码噪声、颜色值与停用词）
    counter = Counter(
        tok for tok in TOKEN_RE.findall(content) if len(tok) >= 2 and not _is_noise(tok)
    )
    # 大小写不敏感去重（避免 vue / Vue 同时出现）
    seen_low = {w.lower() for w in result}
    for word, _ in counter.most_common(limit * 3):
        low = word.lower()
        if low in seen_low:
            continue
        seen_low.add(low)
        result.append(word)
        if len(result) >= limit:
            break

    return result[:limit]


def find_similar_tags(db: Session, name: str, threshold: float = 0.6) -> list[str]:
    """基于 PostgreSQL similarity() 找出相似标签。"""
    from sqlalchemy import text as sql_text

    rows = db.execute(
        sql_text(
            "SELECT name, similarity(name, :n) AS s FROM tags "
            "WHERE similarity(name, :n) >= :th ORDER BY s DESC"
        ),
        {"n": name, "th": threshold},
    ).all()
    return [r[0] for r in rows]


# ---------------- AI 标签推荐 ----------------
TAG_AI_SYSTEM_PROMPT = """你是知识管理助手，负责为一篇文档提取检索标签。

要求：
1. 只输出标签本身，用中文逗号「，」分隔；不要编号、不要解释、不要加引号。
2. 标签应是能概括文档**主题**的概念词（如「Docker」「容器编排」「数据卷」「镜像构建」），
   而不是：代码符号（font、color、rgb）、十六进制颜色（DF2A3F）、
   编程语言关键字（const、return）、通用词（使用、配置、说明）或单个字符。
3. 每个标签 2~8 个字；优先采用文档中反复出现、或作为小标题出现的术语。
4. 输出 5~8 个标签，按重要性从高到低排列。
"""


def _parse_tag_list(raw: str, limit: int) -> list[str]:
    """把模型输出解析为标签列表（容错各种分隔与编号形式）。"""
    text = (raw or "").strip()
    if not text:
        return []
    # 去掉行首编号（1. / 2、/ 3)）
    text = re.sub(r"^\s*\d+\s*[.、)]\s*", "", text, flags=re.M)
    parts = re.split(r"[，,、\n;；|]+", text)
    result: list[str] = []
    seen: set[str] = set()
    for part in parts:
        tag = part.strip().strip("\"'“”‘’*#-· ").strip()
        if not tag or len(tag) > 12 or _is_noise(tag):
            continue
        low = tag.lower()
        if low in seen:
            continue
        seen.add(low)
        result.append(tag)
        if len(result) >= limit:
            break
    return result


async def suggest_tags_ai(
    db: Session,
    document_id: uuid.UUID | None = None,
    text: str | None = None,
    limit: int = 8,
) -> list[str]:
    """用对话模型提取标签。

    相比词频启发式，模型能判断「这段内容讲的是什么主题」，
    不会把 font / color / DF2A3F 这类高频代码符号误当成标签。
    """
    content = (text or "").strip()
    title = ""
    if document_id:
        doc = db.get(Document, document_id)
        if doc:
            title = doc.title
            if not content:
                content = doc.content_text or ""
    if not content:
        return []

    # 标签来自主题，取开头一段即可（同时控制 token 成本）
    excerpt = content[:3000]
    messages = [
        {"role": "system", "content": TAG_AI_SYSTEM_PROMPT},
        {"role": "user", "content": f"文档标题：{title}\n\n文档内容（节选）：\n{excerpt}"},
    ]
    provider = get_provider()
    raw = await provider.chat(messages, stream=False)
    return _parse_tag_list(str(raw), limit)
