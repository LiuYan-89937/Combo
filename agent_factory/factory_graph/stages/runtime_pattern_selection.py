from __future__ import annotations

from pathlib import Path
from typing import Any
import json

from agent_factory.factory_graph.state import FactoryGraphState
from agent_factory.models import get_main_model, get_main_model_settings
from agent_factory.prompts import (
    PromptId,
    RuntimePatternSelectionOutput,
    get_prompt,
    output_json_schema,
)
from agent_factory.runtime_kernel.patterns import PatternCatalogItemSpec, PatternRegistry


def run(state: FactoryGraphState) -> dict:
    catalog = _load_pattern_catalog()
    selection = _select_runtime_pattern(state, catalog)
    selected_item = _catalog_item_by_id(catalog, selection.selected_pattern_id)
    payload = {
        **selection.model_dump(mode="json"),
        "selected_pattern_name": selected_item.name,
        "selected_pattern_description": selected_item.description,
        "available_pattern_ids": [item.pattern_id for item in catalog],
    }
    return {
        "current_stage": "runtime_pattern_selection",
        "status": "running",
        "runtime_pattern_selection": payload,
        "runtime_pattern_summary": (
            f"已选择 {selection.selected_pattern_id}，因为{selection.fit_summary}"
        ),
        "stage_log": [
            {
                "stage_id": "runtime_pattern_selection",
                "status": "selected",
                "message": f"runtime_pattern_selection selected {selection.selected_pattern_id}.",
            }
        ],
    }


def _load_pattern_catalog() -> list[PatternCatalogItemSpec]:
    builtins_dir = Path(__file__).resolve().parents[2] / "runtime_kernel" / "patterns" / "builtins"
    registry = PatternRegistry(builtins_dir=builtins_dir)
    return registry.list_pattern_catalog(include_embeddable=False)


def _select_runtime_pattern(
    state: FactoryGraphState,
    catalog: list[PatternCatalogItemSpec],
) -> RuntimePatternSelectionOutput:
    fallback = _default_selection(catalog)
    model = get_main_model()
    settings = get_main_model_settings()
    if model is None:
        return fallback
    try:
        prompt_value = get_prompt(PromptId.RUNTIME_PATTERN_SELECTION).invoke(
            {
                "requirement_brief": _format_requirement_brief(state.get("requirement_brief") or {}),
                "refined_plan_text": state.get("refined_plan_text") or "",
                "pattern_catalog": _format_pattern_catalog(catalog),
                "output_json_schema": output_json_schema(RuntimePatternSelectionOutput),
            }
        )
        structured_model = model.with_structured_output(
            RuntimePatternSelectionOutput,
            method="json_mode",
        ).with_config(tags=["nostream"])
        if settings.max_tokens is not None:
            structured_model = structured_model.bind(max_tokens=settings.max_tokens)
        selection = structured_model.invoke(prompt_value)
    except Exception:
        return fallback
    if _catalog_contains(catalog, selection.selected_pattern_id):
        return selection
    return RuntimePatternSelectionOutput(
        selected_pattern_id=fallback.selected_pattern_id,
        selection_reason=fallback.selection_reason,
        fit_summary=fallback.fit_summary,
        alternatives=fallback.alternatives,
        assumptions=[
            *selection.assumptions,
            "model selected a pattern_id outside catalog; selected default runtime pattern from catalog",
        ],
        open_questions=selection.open_questions,
    )


def _default_selection(catalog: list[PatternCatalogItemSpec]) -> RuntimePatternSelectionOutput:
    selected = next((item for item in catalog if item.pattern_id == "react_agent"), None)
    selected = selected or catalog[0]
    alternatives = [
        {
            "pattern_id": item.pattern_id,
            "reason": item.description,
            "tradeoff": "fallback alternative from catalog",
        }
        for item in catalog
        if item.pattern_id != selected.pattern_id
    ]
    return RuntimePatternSelectionOutput(
        selected_pattern_id=selected.pattern_id,
        selection_reason="model unavailable or invalid; selected default runtime pattern from catalog",
        fit_summary=selected.metadata.summary or selected.description,
        alternatives=alternatives,
        assumptions=["model unavailable or invalid; selected default runtime pattern from catalog"],
        open_questions=[],
    )


def _format_requirement_brief(requirement_brief: dict[str, Any]) -> str:
    return json.dumps(requirement_brief, ensure_ascii=False, indent=2)


def _format_pattern_catalog(catalog: list[PatternCatalogItemSpec]) -> str:
    return json.dumps(
        [item.model_dump(mode="json") for item in catalog],
        ensure_ascii=False,
        indent=2,
    )


def _catalog_contains(catalog: list[PatternCatalogItemSpec], pattern_id: str) -> bool:
    return any(item.pattern_id == pattern_id for item in catalog)


def _catalog_item_by_id(
    catalog: list[PatternCatalogItemSpec],
    pattern_id: str,
) -> PatternCatalogItemSpec:
    for item in catalog:
        if item.pattern_id == pattern_id:
            return item
    return catalog[0]
