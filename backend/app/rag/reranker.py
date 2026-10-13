"""搜索重排序：用对话模型对检索候选按相关性重排。

对应 LocalMind 风险二：「混合搜索需要通过实际问题集测试效果，再决定是否增加重排序模型。」

实现思路：hybrid_search 取回 top-k 候选后，把「查询 + 候选片段摘要」交给对话模型，
让它输出每个候选的相关性分数（0~10），再按新分数重排。
- 默认关闭（`RERANK_ENABLED=false`），开启后增加一次对话模型调用，延迟与额度都会增加。
- 模型返回格式错误或超时则**静默回退到原始排序**，不让重排失败影响检索可用性。
"""
from __future__ import annotations

import re

from app.core.logging import get_logger

logger = get_logger(__name__)

RERANK_PROMPT = """你是搜索相关性评估助手。用户会给出一组「查询 + 候选片段」。
请对每个候选片段与查询的相关性打分（0=完全无关，10=直接回答了查询）。

只输出 JSON 数组，格式：[{"index": 0, "score": 8}, {"index": 1, "score": 2}]
不要输出任何解释、代码块标记或其他内容。"""


async def rerank(
    query: str,
    candidates: list[dict],
    provider,
    top_k: int,
) -> list[dict]:
    """对候选片段重排。失败时返回原始顺序。

    candidates 每项至少有 `snippet`（或 `parent_content`）与 `document_title`。
    返回重排后的前 top_k 项。
    """
    if not candidates:
        return candidates[:top_k]

    # 构建评估输入（截断片段避免超上下文）
    lines: list[str] = []
    for i, c in enumerate(candidates):
        snippet = (c.get("snippet") or c.get("parent_content") or "")[:200]
        title = c.get("document_title") or ""
        lines.append(f"[{i}] 《{title}》 {snippet}")

    user_msg = f"查询：{query}\n\n候选片段：\n" + "\n".join(lines)
    messages = [
        {"role": "system", "content": RERANK_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    try:
        raw = str(await provider.chat(messages, stream=False)).strip()
        scores = _parse_scores(raw, len(candidates))
        if not scores:
            logger.info("重排序未返回可解析分数，保持原始排序")
            return candidates[:top_k]

        # 按分数降序重排，稳定排序保持同分时的原始顺序
        indexed = list(enumerate(candidates))
        indexed.sort(key=lambda pair: -scores.get(pair[0], 0))
        ranked = [item for _, item in indexed]
        logger.info("重排序完成：%d 个候选", len(ranked))
        return ranked[:top_k]
    except Exception as exc:  # noqa: BLE001
        logger.warning("重排序失败，回退原始排序：%s", exc)
        return candidates[:top_k]


def _parse_scores(raw: str, count: int) -> dict[int, int]:
    """从模型输出解析分数表；格式错误返回空 dict。"""
    import json

    # 剥掉可能的代码块标记
    text = re.sub(r"```(?:json)?\s*", "", raw).replace("```", "").strip()
    try:
        arr = json.loads(text)
    except json.JSONDecodeError:
        return {}
    if not isinstance(arr, list):
        return {}

    result: dict[int, int] = {}
    for item in arr:
        if not isinstance(item, dict):
            continue
        idx = item.get("index")
        score = item.get("score")
        if isinstance(idx, int) and 0 <= idx < count and isinstance(score, (int, float)):
            result[idx] = max(0, min(10, int(score)))
    return result
