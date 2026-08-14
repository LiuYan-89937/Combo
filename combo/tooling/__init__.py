"""Tool execution primitives used by published capability revisions."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any


_EXPORT_MODULES: dict[str, str] = {
    "ModelToolView": "combo.tooling.spec",
    "ToolCompiler": "combo.tooling.compiler",
    "ToolEventPayload": "combo.tooling.spec",
    "ToolExecutionGateway": "combo.tooling.gateway",
    "ToolObservation": "combo.tooling.spec",
    "ToolRiskEvaluatorConfig": "combo.tooling.spec",
    "ToolRiskResult": "combo.tooling.spec",
    "ToolSpec": "combo.tooling.spec",
    "compile_json_schema": "combo.tooling.schema_compiler",
}


def __getattr__(name: str) -> Any:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(name)
    value = getattr(importlib.import_module(module_name), name)
    globals()[name] = value
    return value


if TYPE_CHECKING:
    from combo.tooling.compiler import ToolCompiler
    from combo.tooling.gateway import ToolExecutionGateway
    from combo.tooling.schema_compiler import compile_json_schema
    from combo.tooling.spec import (
        ModelToolView,
        ToolEventPayload,
        ToolObservation,
        ToolRiskEvaluatorConfig,
        ToolRiskResult,
        ToolSpec,
    )


__all__ = sorted(_EXPORT_MODULES)
