"""查询分词测试。"""
from __future__ import annotations

from app.rag.tokenize import extract_terms


def test_extract_english_words() -> None:
    terms = extract_terms("reactive toRefs")
    lowered = [t.lower() for t in terms]
    assert "reactive" in lowered
    assert "torefs" in lowered


def test_extract_chinese_bigrams() -> None:
    terms = extract_terms("解构丢失响应性")
    # 应包含关键 2-gram
    assert "解构" in terms
    assert "丢失" in terms
    assert "响应" in terms


def test_natural_language_question_yields_terms() -> None:
    """自然语言问句必须能提取出可匹配的词项（回归：之前整句当子串会全部落空）。"""
    terms = extract_terms("reactive 解构为什么会丢失响应性？怎么解决？")
    assert "reactive" in [t.lower() for t in terms]
    assert "解构" in terms
    assert "丢失" in terms
    assert "响应" in terms
    # 疑问词噪声应被过滤
    assert "什么" not in terms
    assert "怎么" not in terms


def test_short_query_keeps_whole_string() -> None:
    terms = extract_terms("响应式")
    assert "响应式" in terms


def test_empty_query() -> None:
    assert extract_terms("") == []
    assert extract_terms("   ") == []
