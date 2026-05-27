from __future__ import annotations

import json
import re
from typing import Any

from langgraph.types import interrupt

from agent_factory.factory_package.constants import SCHEDULER_PREPARATION_NODE_ID
from agent_factory.factory_package.model_call import FactoryModelCallError, call_structured_model
from agent_factory.factory_package.schemas import (
    CapabilityContractOutput,
    ProductBriefOutput,
    RuntimeDesignOutput,
    SchedulerPreparationOutput,
    SchedulerSeedRevisionOutput,
    SchedulerSeedValidationReport,
)
from agent_factory.prompts import PromptId, output_json_schema
from agent_factory.scheduler_system.schema import SchedulerSeedPlan


def prepare_scheduler_seeds(
    *,
    product_brief: ProductBriefOutput,
    runtime_design: RuntimeDesignOutput,
    capability_contract: CapabilityContractOutput,
    tool_manufacturing: dict[str, Any],
) -> SchedulerPreparationOutput:
    del capability_contract, tool_manufacturing
    candidates = _scheduler_seed_candidates(product_brief=product_brief, runtime_design=runtime_design)
    if not candidates:
        return SchedulerPreparationOutput(
            approved_seeds=[],
            display_summary="当前 Agent 没有声明需要自动准备的定时任务。",
            validation_report=SchedulerSeedValidationReport(status="valid"),
        )

    review = _normalize_scheduler_seed_review_resume(interrupt(_scheduler_seed_review_payload(candidates)))
    if review["decision"] == "skip":
        return SchedulerPreparationOutput(
            approved_seeds=[],
            display_summary="用户选择暂不准备定时任务。",
            validation_report=SchedulerSeedValidationReport(status="valid"),
        )
    if review["decision"] == "approve":
        seeds, errors = _validated_candidate_seeds(candidates)
        if errors:
            raise FactoryModelCallError("scheduler seed review still needs details: " + "; ".join(errors))
        return _preparation_output(seeds=seeds, summary="定时任务方案已确认。")

    revision_text = str(review.get("revision_text") or "").strip()
    if not revision_text:
        raise FactoryModelCallError("scheduler seed revision is empty")
    resolved = _resolve_scheduler_seed_revision(
        product_brief=product_brief,
        runtime_design=runtime_design,
        candidates=candidates,
        revision_text=revision_text,
    )
    if resolved.decision == "skip":
        return SchedulerPreparationOutput(
            approved_seeds=[],
            display_summary=resolved.display_summary or "用户选择暂不准备定时任务。",
            warnings=list(resolved.warnings),
            validation_report=SchedulerSeedValidationReport(status="valid"),
        )
    errors = validate_scheduler_preparation_seeds(resolved.seeds)
    if errors:
        raise FactoryModelCallError("scheduler seed revision failed validation: " + "; ".join(errors))
    return _preparation_output(
        seeds=resolved.seeds,
        summary=resolved.display_summary or "定时任务方案已确认。",
        warnings=list(resolved.warnings),
    )


def validate_scheduler_preparation_seeds(seeds: list[SchedulerSeedPlan]) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for seed in seeds:
        if seed.seed_id in seen:
            errors.append(f"duplicate seed_id: {seed.seed_id}")
        seen.add(seed.seed_id)
        if not seed.enabled_on_apply:
            errors.append(f"{seed.seed_id}: enabled_on_apply must be true for confirmed scheduler seeds")
        if seed.target.target_type != "graph_run":
            payload = seed.target.payload
            if seed.target.target_type == "tool_call" and not str(payload.get("tool_id") or "").strip():
                errors.append(f"{seed.seed_id}: tool_call seed requires payload.tool_id")
            if seed.target.target_type == "script_run" and not str(payload.get("command") or "").strip():
                errors.append(f"{seed.seed_id}: script_run seed requires payload.command")
    return errors


def scheduler_preparation_message(output: SchedulerPreparationOutput) -> str:
    if not output.approved_seeds:
        return output.display_summary or "Scheduler Preparation 已完成：无需准备定时任务。"
    lines = ["Scheduler Preparation 已完成。", ""]
    for seed in output.approved_seeds:
        lines.extend(
            [
                f"- {seed.title}",
                f"  时间：{seed.human_schedule}",
                f"  动作：{seed.task_content}",
                f"  失败治理：连续失败 {seed.failure_policy.max_consecutive_failures} 次后自动暂停",
                f"  完成反馈：{'开启' if seed.feedback.enabled else '关闭'}",
            ]
        )
    if output.warnings:
        lines.extend(["", "提示：", *[f"- {item}" for item in output.warnings]])
    return "\n".join(lines).strip()


