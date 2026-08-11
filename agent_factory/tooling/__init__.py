"""Tool execution primitives used by published capability revisions."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any


_EXPORT_MODULES: dict[str, str] = {
    "ModelToolView": "agent_factory.tooling.spec",
    "ToolCompiler": "agent_factory.tooling.compiler",
    "ToolEventPayload": "agent_factory.tooling.spec",
    "ToolExecutionGateway": "agent_factory.tooling.gateway",
    "ToolObservation": "agent_factory.tooling.spec",
    "ToolRiskEvaluatorConfig": "agent_factory.tooling.spec",
    "ToolRiskResult": "agent_factory.tooling.spec",
    "ToolSpec": "agent_factory.tooling.spec",
    "compile_json_schema": "agent_factory.tooling.schema_compiler",
}


def __getattr__(name: str) -> Any:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(name)
    value = getattr(importlib.import_module(module_name), name)
    globals()[name] = value
    return value


if TYPE_CHECKING:
    from agent_factory.tooling.compiler import ToolCompiler
    from agent_factory.tooling.gateway import ToolExecutionGateway
    from agent_factory.tooling.schema_compiler import compile_json_schema
    from agent_factory.tooling.spec import (
        ModelToolView,
        ToolEventPayload,
        ToolObservation,
        ToolRiskEvaluatorConfig,
        ToolRiskResult,
        ToolSpec,
    )


__all__ = sorted(_EXPORT_MODULES)
