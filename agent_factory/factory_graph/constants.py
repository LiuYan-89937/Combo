from __future__ import annotations


STAGE_IDS: tuple[str, ...] = (
    "requirement_capture",
    "runtime_pattern_selection",
    "graph_behavior_planning",
    "node_strategy_planning",
    "tool_capability_planning",
    "resource_and_condition_planning",
    "assembly_spec_generation",
    "package_generation",
    "harness_generation_and_test",
    "repair_or_finalize",
)


EMPTY_STAGE_MESSAGE = "stage skeleton preserved; implementation pending rewrite."
DEFAULT_CREATE_AGENT_BREAKPOINT_STAGE = "package_generation"
