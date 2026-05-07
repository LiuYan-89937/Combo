from __future__ import annotations

from enum import Enum
import json
from typing import Literal

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, ConfigDict, Field


class PromptId(str, Enum):
    CAPTURE_REQUIREMENT_INTENT = "factory.capture_requirement.intent"
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
