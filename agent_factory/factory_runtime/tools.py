from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class FactoryTool(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    description: str
    category: Literal["model", "package", "filesystem", "trace", "memory"]
    enabled: bool = True


class FactoryToolRegistry:
    def __init__(self, tools: list[FactoryTool] | None = None) -> None:
        self._tools = {tool.id: tool for tool in (tools or self.default_tools())}

    @staticmethod
    def default_tools() -> list[FactoryTool]:
        return [
            FactoryTool(
                id="model.generate_structured",
                description="Generate structured JSON through ModelService.",
                category="model",
            ),
            FactoryTool(
                id="package.write_primitives",
                description="Write AgentPackagePrimitives as YAML files.",
                category="package",
            ),
            FactoryTool(
                id="package.validate",
                description="Validate AgentPackage primitives.",
                category="package",
            ),
            FactoryTool(
                id="filesystem.safe_write",
                description="Write files inside approved Factory workspace boundaries.",
                category="filesystem",
            ),
            FactoryTool(
                id="trace.record",
                description="Append Factory events to the trace store.",
                category="trace",
            ),
            FactoryTool(
                id="memory.append",
                description="Append Factory-only memory records.",
                category="memory",
            ),
        ]

    def list_tools(self) -> list[FactoryTool]:
        return list(self._tools.values())

    def get(self, tool_id: str) -> FactoryTool | None:
        return self._tools.get(tool_id)
