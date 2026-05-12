from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from agent_factory.factory_graph.state import FactoryGraphState
from agent_factory.factory_graph.model_call import (
    FactoryModelCallError,
    call_text_model,
    model_error_patch,
)
from agent_factory.prompts import PromptId


DEFAULT_REFINED_PLAN_SECTIONS: tuple[str, ...] = (
    "【制造目标】",
    "【使用场景】",
    "【业务行为】",
    "【交互方式】",
    "【业务边界】",
    "【成功标准】",
    "【后续规划提示】",
)


def build_business_plan_review_subgraph():
    graph = StateGraph(FactoryGraphState)
    graph.add_node("load_requirement_brief", _load_requirement_brief)
    graph.add_node("draft_business_plan", _draft_business_plan)
    graph.add_node("present_business_plan", _present_business_plan)
    graph.add_node("revise_business_plan", _revise_business_plan)
    graph.add_node("finalize_business_plan", _finalize_business_plan)
    graph.add_edge(START, "load_requirement_brief")
    graph.add_edge("load_requirement_brief", "draft_business_plan")
    graph.add_conditional_edges(
        "draft_business_plan",
        _route_after_model_step,
        {
            "present_business_plan": "present_business_plan",
            END: END,
        },
    )
    graph.add_conditional_edges(
        "present_business_plan",
        _route_after_plan_review,
        {
            "revise_business_plan": "revise_business_plan",
            "finalize_business_plan": "finalize_business_plan",
        },
    )
    graph.add_conditional_edges(
        "revise_business_plan",
        _route_after_model_step,
        {
            "present_business_plan": "present_business_plan",
            END: END,
        },
    )
    graph.add_edge("finalize_business_plan", END)
    return graph.compile()


def run_business_plan_review_subgraph(state: FactoryGraphState) -> dict[str, Any]:
    original_stage_log_count = len(state.get("stage_log", []))
    final_state = build_business_plan_review_subgraph().invoke(state)
    return _delta_patch(final_state, original_stage_log_count=original_stage_log_count)


def _load_requirement_brief(state: FactoryGraphState) -> dict[str, Any]:
    requirement_brief = dict(state.get("requirement_brief") or {})
    refined_requirement = requirement_brief.get("refined_requirement") or state.get("requirement", "")
    return {
        "current_stage": "requirement_capture",
        "business_plan_review": {
            "requirement_brief": {
                **requirement_brief,
                "refined_requirement": refined_requirement,
            },
            "iteration_count": 0,
        },
    }


def _draft_business_plan(state: FactoryGraphState) -> dict[str, Any]:
    business_plan_review = dict(state.get("business_plan_review") or {})
    requirement_brief = dict(business_plan_review.get("requirement_brief") or {})
    try:
        plan_text = call_text_model(
            stage_id="requirement_capture",
            prompt_id=PromptId.BUSINESS_PLAN_REVIEW_DRAFT,
            values={
                "requirement_brief": _format_requirement_brief(requirement_brief),
                "required_sections": "\n".join(DEFAULT_REFINED_PLAN_SECTIONS),
            },
        )
    except FactoryModelCallError as exc:
        return model_error_patch("requirement_capture", str(exc))
    return {
        "business_plan_review": {
            **business_plan_review,
            "current_plan_text": plan_text,
        }
    }


def _present_business_plan(state: FactoryGraphState) -> dict[str, Any]:
    business_plan_review = dict(state.get("business_plan_review") or {})
    review = interrupt(
        {
            "type": "plan_review",
            "stage_id": "requirement_capture",
            "plan_text": business_plan_review.get("current_plan_text", ""),
            "message": "请审查第一阶段生成的业务制造计划，选择继续或输入修改意见。",
        }
    )
    return {"business_plan_review": {**business_plan_review, "review": review}}


def _revise_business_plan(state: FactoryGraphState) -> dict[str, Any]:
    business_plan_review = dict(state.get("business_plan_review") or {})
    review = dict(business_plan_review.get("review") or {})
    requirement_brief = dict(business_plan_review.get("requirement_brief") or {})
    try:
        plan_text = call_text_model(
            stage_id="requirement_capture",
            prompt_id=PromptId.BUSINESS_PLAN_REVIEW_REVISE,
            values={
                "requirement_brief": _format_requirement_brief(requirement_brief),
                "current_plan_text": business_plan_review.get("current_plan_text", ""),
                "revision_instruction": review.get("revision_instruction", ""),
                "required_sections": "\n".join(DEFAULT_REFINED_PLAN_SECTIONS),
            },
        )
    except FactoryModelCallError as exc:
        return model_error_patch("requirement_capture", str(exc))
    iteration_count = int(business_plan_review.get("iteration_count") or 0) + 1
    return {
        "business_plan_review": {
            **business_plan_review,
            "current_plan_text": plan_text,
            "iteration_count": iteration_count,
            "review": {},
        }
    }


def _finalize_business_plan(state: FactoryGraphState) -> dict[str, Any]:
    business_plan_review = dict(state.get("business_plan_review") or {})
    plan_text = str(business_plan_review.get("current_plan_text") or "")
    return {
        "current_stage": "requirement_capture",
        "status": "running",
        "business_plan_review": {
            **business_plan_review,
            "status": "approved",
            "final_plan_text": plan_text,
        },
        "refined_plan_text": plan_text,
        "stage_log": [
            {
                "stage_id": "requirement_capture",
                "status": "approved",
                "message": "requirement_capture completed business plan refinement.",
            }
        ],
    }


def _route_after_plan_review(state: FactoryGraphState) -> str:
    business_plan_review = state.get("business_plan_review") or {}
    review = business_plan_review.get("review") or {}
    if review.get("decision") == "revise":
        return "revise_business_plan"
    return "finalize_business_plan"


def _route_after_model_step(state: FactoryGraphState) -> str:
    if state.get("status") == "failed" or state.get("graph_control", {}).get("action") == "end":
        return END
    return "present_business_plan"


def _format_requirement_brief(requirement_brief: dict[str, Any]) -> str:
    lines = [
        f"原始输入：{requirement_brief.get('original_input', '')}",
        f"整理后的需求：{requirement_brief.get('refined_requirement', '')}",
    ]
    assumptions = requirement_brief.get("assumptions") or []
    unresolved_questions = requirement_brief.get("unresolved_questions") or []
    if assumptions:
        lines.append("已知假设：")
        lines.extend(f"- {item}" for item in assumptions)
    if unresolved_questions:
        lines.append("未解决问题：")
        lines.extend(f"- {item}" for item in unresolved_questions)
    return "\n".join(lines)


def _delta_patch(
    final_state: FactoryGraphState,
    *,
    original_stage_log_count: int,
) -> dict[str, Any]:
    keys = [
        "current_stage",
        "status",
        "graph_control",
        "errors",
        "business_plan_review",
        "refined_plan_text",
        "model_activity",
    ]
    patch = {key: final_state[key] for key in keys if key in final_state}
    new_stage_log = final_state.get("stage_log", [])[original_stage_log_count:]
    if new_stage_log:
        patch["stage_log"] = new_stage_log
    return patch
