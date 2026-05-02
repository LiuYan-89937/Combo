from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class FactoryContextPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    include_schema: bool = True
    include_factory_rules: bool = True
    include_workspace_summary: bool = True
    include_tool_summary: bool = True
    include_recent_memory: bool = True
    memory_limit: int = Field(default=5, ge=0)
    include_agent_instance_memory: bool = False
    include_secrets: bool = False
