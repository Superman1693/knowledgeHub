"""文本分块：把解析后的正文切分为语义合理的知识片段。

策略：
1. 优先按 Markdown 标题切分「章节」；
2. 章节内按空行切分「段落」；
3. 把段落累积到目标长度（chunk_size），超出则单独成块并做重叠切分；
4. PDF 等分页文档按页保留 page_no。
"""
from __future__ import annotations

from dataclasses import dataclass

from app.core.config import settings


@dataclass
class ChunkData:
    index: int
    heading: str | None
    content: str
    page_no: int | None
    token_count: int


def estimate_tokens(text: str) -> int:
    """粗略 token 估算：中文按字计，英文按 4 字符计。"""
    chinese = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = len(text) - chinese
    return chinese + max(1, other // 4)


def _split_long(text: str, size: int, overlap: int) -> list[str]:
    """对超长段落做带重叠的滑窗切分。"""
    if len(text) <= size:
        return [text]
    parts: list[str] = []
    start = 0
    step = max(1, size - overlap)
    while start < len(text):
        parts.append(text[start : start + size])
        start += step
    return parts


def _iter_sections(text: str):
    """按 Markdown 标题切分，产出 (heading, body_lines)。"""
    current_heading: str | None = None
    buffer: list[str] = []

    def flush():
        if buffer or current_heading is not None:
            yield current_heading, "\n".join(buffer).strip()

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            yield from flush()
            current_heading = stripped.lstrip("#").strip()
            buffer = []
        else:
            buffer.append(line)
    yield from flush()


def chunk_document(
    text: str,
    pages: list[str] | None = None,
    chunk_size: int | None = None,
    overlap: int | None = None,
) -> list[ChunkData]:
    """把正文切分为片段列表。"""
    size = chunk_size or settings.chunk_size
    ov = overlap if overlap is not None else settings.chunk_overlap

    chunks: list[ChunkData] = []
    idx = 0

    # 分页文档：按页切分以保留页码
    if pages:
        for page_no, page_text in enumerate(pages, start=1):
            if not page_text.strip():
                continue
            for heading, body in _iter_sections(page_text):
                if not body:
                    continue
                for piece in _split_long(body, size, ov):
                    chunks.append(
                        ChunkData(
                            index=idx,
                            heading=heading,
                            content=piece,
                            page_no=page_no,
                            token_count=estimate_tokens(piece),
                        )
                    )
                    idx += 1
        return chunks

    # 普通文档：按标题 → 段落累积
    for heading, body in _iter_sections(text):
        if not body:
            continue
        paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
        buf = ""
        for para in paragraphs:
            if len(para) > size:
                if buf:
                    chunks.append(ChunkData(idx, heading, buf, None, estimate_tokens(buf)))
                    idx += 1
                    buf = ""
                for piece in _split_long(para, size, ov):
                    chunks.append(
                        ChunkData(idx, heading, piece, None, estimate_tokens(piece))
                    )
                    idx += 1
                continue
            if len(buf) + len(para) + 1 <= size:
                buf = f"{buf}\n{para}".strip()
            else:
                if buf:
                    chunks.append(ChunkData(idx, heading, buf, None, estimate_tokens(buf)))
                    idx += 1
                buf = para
        if buf:
            chunks.append(ChunkData(idx, heading, buf, None, estimate_tokens(buf)))
            idx += 1

    return chunks
