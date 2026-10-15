"""PDF 批注服务：增删改查 + 导出为可检索笔记。

## 这个模块的设计主线

1. **锚点是引文，不是坐标**。`quote` 是身份，`rects` 只是渲染用的缓存。
   所以校验时对引文的把关最严（非空、限长），对坐标只做「别越界」的检查。
2. **批注不进向量库**。导出成一篇普通 `.md` 笔记后，
   混合检索 / 拼音 / 拼错容错 / 双链 / 相关笔记**全部自动可用**，
   `retriever.py` 一行不改。这是整个方案最大的杠杆点。
3. **导出是幂等的**。同一份 PDF 反复导出只会更新那一篇笔记，不会堆积副本
   ——否则用户点三次导出就会有三篇高度重复的笔记污染检索结果。
"""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models import Document, PdfAnnotation
from app.models.pdf_annotation import (
    ANNOTATION_COLORS,
    DEFAULT_ANNOTATION_COLOR,
    MAX_CONTEXT_LEN,
    MAX_QUOTE_LEN,
)

# 坐标容许的浮点误差：前端除以页面宽高后会有末位浮动
_COORD_TOL = 1e-6

# 导出笔记的标题后缀。用中文书名号包住原文档名，
# 既一眼能看出「这是某篇的批注」，也让同一篇的重复导出能靠标题找到旧笔记。
_EXPORT_SUFFIX = " 批注"


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------

def _require_pdf(db: Session, document_id: uuid.UUID) -> Document:
    """批注只对 PDF 有意义——它的锚点建立在「页」这个概念上。"""
    from app.services import document_service

    doc = document_service.get_document(db, document_id)
    ext = (doc.file_type or "").lower().lstrip(".")
    if ext != "pdf":
        raise ValidationError("只有 PDF 文档支持批注（其它格式没有「页」这一层结构）")
    return doc


