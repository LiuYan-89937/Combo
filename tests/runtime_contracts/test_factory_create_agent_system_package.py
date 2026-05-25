from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from agent_factory.assembly.compiler import AgentAssemblyCompiler
from agent_factory.factory_package.capability_contract import (
    STANDARD_CAPABILITY_SYSTEMS,
    capability_contract_catalog_payload,
    validate_capability_contract,
)
from agent_factory.factory_package.constants import (
    CAPABILITY_CONTRACT_NODE_ID,
    PACKAGE_BUILD_NODE_ID,
    PRODUCT_BRIEF_NODE_ID,
    RUNTIME_DESIGN_NODE_ID,
)
from agent_factory.factory_package.package_build import build_agent_package, default_package_build_plan
from agent_factory.factory_package.runtime_design import validate_runtime_design
from agent_factory.factory_package.schemas import CapabilityContractOutput, ProductBriefOutput, RuntimeDesignOutput
from agent_factory.factory_package.nodes import factory_manufacturing_node_provider
from agent_factory.package_runtime import host_runtime_package_view, register_package_patterns
from agent_factory.runtime_contracts import AgentPackageLoader, RuntimeBuildPlanner
from agent_factory.runtime_contracts.builtins import default_runtime_contract_registry
from agent_factory.runtime_kernel.kernel import RuntimeKernelFacade
from agent_factory.runtime_kernel.persistence import LangGraphCheckpointerConfig, LangGraphStoreConfig


