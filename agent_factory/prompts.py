from __future__ import annotations

from enum import Enum
import json
from typing import Literal

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, ConfigDict, Field


class PromptId(str, Enum):
    REQUIREMENT_CAPTURE_INTENT = "factory.requirement_capture.intent"
    REQUIREMENT_CAPTURE_CLARITY = "factory.requirement_capture.clarity"
    REQUIREMENT_CAPTURE_QUESTION = "factory.requirement_capture.question"
    REQUIREMENT_CAPTURE_MERGE = "factory.requirement_capture.merge"
    BUSINESS_PLAN_REVIEW_DRAFT = "factory.business_plan_review.draft"
    BUSINESS_PLAN_REVIEW_REVISE = "factory.business_plan_review.revise"
    RUNTIME_PATTERN_SELECTION = "factory.runtime_pattern_selection"
    GRAPH_BEHAVIOR_PLANNING = "factory.graph_behavior_planning"
    FACTORY_CHAT = "factory.chat"


class CaptureIntentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: Literal["chat", "inspect_factory", "manufacture_agent", "repair_agent", "unclear"]
    confidence: float = Field(ge=0, le=1)
    reason: str
    extracted_requirement: str | None = None
    reply_hint: str | None = None
    entry_stage: str | None = None
    should_run_graph: bool


class RequirementClarityOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_clear: bool
    confidence: float = Field(ge=0, le=1)
    reason: str
    missing_fields: list[str] = Field(default_factory=list, max_length=8)


class ClarificationOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    description: str | None = None


class ClarifyingQuestionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    question: str
    options: list[ClarificationOption] = Field(min_length=2, max_length=5)
    custom_option_id: str


class ClarifyingQuestionSetOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    questions: list[ClarifyingQuestionOutput] = Field(min_length=1, max_length=5)


class RequirementMergeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_requirement: str
    assumptions: list[str] = Field(default_factory=list, max_length=8)
    unresolved_questions: list[str] = Field(default_factory=list, max_length=8)


class RuntimePatternAlternativeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pattern_id: str
    reason: str
    tradeoff: str | None = None


class RuntimePatternSelectionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_pattern_id: str
    selection_reason: str
    fit_summary: str
    alternatives: list[RuntimePatternAlternativeOutput] = Field(default_factory=list, max_length=5)
    assumptions: list[str] = Field(default_factory=list, max_length=8)
    open_questions: list[str] = Field(default_factory=list, max_length=8)


class GraphBehaviorNodePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    node_type: str
    business_behavior: str
    input_expectation: str
    output_expectation: str
    user_visible: bool = False
    notes: list[str] = Field(default_factory=list, max_length=8)


class GraphBehaviorRoutePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_node: str
    to_node: str
    condition: str
    business_meaning: str
    expected_usage: str


class GraphBehaviorInterruptPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    business_reason: str
    user_visible_reason: str


class GraphBehaviorTerminationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success_nodes: list[str] = Field(default_factory=list)
    failure_nodes: list[str] = Field(default_factory=list)
    business_success_meaning: str
    business_failure_meaning: str


class GraphBehaviorPlanOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pattern_id: str
    pattern_name: str
    graph_intent: str
    nodes: list[GraphBehaviorNodePlan] = Field(default_factory=list)
    routes: list[GraphBehaviorRoutePlan] = Field(default_factory=list)
    interrupts: list[GraphBehaviorInterruptPlan] = Field(default_factory=list)
    termination: GraphBehaviorTerminationPlan
    assumptions: list[str] = Field(default_factory=list, max_length=8)
    open_questions: list[str] = Field(default_factory=list, max_length=8)


