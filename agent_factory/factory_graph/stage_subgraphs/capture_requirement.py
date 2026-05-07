from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from agent_factory.factory_graph.state import FactoryGraphState
from agent_factory.models import get_main_model, get_main_model_settings
from agent_factory.prompts import (
    ClarifyingQuestionSetOutput,
    PromptId,
    RequirementClarityOutput,
    RequirementMergeOutput,
    get_prompt,
    output_json_schema,
)


MAX_CAPTURE_ITERATIONS = 5
FACTORY_RUNTIME_ENVIRONMENT = """当前 Factory 生产目标与运行环境：
- 当前阶段生产的是 CLI-first Agent，不是移动 App、网页产品或多媒体消费应用。
- Agent 运行方式以文本对话、ReAct 推理、工具调用、文件/搜索/shell 等可审计能力为主。
- 用户提出的能力如果需要额外外部服务、模型、API、数据库、媒体生成或部署环境，应作为资源条件/工具需求澄清，而不是默认假设已经可用。
- 澄清问题应围绕 Agent 目标、输入输出、运行场景、工具/资源条件、权限、安全边界、交付形态展开。
- 不要脱离当前运行环境去发散产品端形态；需要确认时，用“是否需要额外资源/工具/服务”这类方式提问。
"""


def build_capture_requirement_subgraph():
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


def run_capture_requirement_subgraph(state: FactoryGraphState) -> dict[str, Any]:
    original_stage_log_count = len(state.get("stage_log", []))
    final_state = build_capture_requirement_subgraph().invoke(state)
    return _delta_patch(final_state, original_stage_log_count=original_stage_log_count)


def _initialize_requirement(state: FactoryGraphState) -> dict[str, Any]:
    capture = dict(state.get("capture_requirement") or {})
    original_input = capture.get("original_input") or state.get("requirement", "")
    current_requirement = capture.get("current_requirement") or original_input
    return {
        "current_stage": "capture_requirement",
        "capture_requirement": {
            "original_input": original_input,
            "current_requirement": current_requirement,
            "iteration_count": int(capture.get("iteration_count") or 0),
            "max_iterations": int(capture.get("max_iterations") or MAX_CAPTURE_ITERATIONS),
        },
    }


def _judge_requirement_clarity(state: FactoryGraphState) -> dict[str, Any]:
    capture = dict(state.get("capture_requirement") or {})
    clarity = _call_structured_model(
        prompt_id=PromptId.CAPTURE_REQUIREMENT_CLARITY,
        output_model=RequirementClarityOutput,
        values={
            "original_input": capture.get("original_input", ""),
            "current_requirement": capture.get("current_requirement", ""),
            "runtime_environment": FACTORY_RUNTIME_ENVIRONMENT,
            "output_json_schema": output_json_schema(RequirementClarityOutput),
        },
        fallback=RequirementClarityOutput(
            is_clear=True,
            confidence=0.7,
            reason="model unavailable; keep current requirement",
            missing_fields=[],
        ),
    )
    return {"capture_requirement": {**capture, "clarity": clarity.model_dump(mode="json")}}


def _generate_clarifying_question(state: FactoryGraphState) -> dict[str, Any]:
    capture = dict(state.get("capture_requirement") or {})
    clarity = capture.get("clarity") or {}
    question = _call_structured_model(
        prompt_id=PromptId.CAPTURE_REQUIREMENT_QUESTION,
        output_model=ClarifyingQuestionSetOutput,
        values={
            "original_input": capture.get("original_input", ""),
            "current_requirement": capture.get("current_requirement", ""),
            "missing_fields": "\n".join(clarity.get("missing_fields") or []),
            "runtime_environment": FACTORY_RUNTIME_ENVIRONMENT,
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
        "capture_requirement": {
            **capture,
            "clarification": question.model_dump(mode="json"),
        }
    }


def _wait_for_requirement_answer(state: FactoryGraphState) -> dict[str, Any]:
    capture = dict(state.get("capture_requirement") or {})
    answer = interrupt(
        {
            "type": "requirement_clarification",
            **dict(capture.get("clarification") or {}),
        }
    )
    return {"capture_requirement": {**capture, "answer": answer}}


def _merge_requirement_answer(state: FactoryGraphState) -> dict[str, Any]:
    capture = dict(state.get("capture_requirement") or {})
    clarification = dict(capture.get("clarification") or {})
    answer = dict(capture.get("answer") or {})
    merged = _call_structured_model(
        prompt_id=PromptId.CAPTURE_REQUIREMENT_MERGE,
        output_model=RequirementMergeOutput,
        values={
            "original_input": capture.get("original_input", ""),
            "current_requirement": capture.get("current_requirement", ""),
            "answers": _format_answers(clarification, answer),
            "runtime_environment": FACTORY_RUNTIME_ENVIRONMENT,
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
        "capture_requirement": {
            "original_input": capture.get("original_input", ""),
            "current_requirement": merged.current_requirement,
            "iteration_count": iteration_count,
            "max_iterations": int(capture.get("max_iterations") or MAX_CAPTURE_ITERATIONS),
            "assumptions": merged.assumptions,
            "unresolved_questions": merged.unresolved_questions,
        }
    }


def _finalize_requirement(state: FactoryGraphState) -> dict[str, Any]:
    capture = dict(state.get("capture_requirement") or {})
    clarity = dict(capture.get("clarity") or {})
    status = "captured" if clarity.get("is_clear", False) else "needs_human_review"
    return {
        "current_stage": "capture_requirement",
        "status": "running",
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
                "stage_id": "capture_requirement",
                "status": status,
                "message": "capture_requirement completed requirement clarification.",
            }
        ],
    }


def _route_after_clarity(state: FactoryGraphState) -> str:
    capture = state.get("capture_requirement") or {}
    clarity = capture.get("clarity") or {}
    iteration_count = int(capture.get("iteration_count") or 0)
    max_iterations = int(capture.get("max_iterations") or MAX_CAPTURE_ITERATIONS)
    if clarity.get("is_clear") or iteration_count >= max_iterations:
        return "finalize_requirement"
    return "generate_clarifying_question"


def _call_structured_model(*, prompt_id, output_model, values: dict[str, Any], fallback):
    model = get_main_model()
    settings = get_main_model_settings()
    if model is None:
        return fallback
    try:
        prompt_value = get_prompt(prompt_id).invoke(values)
        structured_model = model.with_structured_output(output_model, method="json_mode").with_config(
            tags=["nostream"]
        )
        if settings.max_tokens is not None:
            structured_model = structured_model.bind(max_tokens=settings.max_tokens)
        return structured_model.invoke(prompt_value)
    except Exception:
        return fallback


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
        "capture_requirement",
        "requirement_brief",
    ]
    patch = {key: final_state[key] for key in keys if key in final_state}
    new_stage_log = final_state.get("stage_log", [])[original_stage_log_count:]
    if new_stage_log:
        patch["stage_log"] = new_stage_log
    return patch
