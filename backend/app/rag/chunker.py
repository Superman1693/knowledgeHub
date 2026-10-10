"""文本分块：把解析后的正文切分为语义合理的知识片段。

策略：
1. 优先按 Markdown 标题切分「章节」——只识别**合法标题**（`#` + 空格，1~6 级），
   并跳过代码围栏内的行，避免把代码/示例里的 `# 注释`、`#include`、`#!/bin/sh`
   误判为标题，从而把正文拦腰切断；
2. 章节内按空行切分「段落」；
3. 把段落累积到目标长度（chunk_size）；
4. 超长内容按**句子边界**切分（而非按字符硬切），避免一句话被切成两半；
5. PDF 等分页文档按页保留 page_no。
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

from app.ai.factory import get_embedding_provider, get_provider
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Markdown 标题：1~6 个 `#` 后必须跟空白。
# `#include <stdio.h>`、`#!/bin/bash`、`#TODO` 这类都不算标题。
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*$")
# 代码围栏起始（``` 或 ~~~）
_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
# 标题长度上限。语雀 / Notion 等导出工具会把整段正文设成标题样式，
# 于是出现「##### 文本配置文件，包含一系列指令，用于自动化构建…」这种 40+ 字的"标题"。
# 真正的章节标题都很短，超过上限的一律当正文，避免产生荒谬的章节边界。
MAX_HEADING_LEN = 40
# 句子切分：**保留**句末标点与换行符（必须原样还原，否则正文会被压成一行）
_SENTENCE_RE = re.compile(r"[^。！？；!?;\n]*(?:[。！？；!?;]+|\n+|$)")


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


def _split_sentences(text: str) -> list[str]:
    """按句子边界切分；句末标点与换行**原样保留**在句尾。"""
    return [s for s in _SENTENCE_RE.findall(text) if s and s.strip()]


def _split_long(text: str, size: int, overlap: int) -> list[str]:
    """超长文本切分：优先在句子边界断开，避免把一句话切成两半。

    只有**单句本身**就超过 size 时，才退化为按字符硬切（并保留重叠）。
    """
    if len(text) <= size:
        return [text]

    parts: list[str] = []
    buf = ""
    for sentence in _split_sentences(text):
        # 单句超长：先落盘已积累内容，再对该句做带重叠的滑窗切分
        if len(sentence) > size:
            if buf:
                parts.append(buf)
                buf = ""
            step = max(1, size - overlap)
            for i in range(0, len(sentence), step):
                parts.append(sentence[i : i + size])
                if i + size >= len(sentence):
                    break
            continue

        if len(buf) + len(sentence) <= size:
            buf += sentence
            continue

        # 放不下：落盘当前块，新块带上尾部 overlap 以保持语义连续
        parts.append(buf)
        buf = (buf[-overlap:] if overlap > 0 else "") + sentence

    if buf:
        parts.append(buf)
    return parts


def _iter_sections(text: str):
    """按 Markdown 标题切分，产出 (heading, body)。

    代码围栏内的内容一律视为正文——这是修复「片段被莫名切断」的关键：
    很多文档会在 ```markdown 代码块里演示 Markdown 写法（如 `# 项目简介`），
    若不跳过围栏，这些示例行会被当成真标题，导致正文被从中间劈开。
    """
    current_heading: str | None = None
    buffer: list[str] = []
    in_fence = False

    def flush():
        if buffer or current_heading is not None:
            yield current_heading, "\n".join(buffer).strip()

    for line in text.splitlines():
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            buffer.append(line)
            continue

        if not in_fence:
            m = _HEADING_RE.match(line.strip())
            # 过长的"标题"多半是正文（见 MAX_HEADING_LEN 说明），不作为章节边界
            if m and len(m.group(2)) <= MAX_HEADING_LEN:
                yield from flush()
                current_heading = m.group(2).strip()
                buffer = []
                continue

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


# ---------------- AI 辅助分块 ----------------
# 段落数 / 总字数上限：超过则直接走规则分块，避免超长上下文与高额调用成本。
# 实测：21398 字 / 173 段的笔记在 120/12000 下会被跳过，而这类中等长度文档
# 恰恰最需要语义分块，因此放宽到 300 段 / 40000 字（单次调用约 1.5 万 token，可接受）。
AI_CHUNK_MAX_PARAS = 300
AI_CHUNK_MAX_CHARS = 40000

CHUNK_AI_SYSTEM_PROMPT = """你是文档分段助手。用户会给出一篇已按段落编号的文档，
请把它划分为若干语义完整的片段。

