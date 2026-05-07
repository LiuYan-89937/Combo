from __future__ import annotations

from enum import Enum
import json
from typing import Literal

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, ConfigDict, Field


class PromptId(str, Enum):
    CAPTURE_REQUIREMENT_INTENT = "factory.capture_requirement.intent"
    CAPTURE_REQUIREMENT_CLARITY = "factory.capture_requirement.clarity"
    CAPTURE_REQUIREMENT_QUESTION = "factory.capture_requirement.question"
    CAPTURE_REQUIREMENT_MERGE = "factory.capture_requirement.merge"
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


def get_prompt(prompt_id: PromptId) -> ChatPromptTemplate:
    if prompt_id == PromptId.CAPTURE_REQUIREMENT_INTENT:
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
    if prompt_id == PromptId.CAPTURE_REQUIREMENT_CLARITY:
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
    if prompt_id == PromptId.CAPTURE_REQUIREMENT_QUESTION:
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
    if prompt_id == PromptId.CAPTURE_REQUIREMENT_MERGE:
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
