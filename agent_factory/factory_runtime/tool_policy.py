from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from agent_factory.factory_runtime.tools import FactoryTool, FactoryToolRegistry


class FactoryToolPolicyEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_id: str
    mode: Literal["direct_internal", "model_only", "proposal_or_future"]
    description: str


class FactoryToolPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entries: list[FactoryToolPolicyEntry]

    @classmethod
    def from_registry(cls, registry: FactoryToolRegistry) -> "FactoryToolPolicy":
        return cls(entries=[_entry_for(tool) for tool in registry.list_tools()])

    def to_prompt_text(self) -> str:
        lines = []
        for entry in self.entries:
            lines.append(f"- {entry.tool_id}: {entry.mode}. {entry.description}")
        return "\n".join(lines)


def _entry_for(tool: FactoryTool) -> FactoryToolPolicyEntry:
    direct = {
        "package.write_primitives",
        "package.validate",
        "filesystem.safe_write",
        "trace.record",
        "memory.append",
        "factory.web_search",
    }
    if tool.id == "model.generate_structured":
        mode = "model_only"
    elif tool.id in direct:
        mode = "direct_internal"
    else:
        mode = "proposal_or_future"
    return FactoryToolPolicyEntry(tool_id=tool.id, mode=mode, description=tool.description)
