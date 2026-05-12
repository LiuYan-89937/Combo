from __future__ import annotations

from typing import Any
import uuid

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from agent_factory.factory_graph.schemas import (
    ClarifyingQuestionSetOutput,
    RequirementClarityOutput,
    RequirementMergeOutput,
)
from agent_factory.factory_graph.prompt_context import prompt_context_values, stage_operating_context
from agent_factory.factory_graph.state import FactoryGraphState
from agent_factory.factory_graph.model_call import (
    emit_model_activity,
    model_activity_completed,
    model_activity_failed,
    model_activity_started,
)
from agent_factory.models import get_main_model, get_main_model_settings
from agent_factory.prompts import (
    PromptId,
    get_prompt,
    output_json_schema,
)


MAX_CAPTURE_ITERATIONS = 5
CLARITY_CONFIDENCE_THRESHOLD = 0.85
STAGE_ID = "requirement_capture"


def build_requirement_capture_subgraph():
    graph = StateGraph(FactoryGraphState)
    graph.add_node("initialize_requirement", _initialize_requirement)
    graph.add_node("judge_requirement_clarity", _judge_requirement_clarity)
    graph.add_node("generate_clarifying_question", _generate_clarifying_question)
    graph.add_node("wait_for_requirement_answer", _wait_for_requirement_answer)
    graph.add_node("merge_requirement_answer", _merge_requirement_answer)
    graph.add_node("finalize_requirement", _finalize_requirement)
    graph.add_edge(START, "initialize_requirement")
    graph.add_edge("initialize_requirement", "judge_requirement_clarity")
    graph.add_conditional_edges(
        "judge_requirement_clarity",
        _route_after_clarity,
        {
            "generate_clarifying_question": "generate_clarifying_question",
            "finalize_requirement": "finalize_requirement",
        },
    )
    graph.add_edge("generate_clarifying_question", "wait_for_requirement_answer")
    graph.add_edge("wait_for_requirement_answer", "merge_requirement_answer")
    graph.add_edge("merge_requirement_answer", "judge_requirement_clarity")
    graph.add_edge("finalize_requirement", END)
    return graph.compile()


def run_requirement_capture_subgraph(state: FactoryGraphState) -> dict[str, Any]:
    original_stage_log_count = len(state.get("stage_log", []))
    final_state = build_requirement_capture_subgraph().invoke(state)
    return _delta_patch(final_state, original_stage_log_count=original_stage_log_count)


def _initialize_requirement(state: FactoryGraphState) -> dict[str, Any]:
    capture = dict(state.get("requirement_capture") or {})
    original_input = capture.get("original_input") or state.get("requirement", "")
    current_requirement = capture.get("current_requirement") or original_input
    return {
        "current_stage": "requirement_capture",
        "requirement_capture": {
            "original_input": original_input,
            "current_requirement": current_requirement,
            "iteration_count": int(capture.get("iteration_count") or 0),
            "max_iterations": int(capture.get("max_iterations") or MAX_CAPTURE_ITERATIONS),
        },
    }


def _judge_requirement_clarity(state: FactoryGraphState) -> dict[str, Any]:
    capture = dict(state.get("requirement_capture") or {})
    clarity, model_error = _call_structured_model(
        prompt_id=PromptId.REQUIREMENT_CAPTURE_CLARITY,
        output_model=RequirementClarityOutput,
        values={
            "original_input": capture.get("original_input", ""),
            "current_requirement": capture.get("current_requirement", ""),
            "runtime_environment": stage_operating_context(STAGE_ID),
            "output_json_schema": output_json_schema(RequirementClarityOutput),
        },
        fallback=RequirementClarityOutput(
            is_clear=False,
            confidence=0.0,
            reason="model unavailable; requirement clarity cannot be confirmed",
            missing_fields=["需要补充业务目标、使用场景、输入输出、边界与成功标准"],
        ),
    )
    return {
        "requirement_capture": {**capture, "clarity": clarity.model_dump(mode="json")},
        **_model_error_state(model_error),
    }


