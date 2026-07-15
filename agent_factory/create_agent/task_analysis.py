from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from agent_factory.create_agent.models import CreateAgentTaskAnalysis
from agent_factory.models import create_control_plane_chat_model
from agent_factory.runtime_kernel.patterns.registry import PatternRegistry


SUPPORTED_CREATE_AGENT_PATTERNS = ("react_agent", "plan_and_execute")


def analyze_create_agent_task(*, user_input: str, model: Any | None = None) -> CreateAgentTaskAnalysis:
    candidates = _pattern_candidates()
    classifier = model or create_control_plane_chat_model()
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
                "You are selecting the runtime orchestration pattern for the produced AgentPackage, "
                "not judging whether the user request is simple or complex. "
                "Choose react_agent when the produced Agent is suited to complete tasks through conversational "
                "reasoning, tool calls, tool observations, continued reasoning, and a final answer or artifact. "
                "react_agent is suitable when each user request can be treated as a relatively independent task, "
                "the Agent can dynamically choose tools from the current context, tool paths may vary by request, "
                "intermediate plans stay inside model reasoning or ordinary assistant text, users mainly care about "
                "the final answer/files/reports/images/code/artifacts, failures can be handled by continuing from "
                "tool observations, and the UI only needs to show messages, tool calls, artifacts, and runtime status. "
                "Choose plan_and_execute when the produced Agent is suited to complete tasks through an explicit "
                "plan, stepwise execution, state tracking, and plan revision. plan_and_execute is suitable when the "
                "Agent needs to create a visible runtime_plan, execution depends on structured steps rather than "
                "conversation history alone, steps may carry objectives/status/acceptance criteria/evidence/deliverables, "
                "execution may update/insert/skip/reorder/resume steps, users may inspect/interrupt/modify/continue "
                "the active plan, the UI or runtime must show plan progress as structured state instead of assistant "
                "text only, the Agent must distinguish casual messages from an active main workflow, and the final "
                "answer depends on plan state, step results, and collected evidence. "
                "Do not choose a pattern directly from task length, number of tools, web access, or file/artifact generation. "
                "The key question is whether the Agent's plan must be visible, durable, recoverable, and actively updated "
                "as runtime state. If the plan is only internal reasoning or ordinary text, choose react_agent. If the plan "
                "is a runtime object continuously read and written by the executor, choose plan_and_execute. "
                "Set requires_dynamic_plan to true only when selected_pattern_id is plan_and_execute; set it false for react_agent. "
                "Also infer model_requirements for the produced AgentPackage. Include at least a main chat model "
                "requirement, and add task/compression requirements only when the produced agent needs "
                "a distinct role. Requirements describe capabilities, not provider names or secrets. "
                "When the produced agent needs local image or audio understanding, infer model_tool_requirements "
                "with stable snake_case tool ids and the image_input or audio_input capability. The competition "
                "runtime does not expose cloud image or audio generation models. "
                "When reusable SkillHub skills may reduce custom package-tool authoring, note intended SkillHub search queries "
                "in manufacturing_notes. Each query must contain 1 to 3 short keywords, not a full requirement sentence "
                "or a pile of mixed synonyms. Do not invent concrete SkillHub skill ids before search results exist. "
                "Do not write concrete plan steps; this is only manufacturing task analysis.\n\n"
                "Minimal valid shape example:\n"
                "{"
                "\"selected_pattern_id\":\"react_agent\","
                "\"model_requirements\":[{\"role\":\"main\",\"purpose\":\"Primary chat model for the produced agent.\","
                "\"kind\":\"chat\",\"input_modalities\":[\"text\"],\"output_modalities\":[\"text\"]}],"
                "\"model_tool_requirements\":[]"
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
