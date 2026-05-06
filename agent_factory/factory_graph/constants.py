from __future__ import annotations


STAGE_IDS: tuple[str, ...] = (
    "capture_requirement",
    "understand_requirement",
    "plan_capabilities",
    "identify_conditions",
    "plan_resource_needs",
    "collect_evidence",
    "build_resource_contracts",
    "decide_readiness",
    "plan_implementation",
    "generate_package_specs",
    "generate_tools",
    "sandbox_test_and_repair",
    "generate_harness",
    "complete_summary",
)


EMPTY_STAGE_MESSAGE = "stage skeleton preserved; implementation pending rewrite."