def _clean_rects(raw: object) -> list[dict]:
    """校验并规范化矩形数组。

    只做三件事：字段齐全、数值有限、落在页面内。
    刻意**不**检查矩形之间是否重叠——跨行选择必然产生多个矩形，
    合并是前端渲染的职责，后端不该替它决定怎么画。
    """
    if not isinstance(raw, list) or not raw:
        raise ValidationError("高亮区域不能为空")

    out: list[dict] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValidationError(f"第 {i + 1} 个高亮区域格式不正确")
        try:
            x = float(item["x"])
            y = float(item["y"])
            w = float(item["w"])
            h = float(item["h"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError(
                f"第 {i + 1} 个高亮区域缺少 x/y/w/h 或不是数字"
            ) from exc

        if not all(map(_is_finite, (x, y, w, h))):
            raise ValidationError(f"第 {i + 1} 个高亮区域含非法数值")
        if w <= 0 or h <= 0:
            raise ValidationError(f"第 {i + 1} 个高亮区域宽或高为 0")
        # 越界不报错而是**裁剪**：拖选到页边之外是常见操作，
        # 为此拒掉整条批注会让用户莫名其妙地存不上
        x = min(max(x, 0.0), 1.0)
        y = min(max(y, 0.0), 1.0)
        w = min(w, 1.0 - x)
        h = min(h, 1.0 - y)
        if w <= _COORD_TOL or h <= _COORD_TOL:
            continue
        out.append(
            {"x": round(x, 6), "y": round(y, 6), "w": round(w, 6), "h": round(h, 6)}
        )

    if not out:
        raise ValidationError("高亮区域全部落在页面之外，无法保存")
    return out


def _is_finite(v: float) -> bool:
    return v == v and v not in (float("inf"), float("-inf"))


def _clean_text(value: str | None, limit: int, field: str) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) > limit:
        raise ValidationError(f"{field}过长（上限 {limit} 字符）")
    return text


def _clean_color(color: str | None) -> str:
    name = (color or DEFAULT_ANNOTATION_COLOR).strip().lower()
    if name not in ANNOTATION_COLORS:
        raise ValidationError(
            f"不支持的颜色 {color!r}；可用：{'、'.join(sorted(ANNOTATION_COLORS))}"
        )
    return name


# ---------------------------------------------------------------------------
# 增删改查
# ---------------------------------------------------------------------------

def ensure_document_exists(db: Session, document_id: uuid.UUID) -> Document:
    """只校验文档存在（不存在则 404），**不要求是 PDF**。

    列表查询刻意比写入宽松：前端为了显示「本文档有 N 条批注」会对每篇文档都查一次，
    若非 PDF 直接报错，普通笔记页上就会一直弹无意义的提示。
    而「笔记的批注数为 0」本身是正确且无害的答案。
    """
    from app.services import document_service

    return document_service.get_document(db, document_id)


def list_annotations(
    db: Session, document_id: uuid.UUID, page_no: int | None = None
) -> list[PdfAnnotation]:
    """按页顺序列出批注；`page_no` 给定时只返回该页。"""
    stmt = select(PdfAnnotation).where(PdfAnnotation.document_id == document_id)
    if page_no is not None:
        stmt = stmt.where(PdfAnnotation.page_no == page_no)
    stmt = stmt.order_by(PdfAnnotation.page_no, PdfAnnotation.created_at)
    return list(db.execute(stmt).scalars().all())


def count_annotations(db: Session, document_id: uuid.UUID) -> int:
    return int(
        db.execute(
            select(func.count())
            .select_from(PdfAnnotation)
            .where(PdfAnnotation.document_id == document_id)
        ).scalar_one()
    )


def create_annotation(
    db: Session,
    document_id: uuid.UUID,
    page_no: int,
    quote: str,
    rects: object,
    prefix: str | None = None,
    suffix: str | None = None,
    rotation: int = 0,
    color: str | None = None,
    comment: str | None = None,
) -> PdfAnnotation:
    """新建一条高亮/批注。"""
    _require_pdf(db, document_id)

    if not isinstance(page_no, int) or page_no < 1:
        raise ValidationError("页码必须是不小于 1 的整数")

    clean_quote = _clean_text(quote, MAX_QUOTE_LEN, "引文")
    if not clean_quote:
        raise ValidationError("引文不能为空（它是批注的主锚，丢了就无法重新定位）")

    clean_rects = _clean_rects(rects)
    clean_prefix = _clean_text(prefix, MAX_CONTEXT_LEN, "前文")
    clean_suffix = _clean_text(suffix, MAX_CONTEXT_LEN, "后文")
    clean_comment = _clean_text(comment, 20_000, "批注")

    if not isinstance(rotation, int) or rotation % 90 != 0:
        raise ValidationError("页面旋转角必须是 90 的整数倍")

    # 防重复提交：同页、同引文、同一个起始矩形 → 视为同一条。
    # 双击按钮、网络重试都可能触发，产生两条完全重合的高亮只会让人困惑。
    first = clean_rects[0]
    existing = db.execute(
        select(PdfAnnotation).where(
            PdfAnnotation.document_id == document_id,
            PdfAnnotation.page_no == page_no,
            PdfAnnotation.quote == clean_quote,
        )
    ).scalars().all()
    for item in existing:
        rects_list = item.rects or []
        if rects_list and _same_rect(rects_list[0], first):
            raise ConflictError("该位置已经有同一条批注了")

    ann = PdfAnnotation(
        document_id=document_id,
        page_no=page_no,
        quote=clean_quote,
        prefix=clean_prefix,
        suffix=clean_suffix,
        rects=clean_rects,
        rotation=rotation,
        color=_clean_color(color),
        comment=clean_comment,
    )
    db.add(ann)
    db.commit()
    db.refresh(ann)
    return ann


def _same_rect(a: dict, b: dict) -> bool:
    return all(abs(float(a.get(k, 0)) - float(b.get(k, 0))) < 1e-4 for k in "xywh")


def get_annotation(db: Session, annotation_id: uuid.UUID) -> PdfAnnotation:
    ann = db.get(PdfAnnotation, annotation_id)
    if ann is None:
        raise NotFoundError("批注不存在")
    return ann


def update_annotation(
    db: Session,
    annotation_id: uuid.UUID,
    color: str | None = None,
    comment: str | None = None,
    touch_comment: bool = False,
) -> PdfAnnotation:
    """改颜色或批注文字。

    `comment` 用 `touch_comment` 区分「没传」与「传了空字符串」——
    后者是用户主动清空批注，应该真的清空而不是被当成没改。
    """
    ann = get_annotation(db, annotation_id)
    if color is not None:
        ann.color = _clean_color(color)
    if touch_comment:
        ann.comment = _clean_text(comment, 20_000, "批注")
    db.commit()
    db.refresh(ann)
    return ann


def delete_annotation(db: Session, annotation_id: uuid.UUID) -> None:
    ann = get_annotation(db, annotation_id)
    db.delete(ann)
    db.commit()


# ---------------------------------------------------------------------------
# 导出为笔记（接进「写入 / 关联 / 复习」三个闭环）
# ---------------------------------------------------------------------------

def _render_export(doc: Document, annotations: list[PdfAnnotation]) -> str:
    """把批注渲染成 Markdown。

    两个刻意的写法：

    * 顶部写 `[[文档标题]]` 双链 —— 这让导出的批注笔记与 PDF 文档**互相反向链接**，
      于是知识图谱里能直接看到「这篇 PDF 有哪些批注」。
      这是「关联闭环」的接入点，零额外代码。
    * 每条批注把**引文放进引用块**、批注文字放正文 —— 读起来是
      「原话 + 我的想法」，而不是一堆没有上下文的碎句。
    """
    pages = sorted({a.page_no for a in annotations})
    lines = [
        f"> 来源：[[{doc.title}]]",
        f"> 共 {len(annotations)} 条批注，覆盖 {len(pages)} 页",
        "",
    ]

    current_page: int | None = None
    for ann in annotations:
        if ann.page_no != current_page:
            current_page = ann.page_no
            lines.extend([f"## 第 {current_page} 页", ""])

        quote = (ann.quote or "").replace("\n", " ").strip()
        lines.append(f"> {quote}")
        lines.append("")
        if ann.comment:
            lines.append(ann.comment.strip())
            lines.append("")
        # 元信息放在最后一行、用斜体，避免打断阅读节奏
        lines.append(f"*第 {ann.page_no} 页 · {ann.color}*")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


async def export_annotations(
    db: Session, document_id: uuid.UUID
) -> tuple[Document, int, bool]:
    """把批注导出成一篇笔记。返回 (笔记文档, 批注条数, 是否新建)。

    **幂等**：若已存在同名的导出笔记则原地更新，而不是再建一篇。
    否则用户点三次导出就会有三篇内容高度重复的笔记，反而污染检索结果。
    """
    from app.services import document_service

    doc = _require_pdf(db, document_id)
    annotations = list_annotations(db, document_id)
    if not annotations:
        raise ValidationError("这份 PDF 还没有批注，没有可导出的内容")

    title = f"《{doc.title}》{_EXPORT_SUFFIX}"
    content = _render_export(doc, annotations)

    existing = db.execute(
        select(Document)
        .where(Document.title == title, Document.deleted_at.is_(None))
        .order_by(Document.created_at)
    ).scalars().first()

    if existing is not None:
        # 原地更新：走 update_document 才能拿到「版本快照 + 写回磁盘 + 重建索引」
        # 三件套，自己改 content_text 会让索引和磁盘文件脱节
        updated = await document_service.update_document(
            db, existing.id, content_text=content
        )
        return updated, len(annotations), False

    note = await document_service.create_note(
        db,
        title=title,
        content_text=content,
        # 从 PDF 里摘出来的原文与自己的批注，跟 PDF 本身是同一批资料的可见性
        ai_enabled=doc.ai_enabled,
        source="annotation",
    )
    return note, len(annotations), True


def quote_for_card(db: Session, annotation_id: uuid.UUID) -> str:
    """取一条批注用于生成闪卡的文本。

    优先用「引文 + 批注」：单用引文出不了好题（原文往往不是疑问句），
    单用批注又缺了上下文。
    """
    ann = get_annotation(db, annotation_id)
    parts = [ann.quote or ""]
    if ann.comment:
        parts.append(ann.comment)
    return "\n\n".join(p for p in parts if p).strip()
