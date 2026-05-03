from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from agent_factory.factory_runtime.production.nodes import FactoryProductionNodes
from agent_factory.factory_runtime.production.routes import (
    route_after_artifact_generation,
    route_after_intent_classification,
    route_after_maybe_clarify,
    route_after_package_write,
    route_after_plan_primitives,
    route_after_readiness,
    route_after_repair,
    route_after_tool_test_repair,
    route_after_tool_tests,
    route_after_validate_package,
    route_after_validate_primitives,
    route_after_verification,
)
from agent_factory.factory_runtime.production.state import FactoryProductionStateDict


def build_factory_production_graph(nodes: FactoryProductionNodes):
    graph = StateGraph(FactoryProductionStateDict)
    graph.add_node("capture_requirement", nodes.capture_requirement)
    graph.add_node("load_factory_context", nodes.load_factory_context)
    graph.add_node("classify_factory_intent", nodes.classify_factory_intent)
    graph.add_node("analyze_requirement", nodes.analyze_requirement)
    graph.add_node("maybe_clarify", nodes.maybe_clarify)
    graph.add_node("plan_primitives", nodes.plan_primitives)
    graph.add_node("validate_primitives", nodes.validate_primitives)
    graph.add_node("repair_primitives", nodes.repair_primitives)
    graph.add_node("plan_capability_preconditions", nodes.plan_capability_preconditions)
    graph.add_node("discover_resources", nodes.discover_resources)
    graph.add_node("probe_environment", nodes.probe_environment)
    graph.add_node("resolve_readiness", nodes.resolve_readiness)
    graph.add_node("write_package", nodes.write_package)
    graph.add_node("generate_tool_scripts", nodes.generate_tool_scripts)
    graph.add_node("generate_tool_tests", nodes.generate_tool_tests)
    graph.add_node("generate_mcp_bindings", nodes.generate_mcp_bindings)
    graph.add_node("generate_harness_scenarios", nodes.generate_harness_scenarios)
    graph.add_node("validate_package", nodes.validate_package)
    graph.add_node("static_check_tool_scripts", nodes.static_check_tool_scripts)
    graph.add_node("run_generated_tool_tests", nodes.run_generated_tool_tests)
    graph.add_node("repair_tool_tests", nodes.repair_tool_tests)
    graph.add_node("validate_mcp_bindings_local", nodes.validate_mcp_bindings_local)
    graph.add_node("dry_run_harness_scenarios", nodes.dry_run_harness_scenarios)
    graph.add_node("record_factory_memory", nodes.record_factory_memory)
    graph.add_node("complete", nodes.complete)
    graph.add_node("failed", nodes.failed)
    graph.add_node("needs_clarification", nodes.needs_clarification)
    graph.add_node("not_agent_request", nodes.not_agent_request)

    graph.add_edge(START, "capture_requirement")
    graph.add_edge("capture_requirement", "load_factory_context")
    graph.add_edge("load_factory_context", "classify_factory_intent")
    graph.add_conditional_edges(
        "classify_factory_intent",
        route_after_intent_classification,
        {
            "analyze_requirement": "analyze_requirement",
            "needs_clarification": "needs_clarification",
            "not_agent_request": "not_agent_request",
        },
    )
    graph.add_edge("analyze_requirement", "maybe_clarify")
    graph.add_conditional_edges(
        "maybe_clarify",
        route_after_maybe_clarify,
        {
            "needs_clarification": "needs_clarification",
            "plan_primitives": "plan_primitives",
        },
    )
    graph.add_conditional_edges(
        "plan_primitives",
        route_after_plan_primitives,
        {
            "validate_primitives": "validate_primitives",
            "failed": "failed",
        },
    )
    graph.add_conditional_edges(
        "validate_primitives",
        route_after_validate_primitives,
        {
            "repair_primitives": "repair_primitives",
            "plan_capability_preconditions": "plan_capability_preconditions",
            "failed": "failed",
        },
    )
    graph.add_conditional_edges(
        "repair_primitives",
        route_after_repair,
        {
            "validate_primitives": "validate_primitives",
            "failed": "failed",
        },
    )
    graph.add_edge("plan_capability_preconditions", "discover_resources")
    graph.add_edge("discover_resources", "probe_environment")
    graph.add_edge("probe_environment", "resolve_readiness")
    graph.add_conditional_edges(
        "resolve_readiness",
        route_after_readiness,
        {
            "write_package": "write_package",
            "needs_clarification": "needs_clarification",
            "failed": "failed",
        },
    )
    graph.add_conditional_edges(
        "write_package",
        route_after_package_write,
        {
            "generate_tool_scripts": "generate_tool_scripts",
            "failed": "failed",
        },
    )
    graph.add_conditional_edges(
        "generate_tool_scripts",
        route_after_artifact_generation,
        {
            "continue": "generate_tool_tests",
            "failed": "failed",
        },
    )
    graph.add_conditional_edges(
        "generate_tool_tests",
        route_after_artifact_generation,
        {
            "continue": "generate_mcp_bindings",
            "failed": "failed",
        },
    )
    graph.add_conditional_edges(
        "generate_mcp_bindings",
        route_after_artifact_generation,
        {
            "continue": "generate_harness_scenarios",
            "failed": "failed",
        },
    )
    graph.add_conditional_edges(
        "generate_harness_scenarios",
        route_after_artifact_generation,
        {
            "continue": "validate_package",
            "failed": "failed",
        },
    )
    graph.add_conditional_edges(
        "validate_package",
        route_after_validate_package,
        {
            "static_check_tool_scripts": "static_check_tool_scripts",
            "failed": "failed",
        },
    )
    graph.add_conditional_edges(
        "static_check_tool_scripts",
        route_after_verification,
        {
            "continue": "run_generated_tool_tests",
            "failed": "failed",
        },
    )
    graph.add_conditional_edges(
        "run_generated_tool_tests",
        route_after_tool_tests,
        {
            "continue": "validate_mcp_bindings_local",
            "repair_tool_tests": "repair_tool_tests",
            "failed": "failed",
        },
    )
    graph.add_conditional_edges(
        "repair_tool_tests",
        route_after_tool_test_repair,
        {
            "run_generated_tool_tests": "run_generated_tool_tests",
            "failed": "failed",
        },
    )
    graph.add_conditional_edges(
        "validate_mcp_bindings_local",
        route_after_verification,
        {
            "continue": "dry_run_harness_scenarios",
            "failed": "failed",
        },
    )
    graph.add_conditional_edges(
        "dry_run_harness_scenarios",
        route_after_verification,
        {
            "continue": "record_factory_memory",
            "failed": "failed",
        },
    )
    graph.add_edge("record_factory_memory", "complete")
    graph.add_edge("complete", END)
    graph.add_edge("failed", END)
    graph.add_edge("needs_clarification", END)
    graph.add_edge("not_agent_request", END)
    return graph.compile()
