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
    structured = classifier.with_structured_output(
        CreateAgentTaskAnalysis,
        method="json_mode",
        include_raw=True,
    ).with_config(
        tags=["nostream"]
    )
    messages = _task_analysis_messages(user_input=user_input, candidates=candidates)
    max_attempts = 3
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        result = structured.invoke(messages)
        try:
            analysis = _parse_task_analysis_result(result)
            break
        except Exception as exc:
            last_error = exc
            if attempt >= max_attempts:
                raise RuntimeError(f"create-agent task analysis failed schema validation: {exc}") from exc
            messages = [
                *messages,
                HumanMessage(
                    content=_task_analysis_repair_prompt(
                        result=result,
                        error=exc,
                        attempt=attempt,
                        max_attempts=max_attempts,
                    )
                ),
            ]
    else:
        raise RuntimeError(f"create-agent task analysis failed schema validation: {last_error}")
    if analysis.selected_pattern_id not in SUPPORTED_CREATE_AGENT_PATTERNS:
        raise ValueError(f"unsupported selected_pattern_id from task analysis: {analysis.selected_pattern_id}")
    selection_reason = analysis.selection_reason or analysis.reasoning
    return analysis.model_copy(
        update={
            "selection_reason": selection_reason,
            "available_patterns": [item["pattern_id"] for item in candidates],
        }
    )


def _task_analysis_messages(*, user_input: str, candidates: list[dict[str, Any]]) -> list[Any]:
    return [
        SystemMessage(
            content=(
                "Analyze one /create-agent manufacturing request before package scaffolding. "
                "Return JSON only using the CreateAgentTaskAnalysis schema. "
                "The exact schema is included below; follow it as the source of truth. "
                "In particular, model_requirements must be an array of model requirement objects, "
                "not an object keyed by model type. model_tool_requirements must be a separate array "
                "of auxiliary model tool requirement objects, not nested inside model_requirements. "
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
                "When reusable SkillHub skills may reduce custom package-tool authoring, note the intended SkillHub search query "
                "in manufacturing_notes. Do not invent concrete SkillHub skill ids before search results exist. "
                "Do not write concrete plan steps; this is only manufacturing task analysis.\n\n"
                "Minimal valid shape example:\n"
                "{"
                "\"selected_pattern_id\":\"react_agent\","
                "\"model_requirements\":[{\"role\":\"main\",\"purpose\":\"Primary chat model for the produced agent.\","
                "\"kind\":\"chat\",\"input_modalities\":[\"text\"],\"output_modalities\":[\"text\"]}],"
                "\"model_tool_requirements\":[{\"tool_id\":\"generate_image\",\"capability\":\"image_output\","
                "\"purpose\":\"Generate images when the produced agent needs visual assets.\"}]"
                "}\n\n"
                f"CreateAgentTaskAnalysis JSON schema:\n{_task_analysis_schema_prompt()}"
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


def _parse_task_analysis_result(result: Any) -> CreateAgentTaskAnalysis:
    if isinstance(result, CreateAgentTaskAnalysis):
        return result
    if isinstance(result, dict) and {"raw", "parsed", "parsing_error"}.intersection(result):
        parsing_error = result.get("parsing_error")
        if parsing_error is not None:
            raise parsing_error
        parsed = result.get("parsed")
        if parsed is None:
            raise ValueError("structured task analysis returned no parsed payload")
        if isinstance(parsed, CreateAgentTaskAnalysis):
            return parsed
        return CreateAgentTaskAnalysis.model_validate(parsed)
    return CreateAgentTaskAnalysis.model_validate(result)


def _task_analysis_repair_prompt(
    *,
    result: Any,
    error: Exception,
    attempt: int,
    max_attempts: int,
) -> str:
    return (
        "The previous CreateAgentTaskAnalysis JSON failed Pydantic schema validation.\n"
        "Rewrite the full answer as JSON only. Do not explain the error.\n"
        "Do not preserve invalid object shapes. Obey list/object field types exactly.\n"
        f"Validation error from attempt {attempt}/{max_attempts}:\n{type(error).__name__}: {error}\n\n"
        f"Previous raw output:\n{_raw_result_text(result)}\n\n"
        f"CreateAgentTaskAnalysis JSON schema:\n{_task_analysis_schema_prompt()}"
    )


def _raw_result_text(result: Any) -> str:
    raw = result.get("raw") if isinstance(result, dict) else result
    content = getattr(raw, "content", raw)
    if isinstance(content, str):
        return content
    try:
        return json.dumps(content, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(content)


def _task_analysis_schema_prompt() -> str:
    return json.dumps(CreateAgentTaskAnalysis.model_json_schema(), ensure_ascii=False, sort_keys=True)


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
