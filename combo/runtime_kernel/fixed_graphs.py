from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from langgraph.graph import END, StateGraph

from combo.runtime_kernel.services import RuntimeServices
from combo.runtime_kernel.fixed_runner import make_fixed_runner
from combo.runtime_kernel.model_operations import ModelOperationService
from combo.runtime_kernel.nodes.base import NodeImplementation
from combo.runtime_kernel.nodes.standard import (
    CognitiveAnswerNode,
    FinalizeNode,
    IngressNode,
    OperationalToolCallNode,
    TerminalCommitNode,
)
from combo.runtime_kernel.state import RuntimeGraphState, RuntimeState


FixedGraphStrategy = Literal["react", "plan_and_execute"]


@dataclass(frozen=True, slots=True)
class FixedNode:
    node_id: str
    impl: str


@dataclass(frozen=True, slots=True)
class FixedEdge:
    source: str
    target: str
    condition: str


@dataclass(frozen=True, slots=True)
class FixedTopology:
    strategy: FixedGraphStrategy
    entry_node: str
    nodes: tuple[FixedNode, ...]
    edges: tuple[FixedEdge, ...]
    success_nodes: frozenset[str]
    visible_model_nodes: frozenset[str]

    def next_node(self, source: str, decision: str | None) -> tuple[str, str] | None:
        fallback: str | None = None
        for edge in self.edges:
            if edge.source != source:
                continue
            if edge.condition == "always":
                fallback = edge.target
            elif decision == edge.condition:
                return edge.condition, edge.target
        return ("always", fallback) if fallback is not None else None


@dataclass(frozen=True, slots=True)
class CompiledRuntimeGraph:
    strategy: FixedGraphStrategy
    graph_app: Any
    services: RuntimeServices
    node_runners: dict[str, Any]


def build_fixed_runtime_graph(
    strategy: FixedGraphStrategy,
    *,
    services: RuntimeServices,
) -> CompiledRuntimeGraph:
    if not isinstance(services.model_operation_service, ModelOperationService):
        raise TypeError("fixed runtime graphs require the snapshot-bound ModelOperationService")
    topology = _topology(strategy)
    implementations = _node_implementations()
    node_runners: dict[str, Any] = {}
    for node in topology.nodes:
        implementation = implementations.get(node.impl)
        if implementation is None:
            raise ValueError(f"fixed graph references unknown node implementation: {node.impl}")
        node_runners[node.node_id] = make_fixed_runner(
            node_id=node.node_id,
            implementation=implementation,
            services=services,
            success_nodes=topology.success_nodes,
            next_node=topology.next_node,
        )

    graph = StateGraph(RuntimeGraphState)
    for node_id, runner in node_runners.items():
        graph.add_node(node_id, runner)
    graph.set_conditional_entry_point(
        _entry_router(topology),
        {node.node_id: node.node_id for node in topology.nodes},
    )
    outgoing: dict[str, dict[str, str]] = {}
    for edge in topology.edges:
        outgoing.setdefault(edge.source, {})[edge.condition] = edge.target
    for node in topology.nodes:
        if node.node_id in topology.success_nodes:
            graph.add_edge(node.node_id, END)
            continue
        mapping = dict(outgoing.get(node.node_id, {}))
        mapping["__end__"] = END
        graph.add_conditional_edges(node.node_id, _route_router(mapping), mapping)

    return CompiledRuntimeGraph(
        strategy=strategy,
        graph_app=graph.compile(checkpointer=services.checkpointer, store=services.graph_store),
        services=services,
        node_runners=node_runners,
    )


def fixed_graph_model_output_visible(strategy: str, node_id: str | None) -> bool:
    if strategy not in {"react", "plan_and_execute"}:
        return False
    return str(node_id or "") in _topology(strategy).visible_model_nodes


def _entry_router(topology: FixedTopology):
    node_ids = {node.node_id for node in topology.nodes}

    def route(raw_state: dict[str, Any]) -> str:
        state = _state(raw_state)
        if state.run.strategy != topology.strategy:
            raise RuntimeError(
                f"runtime strategy {state.run.strategy!r} cannot execute {topology.strategy!r} graph"
            )
        current = state.execution.current_node
        if current in node_ids and not state.execution.finished:
            return current or topology.entry_node
        return topology.entry_node

    return route


