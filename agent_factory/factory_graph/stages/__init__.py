from agent_factory.factory_graph.stages import (
    build_resource_contracts,
    capture_requirement,
    collect_evidence,
    complete_summary,
    decide_readiness,
    generate_harness,
    generate_package_specs,
    generate_tools,
    identify_conditions,
    plan_capabilities,
    plan_implementation,
    plan_resource_needs,
    sandbox_test_and_repair,
    understand_requirement,
)

STAGE_RUNNERS = {
    "capture_requirement": capture_requirement.run,
    "understand_requirement": understand_requirement.run,
    "plan_capabilities": plan_capabilities.run,
    "identify_conditions": identify_conditions.run,
    "plan_resource_needs": plan_resource_needs.run,
    "collect_evidence": collect_evidence.run,
    "build_resource_contracts": build_resource_contracts.run,
    "decide_readiness": decide_readiness.run,
    "plan_implementation": plan_implementation.run,
    "generate_package_specs": generate_package_specs.run,
    "generate_tools": generate_tools.run,
    "sandbox_test_and_repair": sandbox_test_and_repair.run,
    "generate_harness": generate_harness.run,
    "complete_summary": complete_summary.run,
}

__all__ = ["STAGE_RUNNERS"]
