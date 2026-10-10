"""分块器测试。"""
from __future__ import annotations

import asyncio

from app.rag import chunker
from app.rag.chunker import (
    MAX_HEADING_LEN,
    _parse_ai_ranges,
    _split_paragraphs,
    chunk_document,
    chunk_document_ai,
    estimate_tokens,
)


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


# ---------------- 标题识别 ----------------

def test_heading_inside_code_fence_is_not_heading() -> None:
    """围栏内的 `# 注释` 不应被当成标题（否则正文会被拦腰切断）。"""
    text = "```bash\n# 启动Docker\nsystemctl start docker\n```\n\n正文内容"
    chunks = chunk_document(text, chunk_size=200)
    assert all(c.heading is None for c in chunks)


def test_overlong_heading_treated_as_body() -> None:
    """超过 MAX_HEADING_LEN 的「标题」视为正文（语雀等导出工具的常见现象）。"""
    long_title = "文" * (MAX_HEADING_LEN + 5)
    text = f"# 正常标题\n\n正文A\n\n# {long_title}\n\n正文B"
    headings = {c.heading for c in chunk_document(text, chunk_size=200)}
    assert "正常标题" in headings
    assert long_title not in headings


def test_split_paragraphs_protects_code_fence() -> None:
    """代码围栏内的空行不应切分段落。"""
    text = "前文\n\n```bash\necho a\n\necho b\n```\n\n后文"
    paras = _split_paragraphs(text)
    assert len(paras) == 3
    assert "echo a" in paras[1] and "echo b" in paras[1]


# ---------------- AI 分块 ----------------

def test_parse_ai_ranges_keeps_adjacent_separate() -> None:
    """回归测试：相邻但**不重叠**的区间不能合并。

    曾把判断写成 `a <= prev_end + 1`，结果模型给出的 9 个范围被粘成 1 段（6001 字）。
    """
    assert _parse_ai_ranges("1-4\n5-12\n13-19", 19) == [(1, 4), (5, 12), (13, 19)]


def test_parse_ai_ranges_merges_overlapping() -> None:
    assert _parse_ai_ranges("1-5\n3-8", 10) == [(1, 8)]


def test_parse_ai_ranges_ignores_out_of_range() -> None:
    assert _parse_ai_ranges("1-3\n9-99", 10) == [(1, 3)]


def test_parse_ai_ranges_accepts_plain_numbers() -> None:
    """兼容「一行一个段号」的输出形式：每个段号各自独立成块，不合并。"""
    assert _parse_ai_ranges("1\n2\n3", 5) == [(1, 1), (2, 2), (3, 3)]


def test_ai_chunk_falls_back_when_model_unavailable(monkeypatch) -> None:
    """模型不可用时必须回退规则分块，而不是让索引流程失败。"""

    class _BrokenProvider:
        async def chat(self, *_args, **_kwargs):
            raise RuntimeError("model down")

    monkeypatch.setattr(chunker, "get_provider", lambda: _BrokenProvider())
    text = "\n\n".join(f"段落{i}" for i in range(5))
    got = asyncio.run(chunk_document_ai(text, chunk_size=100))
    expected = chunk_document(text, chunk_size=100)
    assert [c.content for c in got] == [c.content for c in expected]