def get_prompt(prompt_id: PromptId) -> ChatPromptTemplate:
    if prompt_id == PromptId.REQUIREMENT_CAPTURE_INTENT:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are the intent classifier for a Factory Agent shell.\n"
                    "Return JSON only. Do not answer the user.\n"
                    "The word JSON is required: your response must be a valid JSON object.\n\n"
                    "Classify the user input into exactly one intent:\n"
                    "- chat\n"
                    "- inspect_factory\n"
                    "- manufacture_agent\n"
                    "- repair_agent\n"
                    "- unclear\n\n"
                    "Output JSON schema:\n{output_json_schema}",
                ),
                ("user", "Classify this user input and return JSON only:\n{user_input}"),
            ]
        )
    if prompt_id == PromptId.REQUIREMENT_CAPTURE_CLARITY:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是 Agent 工厂第一阶段的需求清晰度判断器。\n"
                    "Return JSON only. The word JSON is required: output must be a valid JSON object.\n"
                    "只判断需求是否足够进入下一阶段，不要向用户提问。\n\n"
                    "判断时必须参考当前 Factory 运行环境，避免把需求扩展到运行环境之外的产品形态。\n\n"
                    "清晰标准至少包括：Agent 目标、使用场景、目标用户、输入、输出、约束、"
                    "可能需要的工具或外部资源。\n\n"
                    "Output JSON schema:\n{output_json_schema}",
                ),
                (
                    "user",
                    "原始输入：\n{original_input}\n\n"
                    "当前 Factory 运行环境：\n{runtime_environment}\n\n"
                    "当前整理后的需求：\n{current_requirement}\n\n"
                    "请返回 JSON。",
                ),
            ]
        )
    if prompt_id == PromptId.REQUIREMENT_CAPTURE_QUESTION:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是 Agent 工厂第一阶段的需求澄清提问器。\n"
                    "Return JSON only. The word JSON is required: output must be a valid JSON object.\n"
                    "一轮可以生成多个引导性问题，最多 5 个问题。\n"
                    "每个问题最多 5 个选项，并且必须包含一个自定义补充选项，"
                    "custom_option_id 必须指向该问题的自定义选项。\n\n"
                    "问题和选项必须参考当前 Factory 运行环境。不要默认假设未声明的外部服务、"
                    "端侧产品形态或多媒体能力已经存在；如果确实相关，应作为资源条件来澄清。\n\n"
                    "Output JSON schema:\n{output_json_schema}",
                ),
                (
                    "user",
                    "原始输入：\n{original_input}\n\n"
                    "当前 Factory 运行环境：\n{runtime_environment}\n\n"
                    "当前整理后的需求：\n{current_requirement}\n\n"
                    "缺失信息：\n{missing_fields}\n\n"
                    "请返回 JSON。",
                ),
            ]
        )
    if prompt_id == PromptId.REQUIREMENT_CAPTURE_MERGE:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是 Agent 工厂第一阶段的需求整理器。\n"
                    "Return JSON only. The word JSON is required: output must be a valid JSON object.\n"
                    "你只能看到原始输入、当前需求版本、本轮问题组和本轮用户回答组。\n"
                    "不要保留历史问答过程，只输出合并后的 current_requirement。\n\n"
                    "整理结果必须保持在当前 Factory 运行环境内；如果用户选择了需要额外资源的能力，"
                    "应把它写成资源/工具/服务条件，而不是默认视为已具备。\n\n"
                    "Output JSON schema:\n{output_json_schema}",
                ),
                (
                    "user",
                    "原始输入：\n{original_input}\n\n"
                    "当前 Factory 运行环境：\n{runtime_environment}\n\n"
                    "当前需求版本：\n{current_requirement}\n\n"
                    "本轮问题和用户回答：\n{answers}\n\n"
                    "请返回 JSON。",
                ),
            ]
        )
    if prompt_id == PromptId.BUSINESS_PLAN_REVIEW_DRAFT:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是 Agent 工厂第一阶段的业务制造计划撰写器。\n"
                    "你的任务是把第一阶段需求整理成一份条理清晰的纯文本业务制造计划。\n"
                    "不要输出 YAML，不要输出 JSON，不要输出代码块。\n\n"
                    "计划必须使用以下固定标题，并保持标题原样：\n"
                    "{required_sections}\n\n"
                    "只从业务层面描述 Agent 应该服务谁、解决什么问题、有哪些业务行为、"
                    "如何与用户互动、业务上不负责什么、怎样算有用。\n\n"
                    "禁止在本阶段写工具方案、资源方案、资源嗅探结论、技术选型、实现设计、"
                    "数据库方案、API 方案或具体工具定义。这些属于后续阶段。\n\n"
                    "【后续规划提示】只能写业务层面后续要关注的事项，不能提前规划工具或资源。",
                ),
                (
                    "user",
                    "第一阶段需求如下：\n{requirement_brief}\n\n"
                    "请输出第一阶段业务制造计划纯文本。",
                ),
            ]
        )
    if prompt_id == PromptId.BUSINESS_PLAN_REVIEW_REVISE:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是 Agent 工厂第一阶段的业务制造计划修订器。\n"
                    "根据用户本轮修改意见，重写当前业务制造计划。\n"
                    "不要输出 YAML，不要输出 JSON，不要输出代码块。\n\n"
                    "计划必须使用以下固定标题，并保持标题原样：\n"
                    "{required_sections}\n\n"
                    "只修订业务制造计划本身，不保留修订过程，不追加对话记录。\n"
                    "禁止写工具方案、资源方案、资源嗅探结论、技术选型、实现设计、"
                    "数据库方案、API 方案或具体工具定义。",
                ),
                (
                    "user",
                    "第一阶段需求：\n{requirement_brief}\n\n"
                    "当前业务制造计划：\n{current_plan_text}\n\n"
                    "用户本轮修改意见：\n{revision_instruction}\n\n"
                    "请输出修订后的第一阶段业务制造计划纯文本。",
                ),
            ]
        )
    if prompt_id == PromptId.RUNTIME_PATTERN_SELECTION:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是 Agent 工厂第二阶段的 RuntimeKernel pattern 选择器。\n"
                    "Return JSON only. The word JSON is required: output must be a valid JSON object.\n"
                    "你只能根据业务制造计划和 pattern catalog 摘要选择一个主运行模式。\n\n"
                    "严格约束：\n"
                    "- 必须从 pattern catalog 中选择一个 kind=main 且 embeddable=false 的 pattern_id。\n"
                    "- 不允许发明 pattern_id。\n"
                    "- 不允许引用 catalog 中没有提供的 nodes、edges、wrappers、contracts。\n"
                    "- 不规划节点职责、路由、中断点、wrapper、上下文、记忆、工具、资源或 AssemblySpec。\n"
                    "- 只解释为什么该 pattern 适合当前业务制造计划。\n\n"
                    "Output JSON schema:\n{output_json_schema}",
                ),
                (
                    "user",
                    "第一阶段整理后的需求：\n{requirement_brief}\n\n"
                    "业务制造计划：\n{refined_plan_text}\n\n"
                    "可选 pattern catalog 摘要：\n{pattern_catalog}\n\n"
                    "请返回 JSON。",
                ),
            ]
        )
    if prompt_id == PromptId.GRAPH_BEHAVIOR_PLANNING:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是 Agent 工厂第三阶段的图行为规划器。\n"
                    "Return JSON only. The word JSON is required: output must be a valid JSON object.\n"
                    "你的任务是把已选 RuntimeKernel pattern 的结构摘要解释成该 Agent 的业务图行为计划。\n\n"
                    "严格约束：\n"
                    "- 只能使用 pattern_structure_summary 中已有的 node_id、node_type、routes、interrupt_points、termination。\n"
                    "- 不允许增删节点。\n"
                    "- 不允许增删边。\n"
                    "- 不允许发明 route condition。\n"
                    "- 不允许修改 pattern_id。\n"
                    "- 不规划 wrapper、上下文策略、记忆策略、policy、工具可见性、资源需求或 AssemblySpec。\n"
                    "- 只说明这个 Agent 准备如何使用该 pattern 的图行为。\n\n"
                    "Output JSON schema:\n{output_json_schema}",
                ),
                (
                    "user",
                    "业务制造计划：\n{refined_plan_text}\n\n"
                    "第二阶段 pattern 选择结果：\n{runtime_pattern_selection}\n\n"
                    "Pattern 结构摘要：\n{pattern_structure_summary}\n\n"
                    "请返回 JSON。",
                ),
            ]
        )
    if prompt_id == PromptId.FACTORY_CHAT:
        return ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are FastAgentFactory's shell assistant.\n"
                    "Answer normal chat directly in Chinese.\n"
                    "Be concise, warm, and practical.",
                ),
                ("placeholder", "{messages}"),
            ]
        )
    raise KeyError(f"unknown prompt id: {prompt_id}")


def output_json_schema(model: type[BaseModel]) -> str:
    return json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2)
