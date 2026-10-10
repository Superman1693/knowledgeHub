"""检索融合逻辑测试（纯逻辑，不依赖数据库）。"""
from __future__ import annotations

import uuid

from app.rag.retriever import _normalize, _Row


def _row(score: float) -> _Row:
    return _Row(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        title="t",
        heading=None,
        page_no=None,
        content="c",
        score=score,
    )


def test_normalize_empty() -> None:
    assert _normalize([]) == {}


def test_normalize_range() -> None:
    rows = [_row(0.1), _row(0.5), _row(0.9)]
    norm = _normalize(rows)
    assert min(norm.values()) == 0.0
    assert max(norm.values()) == 1.0


def test_normalize_identical_scores() -> None:
    rows = [_row(0.5), _row(0.5)]
    norm = _normalize(rows)
    assert all(v == 1.0 for v in norm.values())
