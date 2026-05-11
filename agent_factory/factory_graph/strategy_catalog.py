from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from agent_factory.factory_graph.schemas import FactoryStrategyKind, FactoryStrategyPhase


StrategyImplementationStatus = Literal["implemented", "requires_generation"]


class FactoryStrategyCatalogItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy_id: str
    name: str
    kind: FactoryStrategyKind
    phase: FactoryStrategyPhase
    description: str
    applies_to_node_types: list[str] = Field(default_factory=list)
    reads: list[str] = Field(default_factory=list)
    writes: list[str] = Field(default_factory=list)
    config_schema: dict[str, Any] = Field(default_factory=dict)
    implementation_status: StrategyImplementationStatus = "implemented"


class FactoryStrategyCatalog:
    def __init__(self, items: list[FactoryStrategyCatalogItem]) -> None:
        self._items = {item.strategy_id: item for item in items}

    def list_items(self) -> list[FactoryStrategyCatalogItem]:
        return [self._items[strategy_id] for strategy_id in sorted(self._items)]

    def has(self, strategy_id: str) -> bool:
        return strategy_id in self._items

    def get(self, strategy_id: str) -> FactoryStrategyCatalogItem | None:
        return self._items.get(strategy_id)

    def as_prompt_payload(self) -> list[dict[str, Any]]:
        return [item.model_dump(mode="json") for item in self.list_items()]


DEFAULT_FACTORY_STRATEGY_CATALOG = FactoryStrategyCatalog(
    [
        FactoryStrategyCatalogItem(
            strategy_id="context.model.reasoning_brief",
            name="模型推理上下文",
            kind="context",
            phase="before",
            description="为认知节点准备当前需求、图行为计划、必要会话摘要和可见运行配置。",
            applies_to_node_types=["cognitive"],
            reads=["requirement", "business_plan", "conversation", "runtime_config"],
            writes=["node_context"],
            config_schema={
                "type": "object",
                "properties": {
                    "include_memory_summary": {"type": "boolean"},
                    "include_runtime_config": {"type": "boolean"},
                },
                "additionalProperties": False,
            },
        ),
        FactoryStrategyCatalogItem(
            strategy_id="context.model.final_response",
            name="最终回答上下文",
            kind="context",
            phase="before",
            description="为最终回答节点准备任务结论、工具观察、引用要求和输出格式约束。",
            applies_to_node_types=["cognitive"],
            reads=["conversation", "tool_observations", "output_contract"],
            writes=["node_context"],
            config_schema={
                "type": "object",
                "properties": {
                    "include_citations": {"type": "boolean"},
                    "include_tool_observations": {"type": "boolean"},
                },
                "additionalProperties": False,
            },
        ),
        FactoryStrategyCatalogItem(
            strategy_id="context.tool.execution_scope",
            name="工具执行上下文",
            kind="context",
            phase="before",
            description="为操作节点提供工具调用所需的最小状态、审批结果和节点可见能力引用。",
            applies_to_node_types=["operational"],
            reads=["tool_visibility", "approval", "runtime_config"],
            writes=["node_context"],
            config_schema={
                "type": "object",
                "properties": {
                    "include_approval_payload": {"type": "boolean"},
                    "include_tool_capability_refs": {"type": "boolean"},
                },
                "additionalProperties": False,
            },
        ),
        FactoryStrategyCatalogItem(
            strategy_id="memory.session.read_recent",
            name="最近会话记忆读取",
            kind="memory",
            phase="before",
            description="在节点执行业务前读取最近会话记忆，供模型判断或回答使用。",
            applies_to_node_types=["cognitive"],
            reads=["memory.session"],
            writes=["node_context"],
            config_schema={
                "type": "object",
                "properties": {"limit": {"type": "integer", "minimum": 0}},
                "additionalProperties": False,
            },
        ),
        FactoryStrategyCatalogItem(
            strategy_id="memory.session.write_turn_summary",
            name="本轮摘要写入",
            kind="memory",
            phase="after",
            description="在关键输出节点后写入本轮输入、关键结论和后续可复用摘要。",
            applies_to_node_types=["cognitive"],
            reads=["conversation", "node_output"],
            writes=["memory.session"],
            config_schema={
                "type": "object",
                "properties": {"max_chars": {"type": "integer", "minimum": 1}},
                "additionalProperties": False,
            },
        ),
        FactoryStrategyCatalogItem(
            strategy_id="policy.tool.human_approval",
            name="工具人工审批",
            kind="policy",
            phase="before",
            description="在高风险或外部副作用工具执行前进入人工审批中断。",
            applies_to_node_types=["operational"],
            reads=["tool_request", "tool_policy"],
            writes=["approval_request"],
            config_schema={
                "type": "object",
                "properties": {
                    "approval_required": {"type": "boolean"},
                    "risk_level": {"type": "string"},
                },
                "additionalProperties": False,
            },
        ),
        FactoryStrategyCatalogItem(
            strategy_id="policy.output.contract_check",
            name="输出契约检查",
            kind="policy",
            phase="after",
            description="在最终输出后检查格式、引用、免责声明或业务契约要求。",
            applies_to_node_types=["cognitive"],
            reads=["node_output", "output_contract"],
            writes=["policy_result"],
            config_schema={
                "type": "object",
                "properties": {
                    "citations_required": {"type": "boolean"},
                    "format": {"type": "string"},
                },
                "additionalProperties": False,
            },
        ),
        FactoryStrategyCatalogItem(
            strategy_id="tool.visibility.none",
            name="无工具可见性",
            kind="tool_visibility",
            phase="before",
            description="该节点不暴露任何工具能力。",
            applies_to_node_types=["cognitive", "operational", "control"],
            reads=["tool_capabilities"],
            writes=["tool_visibility"],
            config_schema={"type": "object", "properties": {}, "additionalProperties": False},
        ),
        FactoryStrategyCatalogItem(
            strategy_id="tool.visibility.node_scoped",
            name="节点级工具可见性",
            kind="tool_visibility",
            phase="before",
            description="只向当前节点暴露装配计划允许的工具能力引用。",
            applies_to_node_types=["cognitive", "operational"],
            reads=["tool_capabilities", "node_strategy"],
            writes=["tool_visibility"],
            config_schema={
                "type": "object",
                "properties": {
                    "allowed_tool_capability_refs": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "approval_required": {"type": "boolean"},
                },
                "additionalProperties": False,
            },
        ),
    ]
)
