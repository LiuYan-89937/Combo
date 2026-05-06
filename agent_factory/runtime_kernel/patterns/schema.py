from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


PatternKind = Literal["main", "subgraph"]
NodeType = Literal["reserved", "cognitive", "operational", "governance", "terminal", "sub_graph"]
StateMode = Literal["shared", "isolated"]
WrapperPhase = Literal["before", "after", "on_error"]


class PatternNodeWrapperSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    phase: WrapperPhase
    order: int = 0
    config: dict[str, Any] = Field(default_factory=dict)


class PatternNodeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: NodeType
    impl: str
    pattern_ref: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    wrappers: list[PatternNodeWrapperSpec] = Field(default_factory=list)


class PatternEdgeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_: str = Field(alias="from")
    to: str
    when: str


class PatternTerminationSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success_nodes: list[str] = Field(default_factory=list)
    failure_nodes: list[str] = Field(default_factory=list)


class PatternConstraintsSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed_node_types: list[NodeType] = Field(default_factory=list)
    required_capabilities: list[str] = Field(default_factory=list)


class PatternIOContractSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    readable_sections: list[str] = Field(default_factory=list)
    writable_sections: list[str] = Field(default_factory=list)


class GraphPatternSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pattern_id: str
    kind: PatternKind
    embeddable: bool
    version: int
    name: str
    description: str
    entry_node: str
    nodes: list[PatternNodeSpec] = Field(default_factory=list)
    edges: list[PatternEdgeSpec] = Field(default_factory=list)
    interrupt_points: list[str] = Field(default_factory=list)
    termination: PatternTerminationSpec
    constraints: PatternConstraintsSpec = Field(default_factory=PatternConstraintsSpec)
    input_contract: PatternIOContractSpec = Field(default_factory=PatternIOContractSpec)
    output_contract: PatternIOContractSpec = Field(default_factory=PatternIOContractSpec)
    exit_routes: list[str] = Field(default_factory=list)
    state_mode: StateMode = "shared"
