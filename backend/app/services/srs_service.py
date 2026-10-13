"""间隔复习服务（SRS / SM-2）。

对应 LocalMind「闪卡与间隔复习」：
- 正面问题、背面答案；
- 依据记忆情况（评分 0~5）安排下次复习时间；
- 记录掌握程度与复习历史。

算法采用 **SM-2**（SuperMemo 2），评分口径与 Anki 的「重来/困难/一般/简单」可一一对应：
| 界面按钮 | rating | 含义 |
|---|---|---|
| 重来 | 1 | 完全不会，重置进度，10 分钟后再来 |
| 困难 | 3 | 勉强答对，间隔小幅增长 |
| 一般 | 4 | 答对，正常增长 |
| 简单 | 5 | 轻松答对，间隔明显增长 |

约束：卡片必须可追溯到原资料（`document_id` / `source_chunk_id`），
生成卡片时一律记录来源，便于用户核对。
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models import Document, Flashcard, ReviewLog
from app.models.flashcard import CARD_LEARNING, CARD_NEW, CARD_REVIEW

logger = get_logger(__name__)

# SM-2 参数
EASE_DEFAULT = 2.5
EASE_MIN = 1.3
PASS_RATING = 3  # >= 3 视为通过
RELEARN_MINUTES = 10  # 未通过时的再学间隔
MAX_INTERVAL_DAYS = 365 * 3
MAX_CARDS_PER_DOC = 100


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------- 卡片 CRUD ----------------
def get_card(db: Session, card_id: uuid.UUID) -> Flashcard:
    card = db.get(Flashcard, card_id)
    if not card:
        raise NotFoundError("卡片不存在")
    return card


def create_card(
    db: Session,
    front: str,
    back: str,
    document_id: uuid.UUID | None = None,
    source_chunk_id: uuid.UUID | None = None,
    tags: list[str] | None = None,
) -> Flashcard:
    front = (front or "").strip()
    back = (back or "").strip()
    if not front or not back:
        raise ValidationError("卡片的正面与背面都不能为空")

    card = Flashcard(
        front=front,
        back=back,
        document_id=document_id,
        source_chunk_id=source_chunk_id,
        tags=tags,
        state=CARD_NEW,
        ease=EASE_DEFAULT,
        interval_days=0,
        repetitions=0,
        lapses=0,
        due_at=_now(),  # 新建即到期，可立即复习
    )
    db.add(card)
    db.commit()
    db.refresh(card)
    return card


def create_cards_bulk(db: Session, items: list[dict]) -> list[Flashcard]:
    """批量创建（AI 生成结果落库用）。"""
    cards: list[Flashcard] = []
    now = _now()
    for item in items[:MAX_CARDS_PER_DOC]:
        front = str(item.get("front") or "").strip()
        back = str(item.get("back") or "").strip()
        if not front or not back:
            continue
        card = Flashcard(
            front=front,
            back=back,
            document_id=item.get("document_id"),
            source_chunk_id=item.get("source_chunk_id"),
            tags=item.get("tags"),
            state=CARD_NEW,
            ease=EASE_DEFAULT,
            interval_days=0,
            repetitions=0,
            lapses=0,
            due_at=now,
        )
        db.add(card)
        cards.append(card)
    if cards:
        db.commit()
        for c in cards:
            db.refresh(c)
    return cards


def update_card(
    db: Session,
    card_id: uuid.UUID,
    front: str | None = None,
    back: str | None = None,
    suspended: bool | None = None,
) -> Flashcard:
    card = get_card(db, card_id)
    if front is not None:
        if not front.strip():
            raise ValidationError("卡片正面不能为空")
        card.front = front.strip()
    if back is not None:
        if not back.strip():
            raise ValidationError("卡片背面不能为空")
        card.back = back.strip()
    if suspended is not None:
        card.suspended = bool(suspended)
    db.commit()
    db.refresh(card)
    return card


def delete_card(db: Session, card_id: uuid.UUID) -> None:
    card = get_card(db, card_id)
    db.delete(card)
    db.commit()


def list_cards(
    db: Session,
    due_only: bool = False,
    document_id: uuid.UUID | None = None,
    include_suspended: bool = False,
    limit: int = 200,
) -> list[Flashcard]:
    """列出卡片；due_only=True 时只返回已到期的（复习队列）。"""
    stmt = select(Flashcard)
    if not include_suspended:
        stmt = stmt.where(Flashcard.suspended.is_(False))
    if document_id:
        stmt = stmt.where(Flashcard.document_id == document_id)
    if due_only:
        # 未设 due_at 的也视为到期（历史数据兜底）
        stmt = stmt.where(
            (Flashcard.due_at.is_(None)) | (Flashcard.due_at <= _now())
        )
    stmt = stmt.order_by(Flashcard.due_at.asc().nulls_first()).limit(limit)
    return list(db.execute(stmt).scalars().all())


# ---------------- SM-2 ----------------
def apply_review(db: Session, card: Flashcard, rating: int) -> Flashcard:
    """按 SM-2 更新卡片状态，并写入一条复习记录。"""
    if not 0 <= rating <= 5:
        raise ValidationError("评分必须在 0~5 之间")

    prev_interval = card.interval_days
    ease = card.ease or EASE_DEFAULT
    reps = card.repetitions or 0

    if rating >= PASS_RATING:
        reps += 1
        if reps == 1:
            interval = 1
        elif reps == 2:
            interval = 6
        else:
            interval = max(1, round(prev_interval * ease))
        interval = min(interval, MAX_INTERVAL_DAYS)
        due_at = _now() + timedelta(days=interval)
        state = CARD_REVIEW if interval >= 1 else CARD_LEARNING
    else:
        # 未通过：重置连续次数，10 分钟后再来（当天内消化）
        reps = 0
        interval = 0
        due_at = _now() + timedelta(minutes=RELEARN_MINUTES)
        state = CARD_LEARNING
        card.lapses = (card.lapses or 0) + 1

    # 难度系数更新（SM-2 标准公式）
    ease = ease + (0.1 - (5 - rating) * (0.08 + (5 - rating) * 0.02))
    ease = max(EASE_MIN, round(ease, 4))

    card.ease = ease
    card.repetitions = reps
    card.interval_days = interval
    card.state = state
    card.due_at = due_at
    card.last_reviewed_at = _now()

    db.add(
        ReviewLog(
            flashcard_id=card.id,
            rating=rating,
            prev_interval=prev_interval,
            next_interval=interval,
            ease_after=ease,
        )
    )
    db.commit()
    db.refresh(card)
    return card


# ---------------- 统计 ----------------
def due_count(db: Session) -> int:
    return db.execute(
        select(func.count())
        .select_from(Flashcard)
        .where(
            Flashcard.suspended.is_(False),
            (Flashcard.due_at.is_(None)) | (Flashcard.due_at <= _now()),
        )
    ).scalar_one()


def _reviewed_days(db: Session) -> list[date]:
    """有复习记录的日期（倒序去重）。"""
    rows = db.execute(
        select(func.date(ReviewLog.reviewed_at)).distinct().order_by(
            func.date(ReviewLog.reviewed_at).desc()
        )
    ).all()
    return [r[0] for r in rows if r[0]]


def _streak(days: list[date]) -> int:
    """连续学习天数（从今天或昨天开始往前数）。"""
    if not days:
        return 0
    today = date.today()
    # 允许「今天还没复习」但不打断连续（从昨天起算）
    start = today if days[0] == today else (today - timedelta(days=1))
    if days[0] != start:
        return 0
    streak = 0
    cursor = start
    for d in days:
        if d == cursor:
            streak += 1
            cursor = cursor - timedelta(days=1)
        elif d < cursor:
            break
    return streak


def review_daily(db: Session, days: int = 14) -> list[dict]:
    """最近 N 天的每日复习次数（没有复习的日期补 0，便于直接画趋势）。

    只统计真实存在的复习记录（`review_logs`），因此"最近很努力"是真实的，
    不会因为补了 0 而看起来像在下降——0 恰恰是"那天没复习"的事实。
    """
    days = max(1, min(int(days or 14), 90))
    today = date.today()
    start = today - timedelta(days=days - 1)
    rows = db.execute(
        select(func.date(ReviewLog.reviewed_at), func.count())
        .where(func.date(ReviewLog.reviewed_at) >= start)
        .group_by(func.date(ReviewLog.reviewed_at))
    ).all()
    counts = {r[0]: r[1] for r in rows if r[0]}
    return [
        {
            "date": (day := start + timedelta(days=i)).isoformat(),
            "count": counts.get(day, 0),
        }
        for i in range(days)
    ]


def mastery_distribution(db: Session) -> list[dict]:
    """掌握程度分布：按当前复习间隔把卡片分档。

    为什么用**间隔**而不是 `state` 字段分档：SM-2 的 interval 就是算法对
    「你记得多牢」的直接量化——间隔越长说明越牢。`state` 只有三档且划分粗
    （learning/review 的边界是「间隔是否进入天级」），看不出梯度。

    分档口径（与常见记忆工具一致）：
    - 新学：尚未开始复习
    - 1 天内 / 2-3 天 / 4-7 天 / 8-15 天 / 16-30 天 / 30 天以上
    """
    rows = db.execute(
        select(Flashcard.state, Flashcard.interval_days).where(
            Flashcard.suspended.is_(False)
        )
    ).all()
    buckets = [
        ("新学", 0),
        ("1 天内", 0),
        ("2-3 天", 0),
        ("4-7 天", 0),
        ("8-15 天", 0),
        ("16-30 天", 0),
        ("30 天以上", 0),
    ]

    def _idx(state: str, interval: int) -> int:
        if state == CARD_NEW:
            return 0
        if interval <= 1:
            return 1
        if interval <= 3:
            return 2
        if interval <= 7:
            return 3
        if interval <= 15:
            return 4
        if interval <= 30:
            return 5
        return 6

    counts = [0] * len(buckets)
    for state, interval in rows:
        counts[_idx(state or CARD_NEW, int(interval or 0))] += 1

    return [
        {"label": label, "count": count} for (label, _), count in zip(buckets, counts)
    ]


def retention_curve(db: Session, days: int = 90) -> list[dict]:
    """遗忘曲线：按复习间隔统计**实际回忆成功率**。

    这是从 `review_logs` 里真实算出来的，不是教科书上的理论曲线——
    每档取「上次间隔落在该区间的复习」中，评分 >=3（SM-2 口径的「通过」）
    所占比例。间隔越长通过率越低，就是你自己在这套资料上的遗忘曲线。

    为什么用 `prev_interval`（上次间隔）而不是 `next_interval`：
    回忆成功率对应的是「顶着多大的间隔还能想起来」，而这次复习考验的正是
    上次留下的那个间隔。
    """
    rows = db.execute(
        select(ReviewLog.prev_interval, ReviewLog.rating).where(
            ReviewLog.reviewed_at >= datetime.now(timezone.utc) - timedelta(days=days)
        )
    ).all()

    buckets = [
        ("新学", 0),
        ("1 天内", 0),
        ("2-3 天", 0),
        ("4-7 天", 0),
        ("8-15 天", 0),
        ("16-30 天", 0),
        ("30 天以上", 0),
    ]

    def _idx(interval: int) -> int:
        if interval <= 0:
            return 0
        if interval <= 1:
            return 1
        if interval <= 3:
            return 2
        if interval <= 7:
            return 3
        if interval <= 15:
            return 4
        if interval <= 30:
            return 5
        return 6

    total = [0] * len(buckets)
    passed = [0] * len(buckets)
    for prev_interval, rating in rows:
        i = _idx(int(prev_interval or 0))
        total[i] += 1
        if (rating or 0) >= 3:
            passed[i] += 1

    out = []
    for (label, _), tot, ok in zip(buckets, total, passed):
        out.append(
            {
                "label": label,
                "attempts": tot,
                "passed": ok,
                # 没有数据的档位返回 None（而不是 0），前端才能区分
                # 「这段时间没复习」和「复习了但全忘」——两者含义完全不同
                "rate": round(ok / tot, 4) if tot else None,
            }
        )
    return out


def review_stats(db: Session) -> dict:
    """复习概览：待复习 / 各状态数量 / 今日已复习 / 连续天数 / 近两周趋势。"""
    total = db.execute(select(func.count()).select_from(Flashcard)).scalar_one()
    by_state = {
        state: n
        for state, n in db.execute(
            select(Flashcard.state, func.count()).group_by(Flashcard.state)
        ).all()
    }
    today = date.today()
    reviewed_today = db.execute(
        select(func.count())
        .select_from(ReviewLog)
        .where(func.date(ReviewLog.reviewed_at) == today)
    ).scalar_one()
    days = _reviewed_days(db)
    return {
        "total": total,
        "due": due_count(db),
        "new": by_state.get(CARD_NEW, 0),
        "learning": by_state.get(CARD_LEARNING, 0),
        "review": by_state.get(CARD_REVIEW, 0),
        "suspended": db.execute(
            select(func.count())
            .select_from(Flashcard)
            .where(Flashcard.suspended.is_(True))
        ).scalar_one(),
        "reviewed_today": reviewed_today,
        "streak_days": _streak(days),
        "reviewed_days": len(days),
        # 近两周每日复习量（趋势图数据）
        "daily": review_daily(db),
        # 掌握程度分布（按复习间隔分档）
        "mastery": mastery_distribution(db),
        # 遗忘曲线（按间隔统计实际回忆成功率）
        "retention": retention_curve(db),
    }


def card_out(card: Flashcard) -> dict:
    return {
        "id": str(card.id),
        "front": card.front,
        "back": card.back,
        "document_id": str(card.document_id) if card.document_id else None,
        "source_chunk_id": str(card.source_chunk_id) if card.source_chunk_id else None,
        "tags": card.tags or [],
        "state": card.state,
        "ease": card.ease,
        "interval_days": card.interval_days,
        "repetitions": card.repetitions,
        "lapses": card.lapses,
        "due_at": card.due_at.isoformat() if card.due_at else None,
        "last_reviewed_at": (
            card.last_reviewed_at.isoformat() if card.last_reviewed_at else None
        ),
        "suspended": card.suspended,
        "created_at": card.created_at.isoformat() if card.created_at else None,
    }


# ---------------- 导出 ----------------

# Anki 文本导入格式的头部指令（以 # 开头的行是注释/元数据，不会变成卡片）
_ANKI_HEADER = [
    "#separator:tab",
    "#html:true",
    "#columns:Front\tBack\tTags",
    "#deck:KnowledgeHub",
    "#notetype:Basic",
]


def _anki_field(text: str) -> str:
    """把一个字段转成 Anki 文本导入能安全接受的形态。

    Anki 用 tab 分列、用换行分行，所以这两类字符必须处理：
    - tab → 空格（否则整行列数错位，后面的列全部串味）
    - 换行 → `<br>`（html:true 模式下 Anki 会正确渲染成换行）
    另外把 HTML 标签转义，避免用户笔记里的 `<script>` 之类被当成富文本执行。
    """
    import html as _html

    # 顺序很重要：先转义 HTML，再把换行换成 <br>。
    # 反过来会把自己插入的 <br> 也转义掉，Anki 里就会显示字面量 "<br>"。
    out = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    out = out.replace("\t", " ")
    out = _html.escape(out, quote=False)
    return out.replace("\n", "<br>")


def _anki_tags(tags: list | None) -> str:
    """Anki 的 Tags 列是空格分隔的多个标签；标签名里的空格换成下划线。"""
    if not tags:
        return ""
    cleaned = []
    for t in tags:
        name = str(t).strip().replace(" ", "_").replace("\t", "_")
        if name:
            cleaned.append(name)
    return " ".join(cleaned)


def export_anki_text(
    db: Session,
    document_id: uuid.UUID | None = None,
    include_suspended: bool = False,
    limit: int = 2000,
) -> str:
    """导出为 Anki 文本导入格式（TSV）。

    Anki 导入时选「文件 → 导入」，勾选「允许 HTML」即可。
    刻意不导 SM-2 状态（Anki 有自己的调度算法，导入后按新卡片重新排期），
    只导 Front / Back / Tags —— 带上自定义的 ease/interval 反而会打乱
    Anki 自己的安排。
    """
    cards = list_cards(
        db,
        document_id=document_id,
        include_suspended=include_suspended,
        limit=limit,
    )
    lines = list(_ANKI_HEADER)
    for card in cards:
        lines.append(
            "\t".join(
                [
                    _anki_field(card.front),
                    _anki_field(card.back),
                    _anki_tags(card.tags),
                ]
            )
        )
    return "\n".join(lines) + "\n"


# ---------------- AI 生成卡片 ----------------
CARD_PROMPT = """你是学习卡片制作助手。请把给定资料整理成便于记忆的问答卡片。