def _route_router(mapping: dict[str, str]):
    allowed = set(mapping)

    def route(raw_state: dict[str, Any]) -> str:
        state = _state(raw_state)
        if state.execution.finished or state.execution.interrupted or state.policy.interrupted:
            return "__end__"
        decision = state.execution.route_decision
        return decision if decision in allowed else "__end__"

    return route


def _state(raw_state: dict[str, Any]) -> RuntimeState:
    return RuntimeState.model_validate(raw_state.get("runtime") or {})


def _node_implementations() -> dict[str, NodeImplementation]:
    implementations: tuple[NodeImplementation, ...] = (
        IngressNode(),
        CognitiveAnswerNode(),
        OperationalToolCallNode(),
        TerminalCommitNode(),
        FinalizeNode(),
    )
    return {implementation.impl_id: implementation for implementation in implementations}


def _topology(strategy: FixedGraphStrategy) -> FixedTopology:
    if strategy == "react":
        return _react_topology()
    if strategy == "plan_and_execute":
        return _plan_and_execute_topology()
    raise ValueError(f"unsupported fixed runtime strategy: {strategy}")


def _react_topology() -> FixedTopology:
    return FixedTopology(
        strategy="react",
        entry_node="ingress",
        nodes=(
            FixedNode("ingress", "ingress"),
            FixedNode("answer", "cognitive.answer"),
            FixedNode("tool_exec", "operational.tool_call"),
            FixedNode("commit", "terminal.commit"),
            FixedNode("finalize", "finalize"),
        ),
        edges=(
            FixedEdge("ingress", "answer", "always"),
            FixedEdge("answer", "tool_exec", "model.requests_tool"),
            FixedEdge("answer", "answer", "runtime.steered"),
            FixedEdge("answer", "commit", "model.ready_to_answer"),
            FixedEdge("tool_exec", "answer", "tool.completed"),
            FixedEdge("tool_exec", "answer", "tool.failed"),
            FixedEdge("tool_exec", "finalize", "tool.interrupted"),
            FixedEdge("tool_exec", "finalize", "policy.blocked"),
            FixedEdge("commit", "answer", "runtime.steered"),
            FixedEdge("commit", "finalize", "always"),
        ),
        success_nodes=frozenset({"finalize"}),
        visible_model_nodes=frozenset({"answer"}),
    )


def _plan_and_execute_topology() -> FixedTopology:
    return FixedTopology(
        strategy="plan_and_execute",
        entry_node="ingress",
        nodes=(
            FixedNode("ingress", "ingress"),
            FixedNode("planner", "cognitive.answer"),
            FixedNode("executor", "cognitive.answer"),
            FixedNode("tool_exec", "operational.tool_call"),
            FixedNode("commit", "terminal.commit"),
            FixedNode("finalize", "finalize"),
        ),
        edges=(
            FixedEdge("ingress", "planner", "always"),
            FixedEdge("planner", "tool_exec", "model.requests_tool"),
            FixedEdge("planner", "planner", "runtime.steered"),
            FixedEdge("planner", "executor", "model.ready_to_answer"),
            FixedEdge("planner", "commit", "subgraph.need_more_input"),
            FixedEdge("executor", "tool_exec", "model.requests_tool"),
            FixedEdge("executor", "planner", "runtime.steered"),
            FixedEdge("executor", "commit", "model.ready_to_answer"),
            FixedEdge("tool_exec", "planner", "tool.return.planner"),
            FixedEdge("tool_exec", "executor", "tool.return.executor"),
            FixedEdge("tool_exec", "finalize", "tool.interrupted"),
            FixedEdge("tool_exec", "finalize", "policy.blocked"),
            FixedEdge("commit", "planner", "runtime.steered"),
            FixedEdge("commit", "finalize", "always"),
        ),
        success_nodes=frozenset({"finalize"}),
        visible_model_nodes=frozenset({"planner", "executor"}),
    )
