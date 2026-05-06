from __future__ import annotations

import asyncio
import json
import re
from typing import Literal

from pydantic import ConfigDict, Field, ValidationError

from agent_factory.core.types import JsonDumpMixin
from agent_factory.factory_context import FactoryContextEnvelope, apply_context_envelope
from agent_factory.factory_runtime import FactoryRunContext
from agent_factory.model import LLMRequest, MessageBuilder, ModelConfigError, ModelService
from agent_factory.model.types import ModelError


FactoryIntent = Literal["create_agent_clear", "create_agent_unclear", "not_agent_request"]


class ClarificationOption(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    id: str
    label: str
    description: str = ""


class IntentClarificationQuestion(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    id: str
    question: str
    options: list[ClarificationOption] = Field(default_factory=list)


class FactoryIntentClassification(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    intent: FactoryIntent
    confidence: float = Field(default=0.5, ge=0, le=1)
    normalized_requirement: str | None = None
    agent_hint: str | None = None
    clarification_questions: list[IntentClarificationQuestion] = Field(default_factory=list)
    guidance_message: str | None = None


class FactoryIntentResult(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    classification: FactoryIntentClassification
    source: Literal["llm", "fallback"] = "llm"
    error: ModelError | None = None


class FactoryIntentClassifier:
    """Small-model gate before expensive Factory production.

    It only decides whether the user is asking to create an Agent. Agent design
    analysis and package generation remain later graph nodes.
    """

    def __init__(self, model_service: ModelService | None = None) -> None:
        self.model_service = model_service

    async def classify(
        self,
        context: FactoryRunContext,
        *,
        requirement: str,
        context_envelope: FactoryContextEnvelope | None = None,
    ) -> FactoryIntentResult:
        if self._should_use_fallback_without_model_call():
            return FactoryIntentResult(
                classification=_fallback_classification(requirement),
                source="fallback",
            )
        try:
            model = self._model()
            request = apply_context_envelope(
                self._build_request(context, requirement=requirement),
                context_envelope,
            )
            result = await model.generate_task_structured(
                request,
                schema=FactoryIntentClassification.model_json_schema(),
                schema_name="FactoryIntentClassification",
            )
            if result.error:
                return FactoryIntentResult(
                    classification=_fallback_classification(requirement),
                    source="fallback",
                    error=result.error,
                )
            classification = FactoryIntentClassification.model_validate(result.data)
            classification = _normalize_classification(classification, requirement)
            return FactoryIntentResult(classification=classification, source="llm")
        except (ModelConfigError, ValidationError, TypeError, ValueError) as error:
            model_error = ModelError(
                type="factory_intent_fallback",
                message=str(error),
            )
            return FactoryIntentResult(
                classification=_fallback_classification(requirement),
                source="fallback",
                error=model_error,
            )

    def classify_sync(
        self,
        context: FactoryRunContext,
        *,
        requirement: str,
        context_envelope: FactoryContextEnvelope | None = None,
    ) -> FactoryIntentResult:
        return asyncio.run(
            self.classify(
                context,
                requirement=requirement,
                context_envelope=context_envelope,
            )
        )

    def _model(self) -> ModelService:
        if self.model_service is not None:
            return self.model_service
        return ModelService.from_env()

    def _should_use_fallback_without_model_call(self) -> bool:
        if self.model_service is None:
            return False
        router = getattr(self.model_service, "router", None)
        config = getattr(router, "config", None)
        return getattr(config, "provider", None) == "fake"

    def _build_request(self, context: FactoryRunContext, *, requirement: str) -> LLMRequest:
        schema = FactoryIntentClassification.model_json_schema()
        prompt = (
            "Classify the user's latest Factory Shell input before AgentPackage generation.\n\n"
            "Return exactly one JSON object matching the schema.\n"
            "Do not create an AgentPackage. Do not write code. Do not ask free-form questions.\n\n"
            "Intent labels:\n"
            "- create_agent_clear: the user clearly wants to create/build/design/generate an Agent, "
            "and gave at least a role/type/persona plus a basic goal or scenario.\n"
            "- create_agent_unclear: the user probably wants to create an Agent, but essential facts "
            "are missing. Provide 1 to 3 option-style clarification questions.\n"
            "- not_agent_request: the input is casual chat, random text, an unrelated task, or cannot "
            "reasonably be treated as an Agent creation request. Provide a short guidance_message that "
            "introduces AgentFactory and gives one concrete next-input example.\n\n"
            "For create_agent_unclear, every clarification question must include 2 to 4 concrete options. "
            "Keep options concise and useful for non-technical users.\n\n"
            f"Factory run id: {context.run_id}\n\n"
            f"User input:\n{requirement}\n\n"
            "FactoryIntentClassification JSON Schema:\n"
            f"{json.dumps(schema, ensure_ascii=False)}"
        )
        return (
            MessageBuilder.start()
            .system(
                "You are AgentFactory's lightweight intent classifier. Use the task model. "
                "Return valid JSON only. Never use markdown fences."
            )
            .user(prompt)
            .request(
                response_format="json_schema",
                json_schema=schema,
                json_schema_name="FactoryIntentClassification",
                json_schema_strict=True,
                metadata={
                    "factory_run_id": context.run_id,
                    "operation": "classify_factory_intent",
                    "model_role": "task",
                },
            )
        )


def _normalize_classification(
    classification: FactoryIntentClassification,
    requirement: str,
) -> FactoryIntentClassification:
    if classification.intent == "create_agent_clear":
        return classification.model_copy(
            update={
                "clarification_questions": [],
                "guidance_message": None,
            }
        )
    if classification.intent == "create_agent_unclear":
        questions = [
            _ensure_other_option(question)
            for question in (classification.clarification_questions or _default_clarification_questions())
        ]
        return classification.model_copy(update={"clarification_questions": questions})
    guidance = classification.guidance_message or _default_guidance_message()
    if not guidance.strip():
        guidance = _default_guidance_message()
    return classification.model_copy(
        update={
            "normalized_requirement": None,
            "clarification_questions": [],
            "guidance_message": guidance,
        }
    )


def _fallback_classification(requirement: str) -> FactoryIntentClassification:
    stripped = requirement.strip()
    if not stripped or len(stripped) < 4:
        return _unclear("输入还太短，无法判断要创建什么 Agent。", confidence=0.25)

    if _looks_like_create_agent_request(stripped):
        if _has_clear_agent_shape(stripped):
            return FactoryIntentClassification(
                intent="create_agent_clear",
                confidence=0.72,
                normalized_requirement=stripped,
                agent_hint=_infer_agent_hint(stripped),
            )
        return _unclear("看起来你想创建 Agent，但还缺少角色或目标。", confidence=0.45)

    if _agent_input_is_too_vague(stripped):
        return _unclear("看起来可能是 Agent 需求，但还需要补全用途。", confidence=0.4)

    return FactoryIntentClassification(
        intent="not_agent_request",
        confidence=0.75,
        guidance_message=_default_guidance_message(),
    )


def _looks_like_create_agent_request(text: str) -> bool:
    lowered = text.lower()
    create_markers = [
        "创建",
        "生成",
        "建立",
        "搭建",
        "设计",
        "开发",
        "做一个",
        "来一个",
        "需要一个",
        "我要一个",
        "build",
        "create",
        "generate",
        "make",
    ]
    agent_markers = [
        "agent",
        "助手",
        "机器人",
        "专家",
        "助理",
        "管理 agent",
    ]
    return any(marker in text or marker in lowered for marker in create_markers) and any(
        marker in text or marker in lowered for marker in agent_markers
    )


def _has_clear_agent_shape(text: str) -> bool:
    if len(text.strip()) >= 12 and _infer_agent_hint(text):
        return True
    lowered = text.lower()
    if "agent" in lowered and len(text.strip()) >= 8:
        return True
    return False


def _agent_input_is_too_vague(text: str) -> bool:
    lowered = text.lower()
    if lowered.strip() in {"agent", "ai agent"}:
        return True
    return any(marker in text or marker in lowered for marker in ["agent", "助手", "机器人"])


def _infer_agent_hint(text: str) -> str | None:
    patterns = [
        r"创建一个(.+?)(?:，|。|,|\.|$)",
        r"生成一个(.+?)(?:，|。|,|\.|$)",
        r"建立一个(.+?)(?:，|。|,|\.|$)",
        r"搭建一个(.+?)(?:，|。|,|\.|$)",
        r"设计一个(.+?)(?:，|。|,|\.|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            hint = match.group(1).strip()
            if hint:
                return hint[:80]
    return None


def _unclear(reason: str, *, confidence: float) -> FactoryIntentClassification:
    return FactoryIntentClassification(
        intent="create_agent_unclear",
        confidence=confidence,
        guidance_message=reason,
        clarification_questions=_default_clarification_questions(),
    )


def _default_clarification_questions() -> list[IntentClarificationQuestion]:
    return [
        IntentClarificationQuestion(
            id="missing_detail",
            question="你想先补充哪类关键信息？",
            options=[
                ClarificationOption(
                    id="role_or_persona",
                    label="角色或人设",
                    description="说明这个 Agent 是谁、面向谁、用什么语气工作。",
                ),
                ClarificationOption(
                    id="main_goal",
                    label="主要目标",
                    description="说明它最重要要帮用户完成什么。",
                ),
                ClarificationOption(
                    id="constraints",
                    label="边界条件",
                    description="说明不能做什么、需要什么输入或审批。",
                ),
                ClarificationOption(
                    id="other",
                    label="其他",
                    description="直接输入完整补充说明。",
                ),
            ],
        ),
    ]


def _ensure_other_option(question: IntentClarificationQuestion) -> IntentClarificationQuestion:
    has_other = any(
        option.id.strip().lower() == "other" or option.label.strip() == "其他"
        for option in question.options
    )
    if has_other:
        return question
    return question.model_copy(
        update={
            "options": [
                *question.options,
                ClarificationOption(
                    id="other",
                    label="其他",
                    description="自己输入更具体的答案。",
                ),
            ]
        }
    )


def _default_guidance_message() -> str:
    return (
        "我是 AgentFactory，可以帮你用自然语言创建、测试、运行和升级 Agent。"
        "你可以这样说：创建一个能读取指定资料并按规则回答问题的 Agent。"
    )
