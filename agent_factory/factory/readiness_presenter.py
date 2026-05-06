from __future__ import annotations

import asyncio
import json
import re
from typing import Literal

from pydantic import ConfigDict, Field, ValidationError

from agent_factory.core.types import JsonDumpMixin
from agent_factory.factory_context import ReadinessDecision, ReadinessItem, ResolutionQuestion
from agent_factory.factory_runtime.redaction import redact_secrets
from agent_factory.model import LLMRequest, MessageBuilder, ModelConfigError, ModelService
from agent_factory.model.types import ModelError
from agent_factory.specs import ReadinessIssue, ReadinessReport


ReadinessPresentationCategory = Literal[
    "local_resource",
    "database",
    "external_service",
    "credential",
    "dependency",
    "approval",
    "other",
]


class UserFacingReadinessItem(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    code: str
    category: ReadinessPresentationCategory = "other"
    subject: str
    problem: str
    impact: str = ""
    next_action: str


class UserFacingReadinessPresentation(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    summary: str
    items: list[UserFacingReadinessItem] = Field(default_factory=list)
    closing_question: str = "你希望怎么处理？"


class ReadinessPresentationResult(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    presentation: UserFacingReadinessPresentation
    source: Literal["llm", "fallback"] = "fallback"
    error: ModelError | None = None


class ReadinessPresenter:
    """Turn internal readiness failures into structured user-facing copy."""

    def __init__(self, model_service: ModelService | None = None) -> None:
        self.model_service = model_service

    async def present(
        self,
        readiness: ReadinessReport,
        decision: ReadinessDecision | None = None,
    ) -> ReadinessPresentationResult:
        fallback = fallback_readiness_presentation(readiness, decision)
        if self.model_service is None or not _has_actionable_issues(readiness):
            return ReadinessPresentationResult(presentation=fallback, source="fallback")
        try:
            result = await self.model_service.generate_task_structured(
                self._build_request(readiness, decision),
                schema=UserFacingReadinessPresentation.model_json_schema(),
                schema_name="UserFacingReadinessPresentation",
            )
            if result.error:
                return ReadinessPresentationResult(
                    presentation=fallback,
                    source="fallback",
                    error=result.error,
                )
            presentation = UserFacingReadinessPresentation.model_validate(result.data)
            presentation = _normalize_presentation(presentation, fallback)
            return ReadinessPresentationResult(presentation=presentation, source="llm")
        except (ModelConfigError, ValidationError, TypeError, ValueError) as error:
            return ReadinessPresentationResult(
                presentation=fallback,
                source="fallback",
                error=ModelError(type="readiness_presentation_fallback", message=str(error)),
            )

    def present_sync(
        self,
        readiness: ReadinessReport,
        decision: ReadinessDecision | None = None,
    ) -> ReadinessPresentationResult:
        return asyncio.run(self.present(readiness, decision))

    def _build_request(
        self,
        readiness: ReadinessReport,
        decision: ReadinessDecision | None,
    ) -> LLMRequest:
        payload = {
            "readiness_status": readiness.status,
            "issues": [
                {
                    "code": issue.code,
                    "severity": issue.severity,
                    "message": issue.message,
                    "resource_id": issue.resource_id,
                    "details": issue.details,
                    "resolution_hint": _resolution_hint_from_decision(decision, issue),
                }
                for issue in readiness.issues
                if issue.severity in {"error", "fatal"}
            ][:5],
        }
        payload = redact_secrets(payload)
        schema = UserFacingReadinessPresentation.model_json_schema()
        prompt = (
            "Rewrite AgentFactory readiness failures into structured, user-facing Chinese.\n\n"
            "The input is already a safe summary. Do not ask for secrets. Keep paths, file names, "
            "URLs, env-like config keys, and database names exact when present. Do not invent facts. "
            "Explain the failed check, why it matters, and one practical next action.\n\n"
            "Return exactly one JSON object matching the schema. No markdown fences.\n\n"
            f"Readiness input:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
            "Output rules:\n"
            "- summary: one natural sentence, not more than 40 Chinese characters if possible.\n"
            "- items: at most 3 items, each with subject/problem/impact/next_action.\n"
            "- problem: state what failed in plain language.\n"
            "- impact: state what AgentFactory cannot safely do yet.\n"
            "- next_action: tell the user what they can choose or provide.\n"
            "- closing_question: a short question asking how to continue.\n\n"
            "UserFacingReadinessPresentation JSON Schema:\n"
            f"{json.dumps(schema, ensure_ascii=False)}"
        )
        return (
            MessageBuilder.start()
            .system(
                "You are AgentFactory's lightweight readiness explainer. Use the task model. "
                "Return valid JSON only. Do not expose secrets."
            )
            .user(prompt)
            .request(
                response_format="json_schema",
                json_schema=schema,
                json_schema_name="UserFacingReadinessPresentation",
                json_schema_strict=True,
                metadata={"operation": "present_readiness", "model_role": "task"},
            )
        )


def apply_readiness_presentation(
    decision: ReadinessDecision,
    presentation: UserFacingReadinessPresentation,
) -> ReadinessDecision:
    blocking = _apply_items_to_readiness_items(decision.blocking, presentation.items)
    options = decision.resolution_questions[0].options if decision.resolution_questions else []
    questions = [
        ResolutionQuestion(
            question_id="readiness_resolution",
            prompt=render_readiness_clarification_prompt(presentation),
            options=options,
            free_text_allowed=True,
        )
    ] if blocking else []
    return decision.model_copy(update={"blocking": blocking, "resolution_questions": questions})


def render_readiness_clarification_prompt(
    presentation: UserFacingReadinessPresentation,
) -> str:
    lines: list[str] = [
        presentation.summary.strip()
        or "当前还不能继续生成 AgentPackage，因为有资源或环境校验未通过。",
        "",
        "需要处理的校验：",
    ]
    for index, item in enumerate(presentation.items[:3], start=1):
        lines.append(f"{index}. {item.subject.strip() or item.code}")
        lines.append(f"   问题：{item.problem.strip()}")
        if item.impact.strip():
            lines.append(f"   影响：{item.impact.strip()}")
        lines.append(f"   建议：{item.next_action.strip()}")
    lines.append("")
    lines.append(presentation.closing_question.strip() or "你希望怎么处理？")
    return "\n".join(lines)


def fallback_readiness_presentation(
    readiness: ReadinessReport,
    decision: ReadinessDecision | None = None,
) -> UserFacingReadinessPresentation:
    issues = [issue for issue in readiness.issues if issue.severity in {"error", "fatal"}]
    items = [_fallback_item(issue, _resolution_hint_from_decision(decision, issue)) for issue in issues[:3]]
    if not items:
        return UserFacingReadinessPresentation(
            summary="当前需要你确认下一步处理方式。",
            items=[],
            closing_question="你希望 AgentFactory 怎么处理？",
        )
    return UserFacingReadinessPresentation(
        summary="当前还不能继续生成 AgentPackage，因为有校验未通过。",
        items=items,
        closing_question="你希望怎么处理？",
    )


def _apply_items_to_readiness_items(
    readiness_items: list[ReadinessItem],
    presentation_items: list[UserFacingReadinessItem],
) -> list[ReadinessItem]:
    updated: list[ReadinessItem] = []
    for index, item in enumerate(readiness_items):
        if index >= len(presentation_items):
            updated.append(item)
            continue
        presentation = presentation_items[index]
        updated.append(
            item.model_copy(
                update={
                    "message": f"{presentation.subject}：{presentation.problem}",
                    "resolution_hint": presentation.next_action,
                }
            )
        )
    return updated


def _fallback_item(
    issue: ReadinessIssue,
    resolution_hint: str | None,
) -> UserFacingReadinessItem:
    target = _target_from_issue(issue)
    hint = resolution_hint or "补充该条件需要的真实信息，或选择只生成不可运行草稿。"
    subject = f"资源/环境校验：{target}" if target else "资源/环境校验"
    return UserFacingReadinessItem(
        code=issue.code,
        category=_category_from_issue(issue),
        subject=subject,
        problem="这项前置条件还没有通过运行前校验。",
        impact="AgentFactory 还不能确认生成的 AgentPackage 可以被真实运行和测试。",
        next_action=hint,
    )


def _normalize_presentation(
    presentation: UserFacingReadinessPresentation,
    fallback: UserFacingReadinessPresentation,
) -> UserFacingReadinessPresentation:
    items = [item for item in presentation.items if item.problem.strip() and item.next_action.strip()]
    if not items:
        items = fallback.items
    if len(items) < len(fallback.items):
        items = [*items, *fallback.items[len(items):]]
    summary = presentation.summary.strip() or fallback.summary
    closing = presentation.closing_question.strip() or fallback.closing_question
    return presentation.model_copy(
        update={
            "summary": _clean_internal_labels(summary),
            "items": [_clean_item(item) for item in items[:3]],
            "closing_question": _clean_internal_labels(closing),
        }
    )


def _clean_item(item: UserFacingReadinessItem) -> UserFacingReadinessItem:
    return item.model_copy(
        update={
            "subject": _clean_internal_labels(item.subject),
            "problem": _clean_internal_labels(item.problem),
            "impact": _clean_internal_labels(item.impact),
            "next_action": _clean_internal_labels(item.next_action),
        }
    )


def _clean_internal_labels(value: str) -> str:
    return re.sub(r"\b[A-Z][A-Za-z0-9_ -]{2,60}:\s*", "", value).strip()


def _target_from_issue(issue: ReadinessIssue) -> str:
    detail_target = issue.details.get("target") if isinstance(issue.details, dict) else None
    if detail_target:
        return str(detail_target)
    cleaned = _clean_internal_labels(issue.message)
    for separator in ("：", ":"):
        if separator in cleaned:
            return cleaned.split(separator, 1)[1].strip() or cleaned
    return cleaned


def _category_from_issue(issue: ReadinessIssue) -> ReadinessPresentationCategory:
    return "other"


def _resolution_hint_from_decision(
    decision: ReadinessDecision | None,
    issue: ReadinessIssue,
) -> str | None:
    if decision is None:
        return None
    for item in [*decision.blocking, *decision.deferred, *decision.warnings]:
        if item.resource_id == issue.resource_id or item.message == issue.message:
            return item.resolution_hint
    return None


def _has_actionable_issues(readiness: ReadinessReport) -> bool:
    return any(issue.severity in {"error", "fatal"} for issue in readiness.issues)
