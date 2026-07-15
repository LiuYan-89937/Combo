from __future__ import annotations

from agent_factory.knowledge_system.schema import KnowledgePromptGuidanceConfig, KnowledgeSourceManifest


KNOWLEDGE_GUIDANCE_CONTEXT_KEY = "knowledge_prompt_guidance"
KNOWLEDGE_TOOL_ID = "knowledge"

KNOWLEDGE_USAGE_RULES = """知识库使用规则：
- 当问题涉及内部资料、项目事实、产品参数、业务规则、操作流程或需要精确引用时，必须先查询知识库。
- 用户明确提到“文档、知识库、资料、规范、项目内容”时，必须查询。
- 当前对话已经提供完整答案时，不要重复查询。
- 闲聊、创作、通用常识问题无需查询。
- 不确定某项事实是否存在于知识库时，优先查询，不要凭印象回答。
- 查询无结果时明确说明，不得伪造知识库内容。
- 未经实际检索，不得声称“根据知识库”。"""


def knowledge_prompt_guidance(
    sources: list[KnowledgeSourceManifest],
    *,
    config: KnowledgePromptGuidanceConfig,
) -> str:
    if not config.enabled:
        return ""
    visible_sources = sources[: config.max_sources]
    lines = ["当前 Agent 已挂载以下知识源："]
    if visible_sources:
        lines.extend(_source_line(source, max_description_chars=config.max_description_chars) for source in visible_sources)
    else:
        lines.append("- 当前没有可用知识源。")
    if len(sources) > len(visible_sources):
        lines.append(
            f"- 另有 {len(sources) - len(visible_sources)} 个知识源，"
            f"可调用 {KNOWLEDGE_TOOL_ID} 工具并设置 action=list_sources 查看。"
        )
    lines.extend(
        [
            "",
            KNOWLEDGE_USAGE_RULES,
            "",
            "推荐调用流程：",
            f"1. 默认调用 {KNOWLEDGE_TOOL_ID} 工具并设置 "
            f"action=search、mode={config.default_search_mode}、top_k={config.default_top_k}。",
            f"2. 对相关命中继续调用 {KNOWLEDGE_TOOL_ID} 工具，设置 action=open 或 action=read 获取完整内容。",
            "3. 根据检索结果回答并标明来源；没有结果时如实说明。",
            "4. 用户询问有哪些资料，或无法判断应查询哪个知识源时，设置 action=list_sources。",
        ]
    )
    return "\n".join(lines)


def _source_line(source: KnowledgeSourceManifest, *, max_description_chars: int) -> str:
    description = _source_description(source)
    if len(description) > max_description_chars:
        description = f"{description[: max_description_chars - 1].rstrip()}…"
    return (
        f"- {source.display_name}"
        f"（状态：{source.status}；类型：{source.source_type}；描述：{description}）"
    )


def _source_description(source: KnowledgeSourceManifest) -> str:
    for key in ("description", "summary", "title"):
        text = " ".join(str(source.metadata.get(key) or "").split())
        if text and text != source.display_name:
            return text
    return "未提供"
