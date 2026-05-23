from agent_factory.factory_package.stages import (
    assembly_spec_generation,
    graph_behavior_planning,
    harness_generation_and_test,
    node_strategy_planning,
    package_generation,
    repair_or_finalize,
    requirement_capture,
    resource_and_condition_planning,
    runtime_pattern_selection,
    tool_capability_planning,
)

FACTORY_STAGE_HANDLERS = {
    "requirement_capture": requirement_capture.run,
    "runtime_pattern_selection": runtime_pattern_selection.run,
    "graph_behavior_planning": graph_behavior_planning.run,
    "node_strategy_planning": node_strategy_planning.run,
    "tool_capability_planning": tool_capability_planning.run,
    "resource_and_condition_planning": resource_and_condition_planning.run,
    "assembly_spec_generation": assembly_spec_generation.run,
    "package_generation": package_generation.run,
    "harness_generation_and_test": harness_generation_and_test.run,
    "repair_or_finalize": repair_or_finalize.run,
}

__all__ = ["FACTORY_STAGE_HANDLERS"]
