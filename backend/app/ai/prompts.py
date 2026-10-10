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
1. 你只能依据下方【知识库资料】与（若提供）【联网补充信息】回答；
   不得编造知识库中不存在的内容。
2. 必须区分并标注三类来源：
   - 📄【知识库原文】：直接来自【知识库资料】的原文，标注编号如 [1]、[2]；
   - 📑【知识库归纳推理】：基于一份或多份资料综合分析得出的结论；
   - 🌐【联网补充信息】：仅当下方确实提供了【联网补充信息】时使用，
     必须附上其中给出的真实链接，不得自行编造链接。
3. 如果下方没有提供【联网补充信息】，不得声称已联网查询。
4. 如果资料不足以回答，必须明确说明"知识库中缺少相关信息"，并指出缺少什么，而不是猜测。
5. 区分【事实】（资料中明确记录的）与【推断】（你的分析），推断必须显式标注。
6. 如果不同资料存在矛盾，需同时指出冲突来源。
7. 输出使用 Markdown，代码使用带语言标注的代码块。
8. 若提供了【专属术语词典】，解释相关术语时**优先采用词典中的定义**；
   词典与知识库资料冲突时以词典为准，并说明该术语来自用户自定义词典；
   词典中没有的术语，不得臆造其含义，应说明无法从现有资料确认。

回答模式：{mode}

思考过程要求：如需先推理，请**使用中文**并保持**简洁**——只写关键判断步骤，
不要复述问题、不要罗列检查清单、不要输出与最终答案无关的推演过程。
"""


def build_context(hits: list[SearchHit]) -> str:
    """把检索片段拼接为带编号的上下文。

    父子检索开启时，片段会带 parent_content（所属父块的完整内容）——
    检索靠子块精准匹配，但喂给模型的是上下文完整的父块，两者兼得。
    """
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
        body = hit.parent_content or hit.snippet
        blocks.append(f"[{i}] 文档《{hit.document_title}》{loc_text}\n{body}")
    return "\n\n".join(blocks)


def build_web_context(results: list[dict]) -> str:
    """把联网结果拼接为带编号与真实链接的上下文。"""
    if not results:
        return "（未获取到联网结果）"
    blocks: list[str] = []
    for i, r in enumerate(results, start=1):
        blocks.append(
            f"[W{i}] {r.get('title', '')}\n{r.get('snippet', '')}\n链接：{r.get('url', '')}"
        )
    return "\n\n".join(blocks)


def build_messages(
    question: str,
    hits: list[SearchHit],
    mode: str,
    history: list[dict] | None = None,
    use_web: bool = False,
    glossary: str = "",
    web_results: list[dict] | None = None,
    web_note: str = "",
) -> list[dict]:
    """构建发给模型的完整消息列表。

    glossary    为命中的专属术语词典内容（可空），会作为高优先级上下文注入；
    web_results 为**实际抓取到**的联网结果（可空）。仅当其非空时才允许模型标注 🌐；
    用户启用了联网但未取得结果时，明确告知模型「未获取」，避免其伪称已联网。
    """
    system = SYSTEM_PROMPT.format(
        mode=MODE_INSTRUCTIONS.get(mode, MODE_INSTRUCTIONS["detail"])
    )

    sections: list[str] = []
    if glossary:
        sections.append(f"【专属术语词典】（用户自定义，优先采用）\n{glossary}")
    sections.append(f"【知识库资料】\n{build_context(hits)}")
    if web_results:
        sections.append(
            f"【联网补充信息】（真实抓取，引用时附链接）\n{build_web_context(web_results)}"
        )
    elif use_web:
        reason = f"：{web_note}" if web_note else ""
        sections.append(
            f"【联网补充信息】\n（本次未获取到联网结果{reason}，"
            "请勿声称已联网，也不要编造链接）"
        )
    sections.append(f"【问题】\n{question}")

    messages: list[dict] = [{"role": "system", "content": system}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": "\n\n".join(sections)})
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
