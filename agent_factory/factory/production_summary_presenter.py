from __future__ import annotations

import asyncio
import json
from typing import Literal

from pydantic import ConfigDict, Field, ValidationError

from agent_factory.core.types import JsonDumpMixin
from agent_factory.factory_runtime.redaction import redact_secrets
from agent_factory.model import LLMRequest, MessageBuilder, ModelConfigError, ModelService
from agent_factory.model.types import ModelError


class UserFacingProductionSummary(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    narrative: str
    capability_summary: str = ""
    readiness_summary: str = ""
    next_action: str = ""


class ProductionSummaryPresentationResult(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    presentation: UserFacingProductionSummary
    source: Literal["llm", "fallback"] = "fallback"
    error: ModelError | None = None


class ProductionSummaryPresenter:
    """Create a natural-language summary for a completed AgentPackage draft."""

    def __init__(self, model_service: ModelService | None = None) -> None:
        self.model_service = model_service

    async def present(
        self,
        *,
        agent_name: str | None,
        agent_goal: str | None,
        package_path: str | None,
        summary: dict,
        tool_ids: list[str],
        verification_status: str | None,
        tool_test_status: str | None,
    ) -> ProductionSummaryPresentationResult:
        fallback = fallback_production_summary(
            agent_name=agent_name,
            agent_goal=agent_goal,
            package_path=package_path,
            summary=summary,
            tool_ids=tool_ids,
            verification_status=verification_status,
            tool_test_status=tool_test_status,
        )
        if self.model_service is None:
            return ProductionSummaryPresentationResult(presentation=fallback, source="fallback")
        try:
            result = await self.model_service.generate_task_structured(
                self._build_request(
                    agent_name=agent_name,
                    agent_goal=agent_goal,
                    package_path=package_path,
                    summary=summary,
                    tool_ids=tool_ids,
                    verification_status=verification_status,
                    tool_test_status=tool_test_status,
                ),
                schema=UserFacingProductionSummary.model_json_schema(),
                schema_name="UserFacingProductionSummary",
            )
            if result.error:
                return ProductionSummaryPresentationResult(
                    presentation=fallback,
                    source="fallback",
                    error=result.error,
                )
            presentation = UserFacingProductionSummary.model_validate(result.data)
            presentation = _normalize_presentation(presentation, fallback)
            return ProductionSummaryPresentationResult(presentation=presentation, source="llm")
        except (ModelConfigError, ValidationError, TypeError, ValueError) as error:
            return ProductionSummaryPresentationResult(
                presentation=fallback,
                source="fallback",
                error=ModelError(type="production_summary_presentation_fallback", message=str(error)),
            )

    def present_sync(self, **kwargs) -> ProductionSummaryPresentationResult:
        return asyncio.run(self.present(**kwargs))

    def _build_request(
        self,
        *,
        agent_name: str | None,
        agent_goal: str | None,
        package_path: str | None,
        summary: dict,
        tool_ids: list[str],
        verification_status: str | None,
        tool_test_status: str | None,
    ) -> LLMRequest:
        payload = redact_secrets(
            {
                "agent_name": agent_name,
                "agent_goal": agent_goal,
                "package_path": package_path,
                "tool_ids": tool_ids,
                "verification_status": verification_status,
                "tool_test_status": tool_test_status,
                "production_summary": summary,
            }
        )
        schema = UserFacingProductionSummary.model_json_schema()
        prompt = (
            "Write a concise natural-language Chinese summary for a newly generated AgentPackage.\n\n"
            "Do not repeat the entire file path unless it is useful for the next action. Do not expose secrets. "
            "Do not invent capabilities beyond tool_ids and summary. Mention what the Agent can do, whether "
            "verification passed, any remaining warnings/configuration, and the best next command.\n\n"
            "Return exactly one JSON object matching the schema. No markdown fences.\n\n"
            f"Input:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
            "Output rules:\n"
            "- narrative: 1-3 natural sentences, suitable for shell display.\n"
            "- capability_summary: one sentence about the useful capabilities.\n"
            "- readiness_summary: one sentence about verification/warnings/configuration.\n"
            "- next_action: one concrete next step or command.\n\n"
            "UserFacingProductionSummary JSON Schema:\n"
            f"{json.dumps(schema, ensure_ascii=False)}"
        )
        return (
            MessageBuilder.start()
            .system(
                "You are AgentFactory's lightweight completion summarizer. Use the task model. "
                "Return valid JSON only."
            )
            .user(prompt)
            .request(
                response_format="json_schema",
                json_schema=schema,
                json_schema_name="UserFacingProductionSummary",
                json_schema_strict=True,
                metadata={"operation": "present_production_summary", "model_role": "task"},
            )
        )


def fallback_production_summary(
    *,
    agent_name: str | None,
    agent_goal: str | None,
    package_path: str | None,
    summary: dict,
    tool_ids: list[str],
    verification_status: str | None,
    tool_test_status: str | None,
) -> UserFacingProductionSummary:
    name = agent_name or "这个 Agent"
    tool_text = "、".join(tool_ids[:5]) if tool_ids else "当前 AgentPackage 中声明的能力"
    goal = f"目标是{agent_goal}" if agent_goal else "已经生成了可运行草稿"
    warnings = [str(item) for item in summary.get("warnings") or [] if str(item).strip()]
    pending = [str(item) for item in summary.get("pending_configuration_keys") or [] if str(item).strip()]
    if pending:
        readiness = f"本地验证状态为 {verification_status or 'unknown'}，真实运行前还需要补齐配置：{', '.join(pending[:5])}。"
    elif warnings:
        readiness = f"本地验证状态为 {verification_status or 'unknown'}，仍有 {len(warnings)} 条 warning 需要复核。"
    else:
        readiness = f"本地验证状态为 {verification_status or 'unknown'}，工具测试状态为 {tool_test_status or 'unknown'}。"
    next_steps = [str(item) for item in summary.get("next_steps") or [] if str(item).strip()]
    next_action = next_steps[-1] if next_steps else (f"/run {package_path} --input \"...\"" if package_path else "/run --input \"...\"")
    narrative = f"{name} 已创建完成，{goal}。它可以通过 {tool_text} 等能力处理用户请求。{readiness}"
    return UserFacingProductionSummary(
        narrative=narrative,
        capability_summary=f"可用能力：{tool_text}。",
        readiness_summary=readiness,
        next_action=next_action,
    )


def _normalize_presentation(
    presentation: UserFacingProductionSummary,
    fallback: UserFacingProductionSummary,
) -> UserFacingProductionSummary:
    updates = {
        "narrative": presentation.narrative.strip() or fallback.narrative,
        "capability_summary": presentation.capability_summary.strip() or fallback.capability_summary,
        "readiness_summary": presentation.readiness_summary.strip() or fallback.readiness_summary,
        "next_action": presentation.next_action.strip() or fallback.next_action,
    }
    return presentation.model_copy(update=updates)