def _generate_clarifying_question(state: FactoryGraphState) -> dict[str, Any]:
    capture = dict(state.get("requirement_capture") or {})
    clarity = capture.get("clarity") or {}
    question, model_error = _call_structured_model(
        prompt_id=PromptId.REQUIREMENT_CAPTURE_QUESTION,
        output_model=ClarifyingQuestionSetOutput,
        values={
            "original_input": capture.get("original_input", ""),
            "current_requirement": capture.get("current_requirement", ""),
            "missing_fields": "\n".join(clarity.get("missing_fields") or []),
            "runtime_environment": stage_operating_context(STAGE_ID),
            "output_json_schema": output_json_schema(ClarifyingQuestionSetOutput),
        },
        fallback=ClarifyingQuestionSetOutput(
            questions=[
                {
                    "id": "usage_scenario",
                    "question": "你希望这个 Agent 主要服务于哪类场景？",
                    "options": [
                        {"id": "personal", "label": "个人使用", "description": "帮助单个用户完成任务"},
                        {"id": "team", "label": "团队协作", "description": "支持多人共享或协同流程"},
                        {"id": "business", "label": "业务流程", "description": "面向稳定可审计的业务流程"},
                        {"id": "custom", "label": "自定义补充", "description": "自己描述场景和目标"},
                    ],
                    "custom_option_id": "custom",
                }
            ]
        ),
    )
    return {
        "requirement_capture": {
            **capture,
            "clarification": question.model_dump(mode="json"),
        },
        **_model_error_state(model_error),
    }


def _wait_for_requirement_answer(state: FactoryGraphState) -> dict[str, Any]:
    capture = dict(state.get("requirement_capture") or {})
    answer = interrupt(
        {
            "type": "requirement_clarification",
            **dict(capture.get("clarification") or {}),
        }
    )
    return {"requirement_capture": {**capture, "answer": answer}}


def _merge_requirement_answer(state: FactoryGraphState) -> dict[str, Any]:
    capture = dict(state.get("requirement_capture") or {})
    clarification = dict(capture.get("clarification") or {})
    answer = dict(capture.get("answer") or {})
    merged, model_error = _call_structured_model(
        prompt_id=PromptId.REQUIREMENT_CAPTURE_MERGE,
        output_model=RequirementMergeOutput,
        values={
            "original_input": capture.get("original_input", ""),
            "current_requirement": capture.get("current_requirement", ""),
            "answers": _format_answers(clarification, answer),
            "runtime_environment": stage_operating_context(STAGE_ID),
            "output_json_schema": output_json_schema(RequirementMergeOutput),
        },
        fallback=RequirementMergeOutput(
            current_requirement=_fallback_merged_requirement(capture, answer),
            assumptions=[],
            unresolved_questions=[],
        ),
    )
    iteration_count = int(capture.get("iteration_count") or 0) + 1
    return {
        "requirement_capture": {
            "original_input": capture.get("original_input", ""),
            "current_requirement": merged.current_requirement,
            "iteration_count": iteration_count,
            "max_iterations": int(capture.get("max_iterations") or MAX_CAPTURE_ITERATIONS),
            "assumptions": merged.assumptions,
            "unresolved_questions": merged.unresolved_questions,
        },
        **_model_error_state(model_error),
    }


def _finalize_requirement(state: FactoryGraphState) -> dict[str, Any]:
    capture = dict(state.get("requirement_capture") or {})
    clarity = dict(capture.get("clarity") or {})
    status = "captured" if clarity.get("is_clear", False) else "needs_human_review"
    return {
        "current_stage": "requirement_capture",
        "status": "running",
        **({"graph_control": {"action": "end"}} if status != "captured" else {}),
        "requirement_brief": {
            "original_input": capture.get("original_input", ""),
            "refined_requirement": capture.get("current_requirement", ""),
            "assumptions": capture.get("assumptions", []),
            "unresolved_questions": capture.get("unresolved_questions", []),
            "confidence": clarity.get("confidence", 0.0),
            "status": status,
        },
        "stage_log": [
            {
                "stage_id": "requirement_capture",
                "status": status,
                "message": "requirement_capture completed requirement clarification.",
            }
        ],
    }


