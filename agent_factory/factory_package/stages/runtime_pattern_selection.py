from __future__ import annotations

from pathlib import Path
from typing import Any
import json

from agent_factory.factory_package.schemas import (
    RuntimePatternSelectionOutput,
)
from agent_factory.factory_package.model_call import (
    FactoryModelCallError,
    call_structured_model,
    model_error_patch,
)
from agent_factory.factory_package.state import FactoryPackageState
from agent_factory.prompts import (
    PromptId,
    output_json_schema,
)
from agent_factory.runtime_kernel.patterns import PatternCatalogItemSpec, PatternRegistry


def run(state: FactoryPackageState) -> dict:
    catalog = _load_pattern_catalog()
    try:
        selection = _select_runtime_pattern(state, catalog)
    except FactoryModelCallError as exc:
        return model_error_patch("runtime_pattern_selection", str(exc))
    if not _catalog_contains(catalog, selection.selected_pattern_id):
        return model_error_patch(
            "runtime_pattern_selection",
            f"model selected unknown pattern_id: {selection.selected_pattern_id}",
        )
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
    state: FactoryPackageState,
    catalog: list[PatternCatalogItemSpec],
) -> RuntimePatternSelectionOutput:
    return call_structured_model(
        stage_id="runtime_pattern_selection",
        prompt_id=PromptId.RUNTIME_PATTERN_SELECTION,
        output_model=RuntimePatternSelectionOutput,
        values={
            "requirement_brief": _format_requirement_brief(state.get("requirement_brief") or {}),
            "refined_plan_text": state.get("refined_plan_text") or "",
            "pattern_catalog": _format_pattern_catalog(catalog),
            "output_json_schema": output_json_schema(RuntimePatternSelectionOutput),
        },
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
