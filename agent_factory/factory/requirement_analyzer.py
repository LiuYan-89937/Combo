from __future__ import annotations

import asyncio
import json
from typing import Literal
from collections.abc import Callable

from pydantic import ConfigDict, Field, ValidationError

from agent_factory.core.types import JsonDumpMixin
from agent_factory.factory_runtime import FactoryRunContext
from agent_factory.model import LLMRequest, LLMStreamEvent, MessageBuilder, ModelConfigError, ModelService
from agent_factory.model.types import ModelError


class RequirementAnalysis(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    is_clear_enough: bool
    agent_name: str | None = None
    agent_type: str | None = None
    persona: str | None = None
    target_users: list[str] = Field(default_factory=list)
    goals: list[str] = Field(default_factory=list)
    in_scope_tasks: list[str] = Field(default_factory=list)
    out_of_scope_boundaries: list[str] = Field(default_factory=list)
    needed_tools: list[str] = Field(default_factory=list)
    needed_memory: list[str] = Field(default_factory=list)
    safety_profile: Literal[
        "general",
        "customer_service",
        "companion_agent",
        "education",
        "productivity",
        "creative",
        "high_risk",
    ] = "general"
    missing_required_fields: list[str] = Field(default_factory=list)
    clarification_questions: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.7, ge=0, le=1)


class RequirementAnalysisResult(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    analysis: RequirementAnalysis
    source: Literal["llm", "fallback"] = "llm"
    error: ModelError | None = None


class RequirementAnalyzer:
    """Structured requirement analysis for Factory production.

    This is the Factory's product-manager/architect brain. It decides whether
    a request needs clarification by looking for missing product facts, not by
    matching a fixed domain keyword list.
    """

    def __init__(self, model_service: ModelService | None = None) -> None:
        self.model_service = model_service

    async def analyze(
        self,
        context: FactoryRunContext,
        *,
        requirement: str,
        on_stream_event: Callable[[LLMStreamEvent], None] | None = None,
    ) -> RequirementAnalysisResult:
        if self._should_use_fallback_without_model_call():
            return RequirementAnalysisResult(
                analysis=_fallback_analysis(requirement),
                source="fallback",
            )
        try:
            model = self._model()
            request = self._build_request(context, requirement=requirement)
            if on_stream_event:
                result = await model.stream_structured(request, on_event=on_stream_event)
            else:
                result = await model.generate_structured(request)
            if result.error:
                return RequirementAnalysisResult(
                    analysis=_fallback_analysis(requirement),
                    source="fallback",
                    error=result.error,
                )
            analysis = RequirementAnalysis.model_validate(result.data)
            return RequirementAnalysisResult(analysis=analysis, source="llm")
        except (ModelConfigError, ValidationError, TypeError, ValueError) as error:
            model_error = ModelError(
                type="requirement_analysis_fallback",
                message=str(error),
            )
            return RequirementAnalysisResult(
                analysis=_fallback_analysis(requirement),
                source="fallback",
                error=model_error,
            )

    def analyze_sync(
        self,
        context: FactoryRunContext,
        *,
        requirement: str,
        on_stream_event: Callable[[LLMStreamEvent], None] | None = None,
    ) -> RequirementAnalysisResult:
        return asyncio.run(
            self.analyze(
                context,
                requirement=requirement,
                on_stream_event=on_stream_event,
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
        schema = RequirementAnalysis.model_json_schema()
        prompt = (
            "Analyze the user's Agent creation requirement and return one JSON object.\n"
            "Do not create the AgentPackage yet. Decide whether the requirement is clear enough.\n\n"
            "A requirement is clear enough when it provides at least an agent role/type and a basic goal "
            "or persona. Do not require implementation details, tool APIs, database schemas, or UI details "
            "during this step. For personal companion, roleplay, coaching, customer-service, education, "
            "creative, productivity, and other domains, infer reasonable first-draft goals if the user gave "
            "a clear role/name.\n\n"
            "Only ask clarification questions for genuinely missing essentials, such as no role/type, no "
            "goal, contradictory safety requirements, or requests that need prohibited/high-risk behavior.\n\n"
            f"Requirement:\n{requirement}\n\n"
            f"Factory run id: {context.run_id}\n\n"
            "RequirementAnalysis JSON Schema:\n"
            f"{json.dumps(schema, ensure_ascii=False)}"
        )
        return (
            MessageBuilder.start()
            .system(
                "You are AgentFactory's requirement analyst. Return valid JSON only. "
                "Never use markdown fences."
            )
            .user(prompt)
            .request(
                response_format="json_schema",
                json_schema=schema,
                json_schema_name="RequirementAnalysis",
                json_schema_strict=True,
                metadata={
                    "factory_run_id": context.run_id,
                    "operation": "analyze_requirement",
                },
            )
        )


def _fallback_analysis(requirement: str) -> RequirementAnalysis:
    stripped = requirement.strip()
    if len(stripped) < 4:
        return RequirementAnalysis(
            is_clear_enough=False,
            missing_required_fields=["agent_role", "goal"],
            clarification_questions=[
                "请描述要创建的 Agent 角色。",
                "请说明它主要要帮助用户完成什么目标。",
            ],
            confidence=0.2,
        )

    inferred_name = _infer_name(stripped)
    lower = stripped.lower()
    if any(marker in stripped for marker in ["恋爱", "女友", "男友", "陪伴", "情感"]):
        return RequirementAnalysis(
            is_clear_enough=True,
            agent_name=inferred_name,
            agent_type="virtual_companion",
            persona=stripped,
            target_users=["需要情感陪伴和日常聊天的用户"],
            goals=["情感陪伴", "日常聊天", "温柔回应", "保持边界和安全"],
            in_scope_tasks=["闲聊", "情绪安抚", "日常问候", "陪伴式互动"],
            out_of_scope_boundaries=["不诱导依赖", "不提供医疗或法律建议", "不进行成人或高风险内容"],
            needed_tools=[],
            needed_memory=["用户偏好", "互动称呼", "长期关系设定"],
            safety_profile="companion_agent",
            confidence=0.65,
        )

    if any(marker in lower for marker in ["agent", "assistant"]) or any(
        marker in stripped for marker in ["助手", "机器人", "客服", "专家", "助理"]
    ):
        return RequirementAnalysis(
            is_clear_enough=True,
            agent_name=inferred_name,
            agent_type="general_agent",
            persona=stripped,
            goals=["根据用户需求完成首版 Agent 草稿"],
            in_scope_tasks=["对话回复", "任务理解", "安全边界内协助"],
            safety_profile="general",
            confidence=0.55,
        )

    return RequirementAnalysis(
        is_clear_enough=False,
        persona=stripped,
        missing_required_fields=["agent_role_or_type"],
        clarification_questions=["请说明你想创建的 Agent 类型、角色或使用场景。"],
        confidence=0.35,
    )


def _infer_name(requirement: str) -> str | None:
    for marker in ["叫", "名叫", "名字是"]:
        if marker in requirement:
            name = requirement.split(marker, 1)[1].strip(" 。，“”\"'")
            return name[:30] or None
    return None
