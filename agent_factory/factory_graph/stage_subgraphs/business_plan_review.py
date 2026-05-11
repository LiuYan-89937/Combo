from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from agent_factory.factory_graph.prompt_context import prompt_context_values
from agent_factory.factory_graph.state import FactoryGraphState
from agent_factory.models import get_main_model, get_main_model_settings
from agent_factory.prompts import PromptId, get_prompt


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
    graph.add_edge("draft_business_plan", "present_business_plan")
    graph.add_conditional_edges(
        "present_business_plan",
        _route_after_plan_review,
        {
            "revise_business_plan": "revise_business_plan",
            "finalize_business_plan": "finalize_business_plan",
        },
    )
    graph.add_edge("revise_business_plan", "present_business_plan")
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
    plan_text = _call_text_model(
        prompt_id=PromptId.BUSINESS_PLAN_REVIEW_DRAFT,
        values={
            "requirement_brief": _format_requirement_brief(requirement_brief),
            "required_sections": "\n".join(DEFAULT_REFINED_PLAN_SECTIONS),
        },
        fallback=_fallback_plan_text(requirement_brief),
    )
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
    plan_text = _call_text_model(
        prompt_id=PromptId.BUSINESS_PLAN_REVIEW_REVISE,
        values={
            "requirement_brief": _format_requirement_brief(requirement_brief),
            "current_plan_text": business_plan_review.get("current_plan_text", ""),
            "revision_instruction": review.get("revision_instruction", ""),
            "required_sections": "\n".join(DEFAULT_REFINED_PLAN_SECTIONS),
        },
        fallback=_fallback_revised_plan_text(
            str(business_plan_review.get("current_plan_text") or ""),
            str(review.get("revision_instruction") or ""),
        ),
    )
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


def _call_text_model(*, prompt_id: PromptId, values: dict[str, Any], fallback: str) -> str:
    model = get_main_model()
    settings = get_main_model_settings()
    if model is None:
        return fallback
    try:
        prompt_value = get_prompt(prompt_id).invoke({**prompt_context_values("requirement_capture"), **values})
        configured_model = model.with_config(tags=["nostream"])
        if settings.max_tokens is not None:
            configured_model = configured_model.bind(max_tokens=settings.max_tokens)
        response = configured_model.invoke(prompt_value)
        content = getattr(response, "content", "")
        if isinstance(content, str):
            return content.strip() or fallback
        return str(content).strip() or fallback
    except Exception:
        return fallback


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


def _fallback_plan_text(requirement_brief: dict[str, Any]) -> str:
    requirement = str(requirement_brief.get("refined_requirement") or "")
    return (
        "【制造目标】\n"
        f"围绕用户需求制造一个 CLI-first 对话式 Agent：{requirement}\n\n"
        "【使用场景】\n"
        "用户通过文本对话提出任务，Agent 根据业务目标提供可执行的帮助。\n\n"
        "【业务行为】\n"
        "Agent 需要理解用户请求、在信息不足时追问，并给出清晰可靠的业务回应。\n\n"
        "【交互方式】\n"
        "以自然语言对话为主，必要时进行确认、追问和结果说明。\n\n"
        "【业务边界】\n"
        "本计划不展开工具方案、资源方案、技术选型或实现设计。\n\n"
        "【成功标准】\n"
        "用户能够通过对话完成核心业务任务，并理解 Agent 的处理结果。\n\n"
        "【后续规划提示】\n"
        "后续阶段需要继续从业务行为出发拆解能力、条件、资源和测试重点。"
    )


def _fallback_revised_plan_text(current_plan_text: str, revision_instruction: str) -> str:
    if not revision_instruction.strip():
        return current_plan_text
    return f"{current_plan_text}\n\n【用户修订意见】\n{revision_instruction.strip()}"


def _delta_patch(
    final_state: FactoryGraphState,
    *,
    original_stage_log_count: int,
) -> dict[str, Any]:
    keys = [
        "current_stage",
        "status",
        "business_plan_review",
        "refined_plan_text",
    ]
    patch = {key: final_state[key] for key in keys if key in final_state}
    new_stage_log = final_state.get("stage_log", [])[original_stage_log_count:]
    if new_stage_log:
        patch["stage_log"] = new_stage_log
    return patch
