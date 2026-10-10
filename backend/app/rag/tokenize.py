"""轻量查询分词：为关键词检索提供可匹配的词项。

本机 PostgreSQL 无中文分词器，因此这里用「中文 2-gram + 英文整词」的方式
从查询中提取词项，配合 pg_trgm 的 ILIKE 做多词命中计数。

设计目标：让自然语言问句也能命中片段（例如
「reactive 解构为什么会丢失响应性？怎么解决？」→ 解构 / 丢失 / 响应 / reactive ...）。
"""
from __future__ import annotations

import re

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

# 中文停用 2-gram（疑问词 / 连接词等噪声）
STOPWORDS_CJK_BIGRAM = {
    "什么", "怎么", "为什", "么会", "么样", "哪些", "哪个", "如何", "是否",
    "可以", "需要", "以及", "但是", "因为", "所以", "如果", "这个", "那个",
    "一个", "我们", "你们", "他们", "就是", "已经", "或者", "而且", "然后",
    "由于", "为了", "通过", "进行", "使用", "时候", "请问", "一下", "能否",
    "的区", "区别", "是什", "么意", "什么",
}

# 查询很短时（<=该长度）额外把整串作为一个词项，保证精确子串仍能命中
SHORT_QUERY_LEN = 8


def extract_terms(query: str, limit: int = 24) -> list[str]:
    """从查询中提取词项列表（去重、保序）。"""
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

    # 1) 英文整词
    for word in _WORD_RE.findall(query):
        if word.lower() not in STOPWORDS_EN:
            add(word)

    # 2) 中文 2-gram
    for run in _CJK_RUN_RE.findall(query):
        if len(run) < 2:
            continue
        for i in range(len(run) - 1):
            bigram = run[i : i + 2]
            if bigram not in STOPWORDS_CJK_BIGRAM:
                add(bigram)

    # 3) 短查询额外加入整串（如「响应式」这类单个关键词）
    if len(query) <= SHORT_QUERY_LEN:
        add(query)

    return terms[:limit]
