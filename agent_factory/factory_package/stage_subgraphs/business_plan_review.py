from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from agent_factory.factory_package.state import FactoryPackageState
from agent_factory.factory_package.model_call import (
    FactoryModelCallError,
    call_text_model,
    model_error_patch,
)
from agent_factory.prompts import PromptId


DEFAULT_REFINED_PLAN_SECTIONS: tuple[str, ...] = (
    "【制造目标】",
    "【第一版核心行为】",
    "【交互与输出】",
    "【动作边界】",
    "【业务资源边界】",
    "【成功标准】",
    "【后续待决】",
)


def build_business_plan_review_subgraph():
    graph = StateGraph(FactoryPackageState)
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


def run_business_plan_review_subgraph(state: FactoryPackageState) -> dict[str, Any]:
    original_stage_log_count = len(state.get("stage_log", []))
    final_state = build_business_plan_review_subgraph().invoke(state)
    return _delta_patch(final_state, original_stage_log_count=original_stage_log_count)


def _load_requirement_brief(state: FactoryPackageState) -> dict[str, Any]:
    requirement_brief = dict(state.get("requirement_brief") or {})
    return {
        "current_stage": "requirement_capture",
        "business_plan_review": {
            "requirement_brief": requirement_brief,
            "iteration_count": 0,
        },
    }


def _draft_business_plan(state: FactoryPackageState) -> dict[str, Any]:
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


def _present_business_plan(state: FactoryPackageState) -> dict[str, Any]:
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


def _revise_business_plan(state: FactoryPackageState) -> dict[str, Any]:
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


def _finalize_business_plan(state: FactoryPackageState) -> dict[str, Any]:
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


def _route_after_plan_review(state: FactoryPackageState) -> str:
    business_plan_review = state.get("business_plan_review") or {}
    review = business_plan_review.get("review") or {}
    if review.get("decision") == "revise":
        return "revise_business_plan"
    return "finalize_business_plan"


def _route_after_model_step(state: FactoryPackageState) -> str:
    if state.get("status") == "failed" or state.get("graph_control", {}).get("action") == "end":
        return END
    return "present_business_plan"


def _format_requirement_brief(requirement_brief: dict[str, Any]) -> str:
    lines = [
        f"版本：{requirement_brief.get('version', 'requirement_brief.v1')}",
        f"状态：{requirement_brief.get('status', '')}",
        f"置信度：{requirement_brief.get('confidence', '')}",
        f"原始输入：{requirement_brief.get('original_input', '')}",
    ]
    clarity = requirement_brief.get("clarity") or {}
    if isinstance(clarity, dict):
        reason = str(clarity.get("reason") or "").strip()
        missing_decisions = clarity.get("missing_decisions") or []
        if reason:
            lines.append(f"清晰度判断：{reason}")
        if missing_decisions:
            lines.append("仍需明确的业务决策：")
            lines.extend(f"- {item}" for item in missing_decisions if str(item).strip())
    frame = requirement_brief.get("requirement_frame") or {}
    if isinstance(frame, dict):
        frame_sections = [
            ("目标", frame.get("goal")),
            ("主要用户", frame.get("primary_users")),
            ("主要场景", frame.get("primary_scenarios")),
            ("行为模式", frame.get("behavior_mode")),
            ("动作边界", frame.get("action_boundary")),
            ("业务资源范围", frame.get("resource_scope")),
            ("输出期望", frame.get("output_expectation")),
            ("成功信号", frame.get("success_signal")),
            ("不做范围", frame.get("out_of_scope")),
            ("人工确认期望", frame.get("human_approval_expectations")),
            ("已知假设", frame.get("assumptions")),
            ("未知/待确认", frame.get("unknowns")),
        ]
        lines.append("结构化需求画像：")
        for label, value in frame_sections:
            if value:
                lines.append(f"- {label}：{_format_value(value)}")
    return "\n".join(lines)


def _format_value(value: Any) -> str:
    if isinstance(value, list):
        return "；".join(str(item) for item in value if str(item).strip())
    return str(value)


def _delta_patch(
    final_state: FactoryPackageState,
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
