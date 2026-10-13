"""轻量查询分词：为关键词检索提供可匹配的词项。

**中文分词策略**（按可用性自动降级）：
1. **jieba**（推荐）：精确分词，提取真实词语（如「响应式」「丢失」「解决」），
   比固定 2-gram 的信噪比高很多。`pip install jieba` 即启用。
2. **2-gram**（兜底）：jieba 不可用时回退到固定 2-gram 切分，
   配合 pg_trgm 的 ILIKE 做多词命中计数。

**为什么改分词器不需要重建索引**：`keyword_search` 里的
`ILIKE '%' || term || '%'` 是对 `chunks.content` 做子串匹配，pg_trgm GIN 索引
支持任意子串。分词器只影响**查询端**提取哪些词，不影响索引结构。

英文处理两种模式相同：整词提取 + 停用词过滤。
"""
from __future__ import annotations

import re

# 尝试导入 jieba（可选依赖，pip install jieba）
try:
    import jieba
    import jieba.analyse

    _HAS_JIEBA = True
except ImportError:
    _HAS_JIEBA = False

# 英文 / 数字 / 标识符
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+.#-]{1,30}")
# 中文连续片段
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")

# 英文停用词
STOPWORDS_EN = {
    "the", "and", "for", "with", "this", "that", "from", "are", "was", "were",
    "what", "why", "how", "when", "where", "which", "who", "can", "could",
    "should", "would", "does", "did", "is", "are", "not", "but", "you", "your",
}

# 中文停用词（jieba 分词后过滤）
STOPWORDS_CJK_WORD = {
    "什么", "怎么", "为什么", "哪些", "哪个", "如何", "是否",
    "可以", "需要", "以及", "但是", "因为", "所以", "如果", "这个", "那个",
    "一个", "我们", "你们", "他们", "就是", "已经", "或者", "而且", "然后",
    "由于", "为了", "通过", "进行", "使用", "时候", "请问", "一下", "能否",
    "没有", "还有", "这些", "那些", "还是", "不是", "比如", "例如",
}

# 中文停用 2-gram（疑问词 / 连接词等噪声，兜底模式用）
STOPWORDS_CJK_BIGRAM = {
    "什么", "怎么", "为什", "么会", "么样", "哪些", "哪个", "如何", "是否",
    "可以", "需要", "以及", "但是", "因为", "所以", "如果", "这个", "那个",
    "一个", "我们", "你们", "他们", "就是", "已经", "或者", "而且", "然后",
    "由于", "为了", "通过", "进行", "使用", "时候", "请问", "一下", "能否",
    "的区", "区别", "是什", "么意", "什么",
}

# 查询很短时（<=该长度）额外把整串作为一个词项，保证精确子串仍能命中
SHORT_QUERY_LEN = 8


def _has_cjk(text: str) -> bool:
    return bool(_CJK_RUN_RE.search(text))


def extract_terms(query: str, limit: int = 24) -> list[str]:
    """从查询中提取词项列表（去重、保序）。

    jieba 可用时用精确分词提取真实词语（信噪比更高）；
    不可用时回退到固定 2-gram。
    """
    query = (query or "").strip()
    if not query:
        return []

    terms: list[str] = []
    seen: set[str] = set()

    def add(term: str) -> None:
        key = term.lower()
        if key and key not in seen:
            seen.add(key)
            terms.append(term)

    # 1) 英文整词（两种模式相同）
    for word in _WORD_RE.findall(query):
        if word.lower() not in STOPWORDS_EN:
            add(word)

    # 2) 中文分词
    if _HAS_JIEBA:
        _extract_cjk_jieba(query, add)
    else:
        _extract_cjk_bigram(query, add)

    # 3) 短查询额外加入整串（如「响应式」这类单个关键词）
    if len(query) <= SHORT_QUERY_LEN:
        add(query)

    return terms[:limit]


def _extract_cjk_jieba(query: str, add) -> None:
    """jieba 精确分词：提取长度 >= 2 的中文词语，过滤停用词。"""
    for run in _CJK_RUN_RE.findall(query):
        if len(run) < 2:
            continue
        # jieba.cut 对纯中文串做精确模式分词
        words = jieba.cut(run, cut_all=False)
        for word in words:
            word = word.strip()
            if len(word) >= 2 and word not in STOPWORDS_CJK_WORD:
                add(word)
            # 单字也有价值时保留（如「卷」「库」「图」在技术语境中可能是有意义的词）
            elif len(word) == 1 and run == word:
                add(word)


def _extract_cjk_bigram(query: str, add) -> None:
    """兜底：固定 2-gram 切分 + 停用词过滤。"""
    for run in _CJK_RUN_RE.findall(query):
        if len(run) < 2:
            continue
        for i in range(len(run) - 1):
            bigram = run[i : i + 2]
            if bigram not in STOPWORDS_CJK_BIGRAM:
                add(bigram)


def segmentation_mode() -> str:
    """返回当前分词模式（用于健康检查 / 设置页展示）。"""
    return "jieba" if _HAS_JIEBA else "bigram（未安装 jieba）"


# ---------------- 拼音词项 ----------------

def extract_pinyin_terms(query: str, limit: int = 12) -> list[str]:
    """挑出查询中「看起来是拼音」的词项，用于匹配拼音列。

    与 `extract_terms` 分开返回是刻意的：这两个集合在 SQL 里走不同的列。
    把英文词混进拼音词集会让 `go` 命中 `gong` 的全拼，造成一片假阳性，
    所以这里用 `is_pinyin_full` / `is_pinyin_initials` 做音节级校验。

    pypinyin 未安装时恒返回空列表，检索退回原有行为。
    """
    query = (query or "").strip()
    if not query:
        return []

    try:
        from app.rag.pinyin import is_pinyin_full, is_pinyin_initials
    except ImportError:  # pragma: no cover
        return []

    # 按空白与中英文边界切开，逐段判断
    candidates = re.findall(r"[A-Za-z]{2,}", query)
    out: list[str] = []
    seen: set[str] = set()
    for cand in candidates:
        low = cand.lower()
        if low in seen:
            continue
        if is_pinyin_full(low) or is_pinyin_initials(low):
            seen.add(low)
            out.append(low)
    return out[:limit]
