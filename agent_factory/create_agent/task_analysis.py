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
        raise RuntimeError("create-agent task analysis requires a configured task or main model")
    structured = classifier.with_structured_output(CreateAgentTaskAnalysis, method="json_mode").with_config(
        tags=["nostream"]
    )
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
                    "Also infer model_requirements for the produced AgentPackage. Include at least a main chat model "
                    "requirement, and add task/compression requirements only when the produced agent needs "
                    "a distinct role. Requirements describe capabilities, not provider names or secrets. "
                    "When the produced agent needs image or audio capabilities that can be served by auxiliary models, "
                    "infer model_tool_requirements with stable snake_case tool ids such as image_understand, "
                    "generate_image, edit_image, audio_transcribe, or audio_generate. Use image_output for text-to-image "
                    "generation and image_edit when the task must transform or edit referenced images. These auxiliary models are exposed as "
                    "system tools to the runtime executor, not as native main-model capabilities. "
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
    if analysis.selected_pattern_id not in SUPPORTED_CREATE_AGENT_PATTERNS:
        raise ValueError(f"unsupported selected_pattern_id from task analysis: {analysis.selected_pattern_id}")
    selection_reason = analysis.selection_reason or analysis.reasoning
    return analysis.model_copy(
        update={
            "selection_reason": selection_reason,
            "available_patterns": [item["pattern_id"] for item in candidates],
        }
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
                "metadata": pattern.metadata.model_dump(mode="json"),
                "nodes": [{"id": node.id, "type": node.type, "impl": node.impl} for node in pattern.nodes],
            }
        )
    return candidates
