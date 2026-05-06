from __future__ import annotations

from abc import ABC
from collections.abc import Callable
from typing import Annotated, Any, Literal, TypedDict
import operator

from langgraph.graph import END, START, StateGraph


WrapperPhase = Literal["before", "after", "on_error"]


class DemoState(TypedDict):
    user_input: str
    draft: str
    final_answer: str
    trace: Annotated[list[str], operator.add]


class NodeWrapper(ABC):
    wrapper_id: str
    supported_phases: set[WrapperPhase] = {"before", "after", "on_error"}

    def before(self, *, state: DemoState, node_id: str, config: dict[str, Any]) -> dict[str, Any]:
        return {}

    def after(
        self,
        *,
        state: DemoState,
        node_id: str,
        config: dict[str, Any],
        node_result: dict[str, Any],
    ) -> dict[str, Any]:
        return {}

    def on_error(
        self,
        *,
        state: DemoState,
        node_id: str,
        config: dict[str, Any],
        error: Exception,
    ) -> dict[str, Any]:
        return {}


WRAPPER_REGISTRY: dict[str, type[NodeWrapper]] = {}


def wrap_node(wrapper_id: str) -> Callable[[type[NodeWrapper]], type[NodeWrapper]]:
    def decorator(wrapper_cls: type[NodeWrapper]) -> type[NodeWrapper]:
        wrapper_cls.wrapper_id = wrapper_id
        WRAPPER_REGISTRY[wrapper_id] = wrapper_cls
        return wrapper_cls

    return decorator


@wrap_node("console.node_trace")
class ConsoleNodeTraceWrapper(NodeWrapper):
    supported_phases = {"before", "after"}

    def before(self, *, state: DemoState, node_id: str, config: dict[str, Any]) -> dict[str, Any]:
        print(f"节点 {node_id} 前")
        return {"trace": [f"{node_id}:before"]}

    def after(
        self,
        *,
        state: DemoState,
        node_id: str,
        config: dict[str, Any],
        node_result: dict[str, Any],
    ) -> dict[str, Any]:
        print(f"节点 {node_id} 后")
        return {"trace": [f"{node_id}:after"]}


GRAPH_DSL: dict[str, Any] = {
    "nodes": [
        {
            "id": "ingress",
            "wrappers": [
                {
                    "id": "console.node_trace",
                    "phase": "before",
                    "order": 10,
                    "config": {},
                },
                {
                    "id": "console.node_trace",
                    "phase": "after",
                    "order": 10,
                    "config": {},
                },
            ],
        },
        {
            "id": "answer",
            "wrappers": [
                {
                    "id": "console.node_trace",
                    "phase": "before",
                    "order": 10,
                    "config": {},
                },
                {
                    "id": "console.node_trace",
                    "phase": "after",
                    "order": 10,
                    "config": {},
                },
            ],
        },
        {
            "id": "finalize",
            "wrappers": [
                {
                    "id": "console.node_trace",
                    "phase": "before",
                    "order": 10,
                    "config": {},
                },
                {
                    "id": "console.node_trace",
                    "phase": "after",
                    "order": 10,
                    "config": {},
                },
            ],
        },
    ],
    "edges": [
        {"from": START, "to": "ingress"},
        {"from": "ingress", "to": "answer"},
        {"from": "answer", "to": "finalize"},
        {"from": "finalize", "to": END},
    ],
}


def ingress_node(state: DemoState) -> dict[str, Any]:
    return {"trace": ["ingress:business"]}


def answer_node(state: DemoState) -> dict[str, Any]:
    return {
        "draft": f"收到：{state['user_input']}",
        "trace": ["answer:business"],
    }


def finalize_node(state: DemoState) -> dict[str, Any]:
    return {
        "final_answer": state["draft"],
        "trace": ["finalize:business"],
    }


NODE_IMPLS: dict[str, Callable[[DemoState], dict[str, Any]]] = {
    "ingress": ingress_node,
    "answer": answer_node,
    "finalize": finalize_node,
}


def compile_node(node_id: str, business_fn: Callable[[DemoState], dict[str, Any]]) -> Callable[[DemoState], dict[str, Any]]:
    node_dsl = next(item for item in GRAPH_DSL["nodes"] if item["id"] == node_id)
    wrappers = sorted(node_dsl.get("wrappers", []), key=lambda item: int(item.get("order", 0)))

    def wrapped(state: DemoState) -> dict[str, Any]:
        patch: dict[str, Any] = {}
        try:
            for wrapper_config in wrappers:
                if wrapper_config.get("phase") != "before":
                    continue
                wrapper = _load_wrapper(wrapper_config)
                patch = _merge_patch(
                    patch,
                    wrapper.before(
                        state=state,
                        node_id=node_id,
                        config=dict(wrapper_config.get("config") or {}),
                    ),
                )

            state_for_business = _merge_state(state, patch)
            node_result = business_fn(state_for_business)
            patch = _merge_patch(patch, node_result)

            state_for_after = _merge_state(state_for_business, node_result)
            for wrapper_config in wrappers:
                if wrapper_config.get("phase") != "after":
                    continue
                wrapper = _load_wrapper(wrapper_config)
                patch = _merge_patch(
                    patch,
                    wrapper.after(
                        state=state_for_after,
                        node_id=node_id,
                        config=dict(wrapper_config.get("config") or {}),
                        node_result=node_result,
                    ),
                )
            return patch
        except Exception as exc:
            for wrapper_config in wrappers:
                if wrapper_config.get("phase") != "on_error":
                    continue
                wrapper = _load_wrapper(wrapper_config)
                patch = _merge_patch(
                    patch,
                    wrapper.on_error(
                        state=state,
                        node_id=node_id,
                        config=dict(wrapper_config.get("config") or {}),
                        error=exc,
                    ),
                )
            raise

    return wrapped


def build_graph():
    graph = StateGraph(DemoState)
    for node_id, business_fn in NODE_IMPLS.items():
        graph.add_node(node_id, compile_node(node_id, business_fn))
    for edge in GRAPH_DSL["edges"]:
        graph.add_edge(edge["from"], edge["to"])
    return graph.compile()


def _load_wrapper(wrapper_config: dict[str, Any]) -> NodeWrapper:
    wrapper_id = str(wrapper_config["id"])
    wrapper_cls = WRAPPER_REGISTRY.get(wrapper_id)
    if wrapper_cls is None:
        raise RuntimeError(f"Unknown wrapper: {wrapper_id}")
    phase = wrapper_config.get("phase")
    if phase not in wrapper_cls.supported_phases:
        raise RuntimeError(f"Wrapper {wrapper_id} does not support phase: {phase}")
    return wrapper_cls()


def _merge_state(state: DemoState, patch: dict[str, Any]) -> DemoState:
    merged = dict(state)
    for key, value in patch.items():
        if key == "trace":
            merged[key] = [*merged.get(key, []), *value]
        else:
            merged[key] = value
    return merged  # type: ignore[return-value]


def _merge_patch(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    merged = dict(left)
    for key, value in right.items():
        if key == "trace":
            merged[key] = [*merged.get(key, []), *value]
        else:
            merged[key] = value
    return merged


def main() -> None:
    app = build_graph()
    result = app.invoke(
        {
            "user_input": "hello",
            "draft": "",
            "final_answer": "",
            "trace": [],
        }
    )
    print("最终 trace:", result["trace"])
    print("最终回答:", result["final_answer"])


if __name__ == "__main__":
    main()