class FactoryCreateAgentSystemPackageTest(unittest.TestCase):
    def test_system_package_manifest_contracts_and_pattern_are_loadable(self) -> None:
        package = AgentPackageLoader().load_path("SystemPackage/factory_create_agent/agent_package.json")

        self.assertEqual(package.assembly_spec.agent.id, "factory_create_agent")
        self.assertEqual(package.manifest.runtime.get("system_package"), True)
        self.assertEqual(package.manifest.runtime.get("execution_backend"), "host")
        self.assertEqual([pattern.pattern_id for pattern in package.patterns], ["factory_manufacturing"])
        self.assertEqual(
            [node.id for node in package.patterns[0].nodes],
            [PRODUCT_BRIEF_NODE_ID, RUNTIME_DESIGN_NODE_ID, CAPABILITY_CONTRACT_NODE_ID, PACKAGE_BUILD_NODE_ID],
        )
        self.assertEqual(set(package.contracts), {
            "artifact",
            "context",
            "dependencies",
            "knowledge",
            "memory",
            "model",
            "node_provider",
            "render",
            "resources",
            "sandbox",
            "scheduler",
            "session",
            "state",
            "tools",
            "trace",
        })

    def test_factory_node_provider_registers_product_brief_impl(self) -> None:
        provider = factory_manufacturing_node_provider()
        impl_ids = [implementation.impl_id for implementation in provider.implementations()]

        self.assertEqual(
            impl_ids,
            [
                f"builtin.factory.{PRODUCT_BRIEF_NODE_ID}",
                f"builtin.factory.{RUNTIME_DESIGN_NODE_ID}",
                f"builtin.factory.{CAPABILITY_CONTRACT_NODE_ID}",
                f"builtin.factory.{PACKAGE_BUILD_NODE_ID}",
            ],
        )

    def test_system_package_compiles_through_runtime_contracts(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package = AgentPackageLoader().load_path("SystemPackage/factory_create_agent/agent_package.json")
            package = host_runtime_package_view(
                _test_runtime_contract_view(package, root),
                runtime_root=root / "runtime",
                artifacts_root=root / "artifacts",
                workdir_root=root / "workdir",
                extension_root=root / "extensions",
            )
            facade = RuntimeKernelFacade(
                checkpointer_config=LangGraphCheckpointerConfig(backend="memory"),
                memory_store_config=LangGraphStoreConfig(backend="memory"),
            )
            runtime_build = RuntimeBuildPlanner(registry=default_runtime_contract_registry()).build(
                package,
                base_services=facade.instance.services,
            )

            register_package_patterns(facade=facade, package=package, runtime_build=runtime_build)
            compiled = AgentAssemblyCompiler(facade=facade).compile(
                package.assembly_spec,
                runtime_build=runtime_build,
            )

            self.assertEqual(compiled.pattern_spec.pattern_id, "factory_create_agent__factory_manufacturing")
            self.assertEqual(
                [node.id for node in compiled.pattern_spec.nodes],
                [PRODUCT_BRIEF_NODE_ID, RUNTIME_DESIGN_NODE_ID, CAPABILITY_CONTRACT_NODE_ID, PACKAGE_BUILD_NODE_ID],
            )

    def test_package_build_materializes_loader_valid_agent_package(self) -> None:
        with TemporaryDirectory() as temp_dir:
            product_brief = ProductBriefOutput.model_validate(
                {
                    "version": "product_brief.v0",
                    "working_title": "Research Assistant",
                    "agent_goal": "Answer user questions with available tools.",
                    "target_user": "Local CLI user",
                    "first_version_scope": "Conversational assistant with runtime contracts.",
                    "primary_workflow": "Read the request, reason, optionally call tools, and answer.",
                    "autonomy_boundary": "Use configured tools only.",
                    "human_review_boundary": "Ask before risky operations.",
                    "resource_boundary": "Use runtime resources only.",
                    "expected_outputs": ["Concise answers"],
                    "success_criteria": ["Compiles as an AgentPackage"],
                    "out_of_scope": [],
                    "manufacturing_assumptions": [],
                    "blocking_questions": [],
                    "business_plan_text": "Create a simple tool-capable assistant.",
                    "ready_for_runtime_design": True,
                }
            )
            runtime_design = _runtime_design_fixture()
            drafts = capability_contract_catalog_payload(runtime_design)["default_contract_drafts"]
            contract = _valid_capability_contract(runtime_design, drafts)
            plan = default_package_build_plan(
                factory_run_id="test_factory_run",
                product_brief=product_brief,
                runtime_design=runtime_design,
                capability_contract=contract,
            )

            result = build_agent_package(
                plan=plan,
                product_brief=product_brief,
                runtime_design=runtime_design,
                capability_contract=contract,
                output_root=Path(temp_dir) / "packages",
            )

            self.assertEqual(result.report.status, "valid", result.report.errors)
            package = AgentPackageLoader().load_path(Path(result.report.package_root) / "agent_package.json")
            self.assertEqual(package.assembly_spec.agent.id, plan.agent_id)
            self.assertEqual(package.assembly_spec.runtime.pattern_id, "react_agent")
            self.assertEqual(set(package.contracts), set(drafts))

    def test_package_build_uses_package_root_relative_tool_entrypoint(self) -> None:
        with TemporaryDirectory() as temp_dir:
            product_brief = ProductBriefOutput.model_validate(
                {
                    "version": "product_brief.v0",
                    "working_title": "Reporter",
                    "agent_goal": "Prepare reports with a generated delivery tool.",
                    "target_user": "Local CLI user",
                    "first_version_scope": "Generate and deliver a report.",
                    "primary_workflow": "Answer, call the report tool when needed, and return the result.",
                    "autonomy_boundary": "Use configured tools only.",
                    "human_review_boundary": "Ask before risky operations.",
                    "resource_boundary": "Use runtime resources only.",
                    "expected_outputs": ["Report text"],
                    "success_criteria": ["Generated tool compiles"],
                    "out_of_scope": [],
                    "manufacturing_assumptions": [],
                    "blocking_questions": [],
                    "business_plan_text": "Create a report-capable assistant.",
                    "ready_for_runtime_design": True,
                }
            )
            runtime_design = _runtime_design_fixture()
            drafts = capability_contract_catalog_payload(runtime_design)["default_contract_drafts"]
            base_contract = _valid_capability_contract(runtime_design, drafts)
            contract = CapabilityContractOutput.model_validate(
                {
                    **base_contract.model_dump(mode="json"),
                    "tool_specs_to_generate": [
                        {
                            "tool_id": "deliver_report",
                            "purpose": "Return a report payload.",
                            "source": "package_generated",
                            "required_by_nodes": ["answer"],
                            "risk_level": "low",
                            "input_summary": "report text",
                            "output_summary": "delivery status",
                        }
                    ],
                }
            )
            base_plan = default_package_build_plan(
                factory_run_id="tool_factory_run",
                product_brief=product_brief,
                runtime_design=runtime_design,
                capability_contract=contract,
            )
            plan = type(base_plan).model_validate(
                {
                    **base_plan.model_dump(mode="json"),
                    "package_tools": [
                        {
                            "tool_id": "deliver_report",
                            "description": "Return report delivery status.",
                            "input_schema": {
                                "type": "object",
                                "properties": {"report": {"type": "string"}},
                                "required": ["report"],
                                "additionalProperties": False,
                            },
                            "output_schema": {
                                "type": "object",
                                "properties": {"status": {"type": "string"}},
                                "required": ["status"],
                                "additionalProperties": False,
                            },
                            "resources": {},
                            "risk_level": "low",
                            "concurrent": True,
                            "python_requirements": ["feedparser>=6"],
                            "system_packages": [],
                            "system_binaries": [],
                            "code": (
                                "import feedparser\n\n"
                                "def run(arguments: dict, resources: dict) -> dict:\n"
                                "    feedparser.parse(arguments.get(\"report\", \"\"))\n"
                                "    return {\"status\": \"delivered\"}\n"
                            ),
                        }
                    ],
                }
            )

            result = build_agent_package(
                plan=plan,
                product_brief=product_brief,
                runtime_design=runtime_design,
                capability_contract=contract,
                output_root=Path(temp_dir) / "packages",
            )

            self.assertEqual(result.report.status, "valid", result.report.errors)
            manifest_path = Path(result.report.package_root) / "tools" / "deliver_report" / "manifest.json"
            self.assertIn(
                '"entrypoint": "tools/deliver_report/tool.py:run"',
                manifest_path.read_text(encoding="utf-8"),
            )
            dependencies = json.loads(
                (Path(result.report.package_root) / "contracts" / "dependencies.json").read_text(encoding="utf-8")
            )
            self.assertIn("feedparser>=6", dependencies["config"]["python_requirements"])

    def test_package_build_rejects_prompt_variables_without_kernel_source(self) -> None:
        with TemporaryDirectory() as temp_dir:
            product_brief = ProductBriefOutput.model_validate(
                {
                    "version": "product_brief.v0",
                    "working_title": "Reporter",
                    "agent_goal": "Prepare reports with available runtime context.",
                    "target_user": "Local CLI user",
                    "first_version_scope": "Generate a report.",
                    "primary_workflow": "Answer with available tools and runtime context.",
                    "autonomy_boundary": "Use configured tools only.",
                    "human_review_boundary": "Ask before risky operations.",
                    "resource_boundary": "Use runtime resources only.",
                    "expected_outputs": ["Report text"],
                    "success_criteria": ["Generated package rejects disconnected prompt variables"],
                    "out_of_scope": [],
                    "manufacturing_assumptions": [],
                    "blocking_questions": [],
                    "business_plan_text": "Create a report-capable assistant.",
                    "ready_for_runtime_design": True,
                }
            )
            runtime_design = _runtime_design_fixture()
            drafts = capability_contract_catalog_payload(runtime_design)["default_contract_drafts"]
            contract = _valid_capability_contract(runtime_design, drafts)
            base_plan = default_package_build_plan(
                factory_run_id="bad_prompt_factory_run",
                product_brief=product_brief,
                runtime_design=runtime_design,
                capability_contract=contract,
            )
            plan = type(base_plan).model_validate(
                {
                    **base_plan.model_dump(mode="json"),
                    "prompt_templates": [
                        {
                            "prompt_id": "bad.prompt",
                            "node_id": "answer",
                            "template": "Use {raw_news}.",
                            "variables": ["raw_news"],
                        }
                    ],
                }
            )

            result = build_agent_package(
                plan=plan,
                product_brief=product_brief,
                runtime_design=runtime_design,
                capability_contract=contract,
                output_root=Path(temp_dir) / "packages",
            )

            self.assertEqual(result.report.status, "invalid")
            self.assertTrue(any("raw_news" in error for error in result.report.errors))

    def test_runtime_design_prevalidation_accepts_kernel_legal_reuse_design(self) -> None:
        design = RuntimeDesignOutput.model_validate(
            {
                "version": "runtime_design.v0",
                "design_mode": "reuse_pattern",
                "selected_pattern_id": "react_agent",
                "graph_intent": "Build a conversational tool-using agent.",
                "nodes": [
                    {
                        "node_id": "answer",
                        "node_type": "cognitive",
                        "impl": "cognitive.answer",
                        "purpose": "Reason about user requests and decide whether tools are needed.",
                        "model_operation": "tool_bound_chat",
                        "requires_tools": True,
                    },
                    {
                        "node_id": "tool_exec",
                        "node_type": "operational",
                        "impl": "operational.tool_call",
                        "purpose": "Execute model requested tools through ToolExecutionGateway.",
                    },
                ],
                "interrupts": [],
                "state_namespaces": [
                    {
                        "namespace": "example_agent",
                        "purpose": "Store user-facing agent preferences.",
                        "owned_by_nodes": ["answer"],
                    }
                ],
                "required_contracts": ["model", "tools", "state", "context", "trace"],
                "package_nodes_to_generate": [],
                "structured_outputs": [],
                "runtime_assumptions": [],
                "blocking_questions": [],
                "design_summary_text": "Use the built-in ReAct pattern.",
            }
        )

        report = validate_runtime_design(design)

        self.assertEqual(report.status, "valid")
        self.assertEqual(report.selected_pattern_id, "react_agent")

    def test_runtime_design_rejects_custom_edges(self) -> None:
        with self.assertRaises(ValueError):
            RuntimeDesignOutput.model_validate(
                {
                    "version": "runtime_design.v0",
                    "design_mode": "reuse_pattern",
                    "selected_pattern_id": "react_agent",
                    "graph_intent": "Invalid custom topology.",
                    "edges": [
                        {
                            "from_node": "answer",
                            "to_node": "tool_exec",
                            "when": "always",
                            "business_meaning": "custom route",
                        }
                    ],
                    "required_contracts": ["model", "trace"],
                    "design_summary_text": "This should fail because preset patterns own topology.",
                }
            )

    def test_capability_contract_validation_accepts_registry_valid_contracts(self) -> None:
        runtime_design = _runtime_design_fixture()
        drafts = capability_contract_catalog_payload(runtime_design)["default_contract_drafts"]
        output = CapabilityContractOutput.model_validate(
            {
                "version": "capability_contract.v0",
                "contract_drafts": drafts,
                "capability_plans": {
                    key: {
                        "enabled": bool(drafts.get(key, {}).get("enabled", False)),
                        "why": f"{key} capability is configured according to Runtime Design.",
                        "what": {"contract": key},
                        "strategy": {"runtime": "Use the standard RuntimeContract builder."},
                        "risks": [],
                        "deferred_decisions": [],
                    }
                    for key in STANDARD_CAPABILITY_SYSTEMS
                },
                "tool_specs_to_generate": [],
                "package_nodes_to_generate": [],
                "prompts_to_generate": [],
                "bindings_to_generate": [],
                "resources_required": [],
                "sandbox_requirements": [],
                "capability_summary_text": "Use registry-valid default contracts.",
                "risks": [],
                "deferred_decisions": [],
            }
        )

        report = validate_capability_contract(output, runtime_design=runtime_design)

        self.assertEqual(report.status, "valid")
        self.assertIn("tools", report.enabled_contracts)

    def test_capability_contract_merges_multiple_logical_state_namespaces(self) -> None:
        runtime_design = RuntimeDesignOutput.model_validate(
            {
                **_runtime_design_fixture().model_dump(mode="json"),
                "state_namespaces": [
                    {
                        "namespace": "portfolio",
                        "purpose": "Store tracked stocks and portfolio preferences.",
                        "owned_by_nodes": ["answer"],
                    },
                    {
                        "namespace": "reporting",
                        "purpose": "Store reporting preferences and latest report summary.",
                        "owned_by_nodes": ["answer"],
                    },
                ],
            }
        )
        catalog = capability_contract_catalog_payload(runtime_design)
        drafts = catalog["default_contract_drafts"]
        state_plan = {
            "enabled": True,
            "why": "The agent needs durable runtime state for multiple logical business domains.",
            "what": {
                "physical_namespace": drafts["state"]["config"]["namespace"],
                "logical_namespaces": ["portfolio", "reporting"],
            },
            "strategy": {"runtime": "Store logical namespaces as sections inside the physical state namespace."},
            "risks": [],
            "deferred_decisions": [],
        }
        output = CapabilityContractOutput.model_validate(
            {
                "version": "capability_contract.v0",
                "contract_drafts": drafts,
                "capability_plans": {
                    key: (
                        state_plan
                        if key == "state"
                        else {
                            "enabled": bool(drafts.get(key, {}).get("enabled", False)),
                            "why": f"{key} capability is configured according to Runtime Design.",
                            "what": {"contract": key},
                            "strategy": {"runtime": "Use the standard RuntimeContract builder."},
                            "risks": [],
                            "deferred_decisions": [],
                        }
                    )
                    for key in STANDARD_CAPABILITY_SYSTEMS
                },
                "tool_specs_to_generate": [],
                "package_nodes_to_generate": [],
                "prompts_to_generate": [],
                "bindings_to_generate": [],
                "resources_required": [],
                "sandbox_requirements": [],
                "capability_summary_text": "Merge logical state namespaces into one physical state contract.",
                "risks": [],
                "deferred_decisions": [],
            }
        )

        report = validate_capability_contract(output, runtime_design=runtime_design)

        self.assertEqual(drafts["state"]["config"]["namespace"], "agent_state")
        self.assertEqual(report.status, "valid")
        self.assertTrue(any("multiple logical state namespaces" in item for item in report.warnings))


def _test_runtime_contract_view(package, root: Path):
    contracts = dict(package.contracts)
    contracts["session"] = {
        "type": "session",
        "version": "session_contract.v0",
        "enabled": True,
        "config": {
            "session_root": str(root / "sessions"),
            "checkpointer_backend": "memory",
            "checkpoint_path": str(root / "checkpoints" / "agent.sqlite"),
        },
    }
    contracts["memory"] = {
        "type": "memory",
        "version": "memory_contract.v0",
        "enabled": False,
        "config": {"memory_system": {"enabled": False}},
    }
    contracts["scheduler"] = {
        "type": "scheduler",
        "version": "scheduler_contract.v0",
        "enabled": False,
        "config": {"store_path": str(root / "scheduler.sqlite")},
    }
    contracts["knowledge"] = {
        "type": "knowledge",
        "version": "knowledge_contract.v0",
        "enabled": True,
        "config": {
            "root": str(root / "knowledge"),
            "catalog_path": str(root / "knowledge" / "catalog" / "knowledge.sqlite"),
            "rag_store": {
                "backend": "memory",
                "path": str(root / "knowledge" / "catalog" / "knowledge_store.sqlite"),
                "namespace_prefix": ["knowledge"],
                "index_fields": ["content", "title", "summary"],
            },
        },
    }
    contracts["artifact"] = {
        "type": "artifact",
        "version": "artifact_contract.v0",
        "enabled": True,
        "config": {
            "root": str(root / "artifacts"),
            "index_path": str(root / "artifacts" / "index.jsonl"),
            "allowed_kinds": ["report", "artifact"],
        },
    }
    contracts["trace"] = {
        "type": "trace",
        "version": "trace_contract.v0",
        "enabled": True,
        "config": {"root": str(root / "trace")},
    }
    contracts["tools"] = {
        "type": "tools",
        "version": "tools_contract.v0",
        "enabled": True,
        "config": {
            "builtin_tools_enabled": False,
            "package_tools_enabled": False,
            "instance_extensions_enabled": False,
        },
    }
    return replace(package, contracts=contracts)


def _runtime_design_fixture() -> RuntimeDesignOutput:
    return RuntimeDesignOutput.model_validate(
        {
            "version": "runtime_design.v0",
            "design_mode": "reuse_pattern",
            "selected_pattern_id": "react_agent",
            "graph_intent": "Build a conversational tool-using agent.",
            "nodes": [
                {
                    "node_id": "answer",
                    "node_type": "cognitive",
                    "impl": "cognitive.answer",
                    "purpose": "Reason about user requests and decide whether tools are needed.",
                    "model_operation": "tool_bound_chat",
                    "requires_tools": True,
                },
                {
                    "node_id": "tool_exec",
                    "node_type": "operational",
                    "impl": "operational.tool_call",
                    "purpose": "Execute model requested tools through ToolExecutionGateway.",
                },
            ],
            "interrupts": [],
            "state_namespaces": [
                {
                    "namespace": "example_agent",
                    "purpose": "Store user-facing agent preferences.",
                    "owned_by_nodes": ["answer"],
                }
            ],
            "required_contracts": ["model", "tools", "state", "context", "trace"],
            "package_nodes_to_generate": [],
            "structured_outputs": [],
            "runtime_assumptions": [],
            "blocking_questions": [],
            "design_summary_text": "Use the built-in ReAct pattern.",
        }
    )


def _valid_capability_contract(
    runtime_design: RuntimeDesignOutput,
    drafts: dict[str, dict[str, object]],
) -> CapabilityContractOutput:
    return CapabilityContractOutput.model_validate(
        {
            "version": "capability_contract.v0",
            "contract_drafts": drafts,
            "capability_plans": {
                key: {
                    "enabled": bool(drafts.get(key, {}).get("enabled", False)),
                    "why": f"{key} capability follows Runtime Design.",
                    "what": {"contract": key},
                    "strategy": {"runtime": "Use standard RuntimeContract builder."},
                    "risks": [],
                    "deferred_decisions": [],
                }
                for key in STANDARD_CAPABILITY_SYSTEMS
            },
            "tool_specs_to_generate": [],
            "package_nodes_to_generate": [],
            "prompts_to_generate": [],
            "bindings_to_generate": [],
            "resources_required": [],
            "sandbox_requirements": [],
            "capability_summary_text": "Use registry-valid contract drafts.",
            "risks": [],
            "deferred_decisions": [],
        }
    )


if __name__ == "__main__":
    unittest.main()