规则：
1. 每个片段围绕一个主题；不要把同一主题的内容拆开，也不要把不相关的内容强行合并。
2. 代码块、表格、列表应尽量保持完整，不要跨片段切断。
3. **严格控制片段长度**：多数片段应在 300~800 字之间；
   超过 1000 字说明合并过度，必须拆开。
4. 只输出划分方案：每行一个范围，格式为「起始段号-结束段号」。
   要求从 1 开始、连续、不重叠、且覆盖全部段落。例如：
1-3
4-7
8-10
5. 不要输出任何解释、标题或代码块标记。"""


def _split_paragraphs(text: str) -> list[str]:
    """按空行切分段落，**保护代码围栏**（围栏内的空行不切分）。"""
    paras: list[str] = []
    buf: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if _FENCE_RE.match(line):
            in_fence = not in_fence
        if not in_fence and not line.strip():
            if buf:
                paras.append("\n".join(buf).strip())
                buf = []
            continue
        buf.append(line)
    if buf:
        paras.append("\n".join(buf).strip())
    return [p for p in paras if p]


def _extract_heading(content: str) -> str | None:
    """从片段内容中取第一个合法标题作为 heading。"""
    for line in content.splitlines():
        m = _HEADING_RE.match(line.strip())
        if m and len(m.group(2)) <= MAX_HEADING_LEN:
            return m.group(2).strip()
    return None


def _parse_ai_ranges(raw: str, total: int) -> list[tuple[int, int]]:
    """解析模型输出的「起-止」范围，做合法性校验与合并。"""
    ranges: list[tuple[int, int]] = []
    for m in re.finditer(r"(\d+)\s*[-~—至到]\s*(\d+)", raw or ""):
        a, b = int(m.group(1)), int(m.group(2))
        if 1 <= a <= b <= total:
            ranges.append((a, b))
    # 兼容「一行一个段号」的输出
    if not ranges:
        for m in re.finditer(r"^\s*(\d+)\s*$", raw or "", flags=re.M):
            i = int(m.group(1))
            if 1 <= i <= total:
                ranges.append((i, i))

    ranges.sort()
    merged: list[tuple[int, int]] = []
    for a, b in ranges:
        # 只合并**重叠**区间。相邻但不重叠的（如 1-4、5-12）必须保持独立，
        # 否则会把模型划分好的所有片段重新粘成一块（写成 prev_end + 1 就会犯这个错）。
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


async def chunk_document_ai(
    text: str,
    pages: list[str] | None = None,
    chunk_size: int | None = None,
    overlap: int | None = None,
) -> list[ChunkData]:
    """AI 辅助分块：由对话模型判断语义边界。

    任何异常、输出不可用、文档过长时**自动回退到规则分块**，
    保证索引流程不会因模型故障而中断（符合「模型不可用时非 AI 功能仍可用」）。
    """
    if pages:  # 分页文档（PDF）保留页码，交给规则分块
        return chunk_document(text, pages, chunk_size, overlap)

    paras = _split_paragraphs(text)
    if (
        len(paras) < 2
        or len(paras) > AI_CHUNK_MAX_PARAS
        or len(text) > AI_CHUNK_MAX_CHARS
    ):
        logger.info(
            "AI 分块跳过（段落 %s / 字数 %s 超出范围），改用规则分块", len(paras), len(text)
        )
        return chunk_document(text, pages, chunk_size, overlap)

    numbered = "\n".join(f"[{i}] {p}" for i, p in enumerate(paras, start=1))
    messages = [
        {"role": "system", "content": CHUNK_AI_SYSTEM_PROMPT},
        {"role": "user", "content": f"共 {len(paras)} 个段落：\n\n{numbered}"},
    ]

    try:
        provider = get_provider()
        raw = await provider.chat(messages, stream=False)
        ranges = _parse_ai_ranges(str(raw), len(paras))
        if not ranges:
            raise ValueError("模型未给出可解析的分段方案")
    except Exception as exc:  # noqa: BLE001
        logger.warning("AI 分块失败，回退规则分块：%s", exc)
        return chunk_document(text, pages, chunk_size, overlap)

    chunks: list[ChunkData] = []
    for a, b in ranges:
        content = "\n\n".join(paras[a - 1 : b]).strip()
        if not content:
            continue
        chunks.append(
            ChunkData(
                index=len(chunks),
                heading=_extract_heading(content),
                content=content,
                page_no=None,
                token_count=estimate_tokens(content),
            )
        )

    if not chunks:
        return chunk_document(text, pages, chunk_size, overlap)

    # 兜底：模型输出并不稳定（同一文档两次调用可能给出 6~13 个片段），
    # 超过硬上限的片段再用规则方式切一次，保证检索粒度不会过粗。
    size = chunk_size or settings.chunk_size
    ov = overlap if overlap is not None else settings.chunk_overlap
    hard_limit = int(size * 1.5)
    final: list[ChunkData] = []
    for c in chunks:
        if len(c.content) > hard_limit:
            for piece in _split_long(c.content, size, ov):
                final.append(
                    ChunkData(
                        index=len(final),
                        heading=c.heading,
                        content=piece,
                        page_no=None,
                        token_count=estimate_tokens(piece),
                    )
                )
        else:
            final.append(
                ChunkData(len(final), c.heading, c.content, None, c.token_count)
            )

    logger.info("AI 分块完成：%s 段落 → %s 片段", len(paras), len(final))
    return final


# ---------------- 语义分块 ----------------
# 句子数上限：超过则走规则分块（避免上千次嵌入调用拖慢索引）。
# 实测 688 句的笔记在 600 上限下会被静默跳过，故放宽到 1000（约 15 秒，成本可接受）。
SEMANTIC_MAX_SENTENCES = 1000
# 断点阈值分位：相邻句距离超过该分位处断开（百分位法比固定阈值更稳）
SEMANTIC_BREAKPOINT_PERCENTILE = 0.9
# 片段最小字数：小于此值的组与相邻组合并，避免碎片
SEMANTIC_MIN_CHUNK = 200


def _cosine(a: list[float], b: list[float]) -> float:
    """余弦相似度（手写实现，不为一个函数引入 numpy 依赖）。"""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


async def chunk_document_semantic(
    text: str,
    pages: list[str] | None = None,
    chunk_size: int | None = None,
    overlap: int | None = None,
) -> list[ChunkData]:
    """语义分块：用嵌入模型算相邻句子的相似度，在话题转换处切分。

    相比 LLM 分块，这里只消耗**嵌入**调用（单价通常低 1~2 个数量级），
    是「结构混乱文档」在成本与效果之间的折中方案：
    句向量化 → 算相邻余弦距离 → 距离骤降处断开 → 按目标长度兜底切分。
    """
    if pages:  # 分页文档（PDF）保留页码，交给规则分块
        return chunk_document(text, pages, chunk_size, overlap)

    size = chunk_size or settings.chunk_size
    ov = overlap if overlap is not None else settings.chunk_overlap

    sentences = [s for s in _split_sentences(text) if s.strip()]
    if len(sentences) < 3 or len(sentences) > SEMANTIC_MAX_SENTENCES:
        logger.info("语义分块跳过（句子数 %s 超出范围），改用规则分块", len(sentences))
        return chunk_document(text, pages, chunk_size, overlap)

    try:
        provider = get_embedding_provider()
        vectors = await provider.embed(sentences)
        if len(vectors) != len(sentences):
            raise ValueError(f"嵌入返回数量不匹配：{len(vectors)} != {len(sentences)}")
    except Exception as exc:  # noqa: BLE001
        logger.warning("语义分块失败，回退规则分块：%s", exc)
        return chunk_document(text, pages, chunk_size, overlap)

    distances = [
        1.0 - _cosine(vectors[i], vectors[i + 1]) for i in range(len(vectors) - 1)
    ]
    if not distances:
        return chunk_document(text, pages, chunk_size, overlap)

    ordered = sorted(distances)
    threshold = ordered[
        min(len(ordered) - 1, int(len(ordered) * SEMANTIC_BREAKPOINT_PERCENTILE))
    ]
    # 断点 i 表示「第 i 句另起一块」
    breakpoints = {i + 1 for i, d in enumerate(distances) if d > threshold}

    groups: list[list[str]] = []
    cur: list[str] = []
    for i, sent in enumerate(sentences):
        if cur and i in breakpoints:
            groups.append(cur)
            cur = []
        cur.append(sent)
    if cur:
        groups.append(cur)

    # 过短的组向前合并，避免产生碎片
    merged: list[str] = []
    for group in groups:
        content = "".join(group).strip()
        if not content:
            continue
        if merged and len(merged[-1]) < SEMANTIC_MIN_CHUNK:
            merged[-1] = f"{merged[-1]}\n{content}"
        else:
            merged.append(content)

    chunks: list[ChunkData] = []
    for content in merged:
        for piece in _split_long(content, size, ov):
            chunks.append(
                ChunkData(
                    index=len(chunks),
                    heading=_extract_heading(piece),
                    content=piece,
                    page_no=None,
                    token_count=estimate_tokens(piece),
                )
            )

    if not chunks:
        return chunk_document(text, pages, chunk_size, overlap)
    logger.info("语义分块完成：%s 句 → %s 片段", len(sentences), len(chunks))
    return chunks
