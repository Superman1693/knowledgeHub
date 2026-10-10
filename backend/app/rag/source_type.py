"""来源类型判定：把一次回答的来源归纳为统一标签。

对应需求 14（三类信息来源与事实性约束）：
- 📄【知识库原文】：回答直接引用检索到的知识库原文；
- 📑【知识库归纳推理】：基于多份资料综合分析；
- 🌐【联网补充信息】：仅当实际抓取到外部资料时才标注。

判定只依据**真实存在的来源**：没有联网结果就绝不会返回联网标签，
与提示词中的约束一致（需求 14.5）。
"""
from __future__ import annotations

SOURCE_ORIGINAL = "知识库原文"
SOURCE_INFERRED = "知识库归纳推理"
SOURCE_WEB = "联网补充信息"
SOURCE_MIXED = "知识库原文 + 联网补充信息"
SOURCE_GLOSSARY = "专属术语词典"

# 前端徽章用的展示元数据（图标 + 说明）
SOURCE_META: dict[str, dict[str, str]] = {
    SOURCE_ORIGINAL: {"icon": "📄", "desc": "直接引用知识库原文"},
    SOURCE_INFERRED: {"icon": "📑", "desc": "基于多份资料的归纳推理"},
    SOURCE_WEB: {"icon": "🌐", "desc": "来自联网检索的外部信息"},
    SOURCE_MIXED: {"icon": "📄🌐", "desc": "知识库原文与联网信息结合"},
    SOURCE_GLOSSARY: {"icon": "📖", "desc": "来自你的专属术语词典"},
}


def classify(
    hits: list | None = None,
    web_results: list | None = None,
    glossary_terms: list | None = None,
) -> str | None:
    """判定回答来源类型；无任何来源时返回 None。

    - 知识库 + 联网 → 混合
    - 仅联网        → 联网补充信息
    - 仅知识库      → 单条为「原文」，多条为「归纳推理」
    - 仅术语词典    → 专属术语词典
    """
    has_kb = bool(hits)
    has_web = bool(web_results)

    if has_kb and has_web:
        return SOURCE_MIXED
    if has_web:
        return SOURCE_WEB
    if has_kb:
        return SOURCE_ORIGINAL if len(hits or []) == 1 else SOURCE_INFERRED
    if glossary_terms:
        return SOURCE_GLOSSARY
    return None
