from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from agent_factory.create_agent.models import CreateAgentTaskAnalysis
from agent_factory.models import get_main_model, get_task_model
from agent_factory.runtime_kernel.patterns.registry import PatternRegistry


SUPPORTED_CREATE_AGENT_PATTERNS = ("react_agent", "plan_and_execute")


def analyze_create_agent_task(*, user_input: str, model: Any | None = None) -> CreateAgentTaskAnalysis:
    candidates = _pattern_candidates()
    classifier = model or get_task_model() or get_main_model()
    if classifier is None:
        return _fallback_analysis(
            user_input=user_input,
            candidates=candidates,
            reason="No task or main model is configured; defaulting to react_agent.",
        )
    try:
        structured = classifier.with_structured_output(CreateAgentTaskAnalysis, method="json_mode")
        result = structured.invoke(
            [
                SystemMessage(
                    content=(
                        "Analyze one /create-agent manufacturing request before package scaffolding. "
                        "Return JSON only using the CreateAgentTaskAnalysis schema. "
                        "Choose selected_pattern_id from the available_patterns list only. "
                        "Use the pattern catalog semantics, not business-specific keyword rules. "
                        "Select plan_and_execute when the produced Agent should maintain and revise a dynamic per-run plan "
                        "as part of normal runtime behavior. Select react_agent when a direct answer/tool loop is enough. "
                        "Do not write concrete plan steps; this is only manufacturing task analysis."
                    )
                ),
                HumanMessage(
                    content=json.dumps(
                        {
                            "user_request": user_input,
                            "available_patterns": candidates,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                ),
            ]
        )
        analysis = result if isinstance(result, CreateAgentTaskAnalysis) else CreateAgentTaskAnalysis.model_validate(result)
        selected = analysis.selected_pattern_id if analysis.selected_pattern_id in SUPPORTED_CREATE_AGENT_PATTERNS else "react_agent"
        return analysis.model_copy(
            update={
                "selected_pattern_id": selected,
                "available_patterns": [item["pattern_id"] for item in candidates],
            }
        )
    except Exception as exc:
        return _fallback_analysis(
            user_input=user_input,
            candidates=candidates,
            reason=f"Task analysis failed: {type(exc).__name__}: {exc}. Defaulting to react_agent.",
        )


def _pattern_candidates() -> list[dict[str, Any]]:
    registry = PatternRegistry(
        builtins_dir=Path(__file__).resolve().parents[1] / "runtime_kernel" / "patterns" / "builtins"
    )
    candidates: list[dict[str, Any]] = []
    for pattern_id in SUPPORTED_CREATE_AGENT_PATTERNS:
        pattern = registry.get(pattern_id)
        candidates.append(
            {
                "pattern_id": pattern.pattern_id,
                "name": pattern.name,
                "description": pattern.description,
                "metadata": pattern.metadata,
                "nodes": [{"id": node.id, "type": node.type, "impl": node.impl} for node in pattern.nodes],
            }
        )
    return candidates


def _fallback_analysis(
    *,
    user_input: str,
    candidates: list[dict[str, Any]],
    reason: str,
) -> CreateAgentTaskAnalysis:
    summary = " ".join(str(user_input or "").split())[:240]
    return CreateAgentTaskAnalysis(
        intent_summary=summary,
        capability_goals=[],
        interaction_style="",
        requires_dynamic_plan=False,
        selected_pattern_id="react_agent",
        selection_reason=reason,
        manufacturing_notes=[reason],
        available_patterns=[str(item.get("pattern_id") or "") for item in candidates],
    )
