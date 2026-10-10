"""分块器测试。"""
from __future__ import annotations

from app.rag.chunker import chunk_document, estimate_tokens


def test_chunk_by_heading() -> None:
    text = "# 标题一\n\n段落A\n\n段落B\n\n# 标题二\n\n段落C"
    chunks = chunk_document(text, chunk_size=50)
    assert len(chunks) >= 2
    headings = {c.heading for c in chunks}
    assert "标题一" in headings
    assert "标题二" in headings


def test_chunk_long_paragraph_is_split() -> None:
    text = "x" * 1000
    chunks = chunk_document(text, chunk_size=300, overlap=50)
    assert len(chunks) > 1
    assert all(len(c.content) <= 300 for c in chunks)


def test_chunk_keeps_page_numbers() -> None:
    pages = ["第一页内容", "第二页内容", "第三页内容"]
    chunks = chunk_document("", pages=pages, chunk_size=100)
    assert {c.page_no for c in chunks} == {1, 2, 3}


def test_chunk_index_is_sequential() -> None:
    text = "\n\n".join(f"段落{i}" for i in range(20))
    chunks = chunk_document(text, chunk_size=40)
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_estimate_tokens_positive() -> None:
    assert estimate_tokens("你好世界") >= 4
    assert estimate_tokens("hello world") >= 1
