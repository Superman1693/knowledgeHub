"""提示词模板：回答模式、RAG 上下文构建、来源标注规则。"""
from __future__ import annotations

from app.schemas.search import SearchHit

# 三种输出模式（需求 17）
MODE_INSTRUCTIONS: dict[str, str] = {
    "detail": "给出**详细解释**：包含完整原理、背景、示例和注意事项。",
    "brief": "给出**极简要点**：只保留核心结论、关键词和记忆要点。",
    "example": "用**通俗举例**：使用容易理解的语言和具体示例解释概念。",
}

SYSTEM_PROMPT = """你是 KnowledgeHub 的本地知识库助手，服务于单一使用者的私有知识库。

严格遵守以下规则：
1. 你只能依据下方【知识库资料】回答；不得编造知识库中不存在的内容。
2. 每条来自知识库的信息必须标注来源编号，例如 [1]、[2]，编号对应资料片段。
3. 如果资料不足以回答，必须明确说明"知识库中缺少相关信息"，并指出缺少什么，而不是猜测。
4. 区分【事实】（资料中明确记录的）与【推断】（你的分析），推断必须显式标注。
5. 如果不同资料存在矛盾，需同时指出冲突来源。
6. 输出使用 Markdown，代码使用带语言标注的代码块。
7. 若提供了【专属术语词典】，解释相关术语时**优先采用词典中的定义**；
   词典与知识库资料冲突时以词典为准，并说明该术语来自用户自定义词典；
   词典中没有的术语，不得臆造其含义，应说明无法从现有资料确认。

回答模式：{mode}
"""


def build_context(hits: list[SearchHit]) -> str:
    """把检索片段拼接为带编号的上下文。"""
    if not hits:
        return "（无相关资料）"
    blocks: list[str] = []
    for i, hit in enumerate(hits, start=1):
        loc = []
        if hit.heading:
            loc.append(f"章节：{hit.heading}")
        if hit.page_no is not None:
            loc.append(f"页码：{hit.page_no}")
        loc_text = f"（{'；'.join(loc)}）" if loc else ""
        blocks.append(
            f"[{i}] 文档《{hit.document_title}》{loc_text}\n{hit.snippet}"
        )
    return "\n\n".join(blocks)


def build_messages(
    question: str,
    hits: list[SearchHit],
    mode: str,
    history: list[dict] | None = None,
    use_web: bool = False,
    glossary: str = "",
) -> list[dict]:
    """构建发给模型的完整消息列表。

    glossary 为命中的专属术语词典内容（可空），会作为高优先级上下文注入。
    """
    system = SYSTEM_PROMPT.format(
        mode=MODE_INSTRUCTIONS.get(mode, MODE_INSTRUCTIONS["detail"])
    )

    sections: list[str] = []
    if glossary:
        sections.append(f"【专属术语词典】（用户自定义，优先采用）\n{glossary}")
    sections.append(f"【知识库资料】\n{build_context(hits)}")
    sections.append(f"【问题】\n{question}")
    user_content = "\n\n".join(sections)

    if use_web:
        user_content += (
            "\n\n注意：用户启用了联网补充，但你当前没有联网结果。"
            "请仅基于知识库回答；如需联网信息，请在回答中说明该部分未获取。"
        )

    messages: list[dict] = [{"role": "system", "content": system}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_content})
    return messages


def insufficient_answer(hits: list[SearchHit]) -> str:
    """检索为空时的固定回复（不编造）。"""
    if not hits:
        return (
            "📄 **知识库中没有找到与你的问题相关的资料。**\n\n"
            "可能的原因：\n"
            "- 相关文档尚未导入，或导入后未完成索引；\n"
            "- 问题表述与文档用词差异较大，可尝试更换关键词。\n\n"
            "我不会基于知识库之外的信息编造回答。"
        )
    return ""