def _preparation_output(
    *,
    seeds: list[SchedulerSeedPlan],
    summary: str,
    warnings: list[str] | None = None,
) -> SchedulerPreparationOutput:
    errors = validate_scheduler_preparation_seeds(seeds)
    return SchedulerPreparationOutput(
        approved_seeds=seeds,
        display_summary=summary,
        warnings=list(warnings or []),
        validation_report=SchedulerSeedValidationReport(
            status="invalid" if errors else "valid",
            errors=errors,
            warnings=list(warnings or []),
        ),
    )


def _scheduler_seed_candidates(
    *,
    product_brief: ProductBriefOutput,
    runtime_design: RuntimeDesignOutput,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for slot in runtime_design.pattern_slots:
        if slot.slot_type != "scheduler" or getattr(slot.binding, "kind", "") != "scheduler":
            continue
        binding = slot.binding
        schedule = _parse_schedule_intent(getattr(binding, "schedule_intent", ""))
        target_message = str(getattr(binding, "target_message", "") or "").strip()
        if not target_message:
            target_message = f"请执行定时任务：{product_brief.agent_goal or runtime_design.graph_intent}"
        source_slot_id = str(slot.slot_id)
        candidates.append(
            {
                "seed_id": _safe_seed_id(source_slot_id),
                "title": slot.purpose or "定时运行 Agent",
                "human_schedule": str(getattr(binding, "schedule_intent", "") or "需要补充执行时间"),
                "schedule_type": schedule.get("schedule_type") or "",
                "schedule_expr": schedule.get("schedule_expr") or "",
                "timezone": "Asia/Shanghai",
                "target": {
                    "target_type": "graph_run",
                    "payload": {
                        "message": target_message,
                        "thread_policy": "new_thread_per_run",
                    },
                },
                "task_content": target_message,
                "enabled_on_apply": True,
                "source_slot_id": source_slot_id,
                "missing_questions": schedule.get("missing_questions") or [],
            }
        )
    return candidates


def _validated_candidate_seeds(candidates: list[dict[str, Any]]) -> tuple[list[SchedulerSeedPlan], list[str]]:
    seeds: list[SchedulerSeedPlan] = []
    errors: list[str] = []
    for candidate in candidates:
        missing = [str(item) for item in candidate.get("missing_questions") or [] if str(item).strip()]
        if missing:
            errors.extend(missing)
            continue
        try:
            seeds.append(SchedulerSeedPlan.model_validate({key: value for key, value in candidate.items() if key != "missing_questions"}))
        except Exception as exc:
            errors.append(f"{candidate.get('seed_id') or 'scheduler_seed'}: {exc}")
    errors.extend(validate_scheduler_preparation_seeds(seeds))
    return seeds, errors


def _scheduler_seed_review_payload(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    missing_questions: list[str] = []
    for candidate in candidates:
        missing_questions.extend(str(item) for item in candidate.get("missing_questions") or [] if str(item).strip())
    return {
        "type": "scheduler_seed_review",
        "node_id": SCHEDULER_PREPARATION_NODE_ID,
        "title": "确认定时任务",
        "message": "工具已经准备好。请确认这个 Agent 需要自动启用的定时任务；也可以直接说怎么修改。",
        "seeds": [_review_seed_payload(candidate) for candidate in candidates],
        "missing_questions": _dedupe(missing_questions),
    }


def _review_seed_payload(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "seed_id": candidate.get("seed_id"),
        "title": candidate.get("title"),
        "human_schedule": candidate.get("human_schedule"),
        "task_content": candidate.get("task_content"),
        "enabled_on_apply": candidate.get("enabled_on_apply", True),
        "feedback_enabled": bool((candidate.get("feedback") or {"enabled": True}).get("enabled", True))
        if isinstance(candidate.get("feedback") or {"enabled": True}, dict)
        else True,
        "failure_policy": {"max_consecutive_failures": 3, "action": "pause"},
        "advanced": {
            "schedule_type": candidate.get("schedule_type") or "",
            "schedule_expr": candidate.get("schedule_expr") or "",
            "timezone": candidate.get("timezone") or "Asia/Shanghai",
            "target_type": (candidate.get("target") or {}).get("target_type", "graph_run")
            if isinstance(candidate.get("target"), dict)
            else "graph_run",
            "thread_policy": ((candidate.get("target") or {}).get("payload") or {}).get("thread_policy", "new_thread_per_run")
            if isinstance(candidate.get("target"), dict)
            else "new_thread_per_run",
        },
    }


def _normalize_scheduler_seed_review_resume(resume_payload: Any) -> dict[str, str]:
    if isinstance(resume_payload, str):
        text = resume_payload.strip()
        lowered = text.lower()
        if lowered in {"y", "yes", "approve", "确认", "继续"}:
            return {"decision": "approve", "revision_text": ""}
        if lowered in {"skip", "no", "n", "暂不定时", "暂不提供", "不启用"}:
            return {"decision": "skip", "revision_text": text}
        return {"decision": "revise", "revision_text": text}
    if not isinstance(resume_payload, dict):
        raise FactoryModelCallError("scheduler seed review resume payload must be an object or text")
    decision = str(resume_payload.get("decision") or "approve").strip()
    if decision not in {"approve", "revise", "skip"}:
        raise FactoryModelCallError(f"unsupported scheduler seed review decision: {decision}")
    return {
        "decision": decision,
        "revision_text": str(resume_payload.get("revision_text") or resume_payload.get("note") or ""),
    }


def _resolve_scheduler_seed_revision(
    *,
    product_brief: ProductBriefOutput,
    runtime_design: RuntimeDesignOutput,
    candidates: list[dict[str, Any]],
    revision_text: str,
) -> SchedulerSeedRevisionOutput:
    return call_structured_model(
        stage_id=SCHEDULER_PREPARATION_NODE_ID,
        prompt_id=PromptId.SCHEDULER_SEED_REVISION,
        output_model=SchedulerSeedRevisionOutput,
        values={
            "product_brief": json.dumps(product_brief.model_dump(mode="json"), ensure_ascii=False, indent=2),
            "runtime_design": json.dumps(runtime_design.model_dump(mode="json"), ensure_ascii=False, indent=2),
            "seed_candidates": json.dumps(candidates, ensure_ascii=False, indent=2),
            "revision_text": revision_text,
            "output_json_schema": output_json_schema(SchedulerSeedRevisionOutput),
        },
    )


def _parse_schedule_intent(value: str) -> dict[str, Any]:
    text = value.strip()
    if not text:
        return {"missing_questions": ["请补充定时任务的执行时间。"]}
    cron_match = re.fullmatch(r"\s*([0-5]?\d)\s+([01]?\d|2[0-3]|\*)\s+(\*|\d+)\s+(\*|\d+)\s+(\*|[0-7](?:-[0-7])?)\s*", text)
    if cron_match:
        return {"schedule_type": "cron", "schedule_expr": " ".join(cron_match.groups())}
    minute_match = re.search(r"(?:每|every)\s*(\d+)?\s*(?:分钟|minute|minutes|min)", text, flags=re.IGNORECASE)
    if minute_match:
        minutes = int(minute_match.group(1) or "1")
        return {"schedule_type": "interval", "schedule_expr": str(minutes * 60)}
    second_match = re.search(r"(?:每|every)\s*(\d+)\s*(?:秒|second|seconds|sec)", text, flags=re.IGNORECASE)
    if second_match:
        return {"schedule_type": "interval", "schedule_expr": str(int(second_match.group(1)))}
    time_match = re.search(r"([01]?\d|2[0-3])[:：]([0-5]\d)", text)
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2))
        weekday = "1-5" if any(token in text for token in ["工作日", "交易日", "weekday", "weekdays", "周一到周五"]) else "*"
        return {"schedule_type": "cron", "schedule_expr": f"{minute} {hour} * * {weekday}"}
    return {"missing_questions": [f"请补充“{text}”对应的具体执行时间，例如每天 09:00 或工作日 17:00。"]}


def _safe_seed_id(value: str) -> str:
    raw = value.lower()
    result = []
    previous_sep = False
    for char in raw:
        if char.isalnum() or char in {"_", "-"}:
            result.append(char)
            previous_sep = False
        elif not previous_sep:
            result.append("_")
            previous_sep = True
    return ("".join(result).strip("_-") or "scheduler_seed")[:80]


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        text = str(raw).strip()
        if not text or text in seen:
            continue
        result.append(text)
        seen.add(text)
    return result