def _route_after_clarity(state: FactoryGraphState) -> str:
    capture = state.get("requirement_capture") or {}
    clarity = capture.get("clarity") or {}
    iteration_count = int(capture.get("iteration_count") or 0)
    max_iterations = int(capture.get("max_iterations") or MAX_CAPTURE_ITERATIONS)
    confidence = float(clarity.get("confidence") or 0)
    missing_fields = clarity.get("missing_fields") or []
    if clarity.get("is_clear") and confidence >= CLARITY_CONFIDENCE_THRESHOLD and not missing_fields:
        return "finalize_requirement"
    if iteration_count >= max_iterations:
        return "finalize_requirement"
    return "generate_clarifying_question"


def _call_structured_model(*, prompt_id, output_model, values: dict[str, Any], fallback):
    span_id = uuid.uuid4().hex
    model = get_main_model()
    settings = get_main_model_settings()
    if model is None:
        return fallback, f"{prompt_id}: main model is not configured"
    try:
        emit_model_activity(model_activity_started(prompt_id=prompt_id, call_kind="structured_json", span_id=span_id))
        prompt_value = get_prompt(prompt_id).invoke({**prompt_context_values(STAGE_ID), **values})
        structured_model = model.with_structured_output(output_model, method="json_mode").with_config(
            tags=["nostream"]
        )
        if settings.max_tokens is not None:
            structured_model = structured_model.bind(max_tokens=settings.max_tokens)
        result = structured_model.invoke(prompt_value)
        emit_model_activity(
            model_activity_completed(
                prompt_id=prompt_id,
                call_kind="structured_json",
                span_id=span_id,
                output_summary=output_model.__name__,
            )
        )
        return result, None
    except Exception as exc:
        emit_model_activity(
            model_activity_failed(
                prompt_id=prompt_id,
                call_kind="structured_json",
                span_id=span_id,
                message=f"{type(exc).__name__}: {exc}",
            )
        )
        return fallback, f"{prompt_id}: {type(exc).__name__}: {exc}"


def _model_error_state(message: str | None) -> dict[str, Any]:
    if not message:
        return {}
    return {
        "errors": [{"where": STAGE_ID, "message": message}],
        "model_activity": [
            {
                "event_type": "model_call_failed",
                "prompt_id": "requirement_capture",
                "call_kind": "structured_json",
                "message": message,
            }
        ],
    }


def _format_answers(clarification: dict[str, Any], answer: dict[str, Any]) -> str:
    questions_by_id = {
        str(question.get("id") or ""): question for question in clarification.get("questions", [])
    }
    lines: list[str] = []
    for item in answer.get("answers", []):
        question_id = str(item.get("question_id") or "")
        question = questions_by_id.get(question_id, {})
        selected_label = item.get("selected_label") or item.get("selected_option_id") or ""
        custom_text = item.get("custom_text") or ""
        lines.append(f"问题：{question.get('question', question_id)}")
        lines.append(f"回答：{selected_label}")
        if custom_text:
            lines.append(f"自定义补充：{custom_text}")
    return "\n".join(lines)


def _fallback_merged_requirement(capture: dict[str, Any], answer: dict[str, Any]) -> str:
    current = str(capture.get("current_requirement") or "")
    formatted_answer = "\n".join(
        str(item.get("custom_text") or item.get("selected_label") or item.get("selected_option_id") or "")
        for item in answer.get("answers", [])
    ).strip()
    if not formatted_answer:
        return current
    return f"{current}\n\n用户补充：{formatted_answer}"


def _delta_patch(
    final_state: FactoryGraphState,
    *,
    original_stage_log_count: int,
) -> dict[str, Any]:
    keys = [
        "current_stage",
        "status",
        "requirement_capture",
        "requirement_brief",
        "model_activity",
    ]
    patch = {key: final_state[key] for key in keys if key in final_state}
    new_stage_log = final_state.get("stage_log", [])[original_stage_log_count:]
    if new_stage_log:
        patch["stage_log"] = new_stage_log
    return patch