要求：
1. 只依据资料内容出题，**不要编造资料里没有的知识**。
2. 每张卡片聚焦一个知识点；正面是**问题**，背面是**简洁的答案**（1~3 句）。
3. 优先覆盖：核心概念、易混淆点、操作步骤、常见错误。
4. 严格输出 JSON 数组，不要输出任何解释或代码块标记：
[{"front": "问题", "back": "答案"}]
5. 数量控制在用户要求的条数内；资料不足以出这么多题时，宁可少出。"""


async def _cards_from_text(
    db: Session,
    text: str,
    count: int,
    document_id: uuid.UUID | None = None,
) -> list[Flashcard]:
    """把一段资料交给模型生成卡片并落库（文档与「选中文字」共用）。"""
    from app.ai.factory import get_provider
    from app.core.exceptions import AIUnavailableError
    from app.services.learning_service import _parse_json

    count = max(1, min(int(count or 8), MAX_CARDS_PER_DOC))
    messages = [
        {"role": "system", "content": CARD_PROMPT},
        {
            "role": "user",
            "content": f"请生成 {count} 张卡片。资料如下：\n\n{text[:6000]}",
        },
    ]
    try:
        raw = await get_provider().chat(messages, stream=False)
    except AIUnavailableError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise AIUnavailableError(f"生成卡片失败：{exc}") from exc

    items = _parse_json(str(raw), list)
    if not isinstance(items, list):
        return []

    payload = [
        {
            "front": str(it.get("front") or ""),
            "back": str(it.get("back") or ""),
            "document_id": document_id,
        }
        for it in items
        if isinstance(it, dict)
    ]
    return create_cards_bulk(db, payload)


async def generate_cards_ai(
    db: Session, document_id: uuid.UUID, count: int = 8
) -> list[Flashcard]:
    """依据某篇笔记生成闪卡（AI）。资料不足时返回空列表，不编造。"""
    doc = db.get(Document, document_id)
    if not doc or doc.deleted_at is not None:
        raise NotFoundError("文档不存在")
    text = (doc.content_text or "").strip()
    if len(text) < 40:
        raise ValidationError("文档内容过少，无法生成卡片")
    return await _cards_from_text(db, text, count, document_id=doc.id)


async def generate_cards_from_text(
    db: Session,
    text: str,
    count: int = 5,
    document_id: uuid.UUID | None = None,
) -> list[Flashcard]:
    """从「选中的一段文字」生成卡片（笔记页内呼出 AI 用）。"""
    text = (text or "").strip()
    if len(text) < 20:
        raise ValidationError("选中的内容过少，无法生成卡片")
    return await _cards_from_text(db, text, count, document_id=document_id)
