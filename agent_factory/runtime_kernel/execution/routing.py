from __future__ import annotations

from agent_factory.runtime_kernel.patterns.schema import GraphPatternSpec
from agent_factory.runtime_kernel.state import RuntimeState


def resolve_next_node(spec: GraphPatternSpec, *, current_node: str, state: RuntimeState) -> str | None:
    fallback = None
    for edge in spec.edges:
        if edge.from_ != current_node:
            continue
        if edge.when == "always":
            fallback = edge.to
            continue
        if state.execution.route_decision == edge.when:
            return edge.to
    return fallback
