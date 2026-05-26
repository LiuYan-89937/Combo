from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from types import SimpleNamespace

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
    TOOL_MANUFACTURING_NODE_ID,
)
from agent_factory.factory_package.package_build import build_agent_package, default_package_build_plan, merge_package_build_plan
from agent_factory.factory_package.runtime_design import validate_runtime_design
from agent_factory.factory_package.schemas import (
    CapabilityContractOutput,
    InheritedExtensionArtifact,
    PackageBuildModelPlan,
    ProductBriefOutput,
    RuntimeDesignOutput,
    ToolDesign,
    ToolManufacturingOutput,
    ToolSourceDecision,
    ToolTrialPlan,
)
from agent_factory.factory_package.nodes import factory_manufacturing_node_provider
from agent_factory.factory_package.tool_manufacturing import (
    approved_package_tool_plans,
    default_tool_manufacturing_output,
    resolve_inherited_extensions,
    validate_tool_manufacturing_output,
)
from agent_factory.factory_package import tool_manufacturing as tool_manufacturing_module
from agent_factory.prompts import PromptId, get_prompt
from agent_factory.package_runtime import host_runtime_package_view, register_package_patterns
from agent_factory.runtime_contracts import AgentPackageLoader, RuntimeBuildPlanner
from agent_factory.runtime_contracts.builtins import default_runtime_contract_registry
from agent_factory.runtime_kernel.kernel import RuntimeKernelFacade
from agent_factory.runtime_kernel.persistence import LangGraphCheckpointerConfig, LangGraphStoreConfig
from agent_factory.factory_graph.frontend_bridge.agent_package_runtime import _seed_package_extensions


class FactoryCreateAgentSystemPackageTest(unittest.TestCase):
    def test_system_package_manifest_contracts_and_pattern_are_loadable(self) -> None:
        package = AgentPackageLoader().load_path("SystemPackage/factory_create_agent/agent_package.json")

        self.assertEqual(package.assembly_spec.agent.id, "factory_create_agent")
        self.assertEqual(package.manifest.runtime.get("system_package"), True)
        self.assertEqual(package.manifest.runtime.get("execution_backend"), "host")
        self.assertEqual([pattern.pattern_id for pattern in package.patterns], ["factory_manufacturing"])
        self.assertEqual(
            [node.id for node in package.patterns[0].nodes],
            [
                PRODUCT_BRIEF_NODE_ID,
                RUNTIME_DESIGN_NODE_ID,
                CAPABILITY_CONTRACT_NODE_ID,
                TOOL_MANUFACTURING_NODE_ID,
                PACKAGE_BUILD_NODE_ID,
            ],
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
                f"builtin.factory.{TOOL_MANUFACTURING_NODE_ID}",
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
                [
                    PRODUCT_BRIEF_NODE_ID,
                    RUNTIME_DESIGN_NODE_ID,
                    CAPABILITY_CONTRACT_NODE_ID,
                    TOOL_MANUFACTURING_NODE_ID,
                    PACKAGE_BUILD_NODE_ID,
                ],
            )

    def test_tool_manufacturing_default_handles_no_tool_requirements(self) -> None:
        runtime_design = _runtime_design_fixture()
        drafts = capability_contract_catalog_payload(runtime_design)["default_contract_drafts"]
        contract = _valid_capability_contract(runtime_design, drafts)

        output = default_tool_manufacturing_output(contract)

        self.assertEqual(output.version, "tool_manufacturing.v0")
        self.assertEqual(output.report.status, "valid")
        self.assertEqual(output.approved_package_tools, [])

    def test_package_build_model_plan_cannot_emit_package_tools(self) -> None:
        with self.assertRaises(Exception):
            PackageBuildModelPlan.model_validate(
                {
                    "version": "package_build_plan.v0",
                    "package_id": "agent_test",
                    "agent_id": "agent_test",
                    "agent_name": "Agent Test",
                    "agent_description": "Test package build model plan.",
                    "package_tools": [],
                }
            )

    def test_package_build_consumes_only_approved_tool_artifacts(self) -> None:
        runtime_design = _runtime_design_fixture()
        contract = _valid_capability_contract(
            runtime_design,
            capability_contract_catalog_payload(runtime_design)["default_contract_drafts"],
        )
        base = default_package_build_plan(
            factory_run_id="tool_approval_run",
            product_brief=_product_brief_fixture(),
            runtime_design=runtime_design,
            capability_contract=contract,
        )
        model_plan = PackageBuildModelPlan.model_validate(
            {key: value for key, value in base.model_dump(mode="json").items() if key != "package_tools"}
        )
        tool_output = ToolManufacturingOutput.model_validate(
            {
                "version": "tool_manufacturing.v0",
                "source_decisions": [
                    {
                        "tool_id": "deliver_report",
                        "source": "package_generated",
                        "rationale": "Agent-specific delivery behavior.",
                        "required_by_nodes": ["answer"],
                    }
                ],
                "tool_designs": [
                    {
                        "tool_id": "deliver_report",
                        "purpose": "Return report delivery status.",
                        "input_semantics": "Receives report text.",
                        "output_semantics": "Returns delivery status.",
                        "failure_semantics": "Returns schema-valid failure details.",
                    }
                ],
                "tool_specs": [
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
                        "risk_level": "low",
                    }
                ],
                "implementations": [
                    {
                        "tool_id": "deliver_report",
                        "code": "def run(arguments: dict, resources: dict) -> dict:\n    return {'status': 'delivered'}\n",
                    }
                ],
                "trial_plans": [
                    {
                        "tool_id": "deliver_report",
                        "scenarios": [
                            {
                                "scenario_id": "success",
                                "user_prompt": "Call deliver_report with report='ok'.",
                                "expected_tool_id": "deliver_report",
                                "arguments": {"report": "ok"},
                                "resources": {},
                                "expected_observation_status": "completed",
                                "expected_output_keys": ["status"],
                            }
                        ],
                    }
                ],
                "approved_package_tools": [
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
                        "python_requirements": [],
                        "system_packages": [],
                        "system_binaries": [],
                        "code": "def run(arguments: dict, resources: dict) -> dict:\n    return {'status': 'delivered'}\n",
                        "manufacturing_status": "approved",
                    }
                ],
                "report": {
                    "status": "valid",
                    "approved_tool_ids": ["deliver_report"],
                },
            }
        )

        merged = merge_package_build_plan(
            base=base,
            model_plan=model_plan,
            approved_package_tools=approved_package_tool_plans(tool_output),
        )

        self.assertEqual([item.tool_id for item in merged.package_tools], ["deliver_report"])

    def test_tool_trial_plan_rejects_model_owned_test_code(self) -> None:
        with self.assertRaises(Exception):
            ToolTrialPlan.model_validate(
                {
                    "tool_id": "deliver_report",
                    "pytest_code": "from deliver_report import run\n",
                }
            )

    def test_tool_trial_plan_accepts_model_bound_scenario(self) -> None:
        plan = ToolTrialPlan.model_validate(
            {
                "tool_id": "fetch_market_data",
                "scenarios": [
                    {
                        "scenario_id": "timeout",
                        "user_prompt": "Call fetch_market_data for 000001.SS and summarize the result.",
                        "expected_tool_id": "fetch_market_data",
                        "arguments": {"symbols": ["000001.SS"]},
                        "resources": {"market_data_api_key": "test"},
                        "expected_observation_status": "completed",
                        "expected_output_keys": ["status"],
                        "expected_output_subset": {"status": "error", "retryable": True},
                        "success_criteria": ["The model emits fetch_market_data as a tool call."],
                    }
                ],
            }
        )

        self.assertEqual(plan.scenarios[0].expected_tool_id, "fetch_market_data")
        self.assertEqual(plan.scenarios[0].expected_output_keys, ["status"])
        self.assertEqual(plan.scenarios[0].expected_output_subset, {"status": "error", "retryable": True})

    def test_tool_manufacturing_resolves_enabled_factory_skill_for_inheritance(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            extension_root = root / "factory_extensions"
            skill_root = extension_root / "skills" / "weather"
            skill_root.mkdir(parents=True)
            (skill_root / "SKILL.md").write_text("# Weather\n", encoding="utf-8")
            (extension_root / "enabled_skills.json").write_text(
                json.dumps(
                    {
                        "version": "enabled_skills.v0",
                        "skills": [{"skill_id": "weather", "path": "skills/weather", "enabled": True}],
                    }
                ),
                encoding="utf-8",
            )
            decision = ToolSourceDecision(
                tool_id="weather_lookup",
                source="skill",
                inherited_extensions=[{"source": "skill", "extension_id": "weather"}],
                rationale="Reuse the configured weather skill.",
                required_by_nodes=["answer"],
            )

            with (
                patch.object(tool_manufacturing_module, "default_factory_extension_root", return_value=extension_root),
                patch.object(tool_manufacturing_module, "project_root", return_value=root),
            ):
                artifacts = resolve_inherited_extensions([decision])

            self.assertEqual(len(artifacts), 1)
            self.assertEqual(artifacts[0].source, "skill")
            self.assertEqual(artifacts[0].extension_id, "weather")
            self.assertEqual(artifacts[0].config["path"], "skills/weather")
            self.assertEqual(Path(str(artifacts[0].source_path)), skill_root.resolve())

    def test_tool_manufacturing_rejects_missing_inherited_extension(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            decision = ToolSourceDecision(
                tool_id="weather_lookup",
                source="skill",
                inherited_extensions=[{"source": "skill", "extension_id": "weather"}],
                rationale="Reuse the configured weather skill.",
                required_by_nodes=["answer"],
            )

            with (
                patch.object(tool_manufacturing_module, "default_factory_extension_root", return_value=root / "missing"),
                patch.object(tool_manufacturing_module, "project_root", return_value=root),
                self.assertRaisesRegex(Exception, "inherited extension not found: skill:weather"),
            ):
                resolve_inherited_extensions([decision])

    def test_package_build_materializes_inherited_skill_extension(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            skill_root = root / "source_skill"
            skill_root.mkdir()
            (skill_root / "SKILL.md").write_text("# Weather\n", encoding="utf-8")
            runtime_design = _runtime_design_fixture()
            drafts = capability_contract_catalog_payload(runtime_design)["default_contract_drafts"]
            contract = _valid_capability_contract(runtime_design, drafts)
            plan = default_package_build_plan(
                factory_run_id="inherited_skill_factory_run",
                product_brief=_product_brief_fixture(),
                runtime_design=runtime_design,
                capability_contract=contract,
            )
            tool_output = ToolManufacturingOutput(
                inherited_extensions=[
                    InheritedExtensionArtifact(
                        source="skill",
                        extension_id="weather",
                        config={"skill_id": "weather", "path": "skills/weather", "enabled": True},
                        source_path=str(skill_root),
                        target_path="extensions/skills/weather",
                    )
                ],
                report={"status": "valid"},
            )

            result = build_agent_package(
                plan=plan,
                product_brief=_product_brief_fixture(),
                runtime_design=runtime_design,
                capability_contract=contract,
                tool_manufacturing=tool_output,
                output_root=root / "packages",
            )

            self.assertEqual(result.report.status, "valid", result.report.errors)
            package_root = Path(result.report.package_root)
            skill_config = json.loads((package_root / "extensions" / "enabled_skills.json").read_text(encoding="utf-8"))
            self.assertEqual(skill_config["skills"][0]["skill_id"], "weather")
            self.assertEqual(skill_config["skills"][0]["path"], "skills/weather")
            self.assertEqual((package_root / "extensions" / "skills" / "weather" / "SKILL.md").read_text(encoding="utf-8"), "# Weather\n")

    def test_runtime_seeds_package_extensions_without_overwriting_user_runtime_extensions(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package_root = root / "package"
            runtime_root = root / "runtime_extensions"
            (package_root / "extensions" / "skills" / "weather").mkdir(parents=True)
            (package_root / "extensions" / "skills" / "weather" / "SKILL.md").write_text("# Weather\n", encoding="utf-8")
            (package_root / "extensions" / "enabled_skills.json").write_text(
                json.dumps(
                    {
                        "version": "enabled_skills.v0",
                        "skills": [{"skill_id": "weather", "path": "skills/weather", "enabled": True}],
                    }
                ),
                encoding="utf-8",
            )
            runtime_root.mkdir()
            (runtime_root / "enabled_skills.json").write_text(
                json.dumps(
                    {
                        "version": "enabled_skills.v0",
                        "skills": [{"skill_id": "custom", "path": "skills/custom", "enabled": True}],
                    }
                ),
                encoding="utf-8",
            )

            _seed_package_extensions(package=SimpleNamespace(package_root=package_root), extension_root=runtime_root)

            merged = json.loads((runtime_root / "enabled_skills.json").read_text(encoding="utf-8"))
            self.assertEqual([item["skill_id"] for item in merged["skills"]], ["custom", "weather"])
            self.assertEqual((runtime_root / "skills" / "weather" / "SKILL.md").read_text(encoding="utf-8"), "# Weather\n")

    def test_tool_manufacturing_source_decision_is_not_locked_by_capability_hint(self) -> None:
        runtime_design = _runtime_design_fixture()
        drafts = capability_contract_catalog_payload(runtime_design)["default_contract_drafts"]
        base_contract = _valid_capability_contract(runtime_design, drafts)
        contract = CapabilityContractOutput.model_validate(
            {
                **base_contract.model_dump(mode="json"),
                "tool_specs_to_generate": [
                    {
                        "tool_id": "weather_lookup",
                        "purpose": "Look up weather from an existing extension.",
                        "source": "package_generated",
                        "required_by_nodes": ["answer"],
                        "risk_level": "low",
                    }
                ],
            }
        )
        output = ToolManufacturingOutput(
            source_decisions=[
                ToolSourceDecision(
                    tool_id="weather_lookup",
                    source="skill",
                    inherited_extensions=[{"source": "skill", "extension_id": "weather"}],
                    rationale="The configured weather skill already owns this capability.",
                    required_by_nodes=["answer"],
                )
            ],
            report={"status": "valid"},
        )

        errors = validate_tool_manufacturing_output(output=output, capability_contract=contract)

        self.assertEqual(errors, [])

    def test_tool_manufacturing_rejects_package_generated_without_required_artifacts(self) -> None:
        runtime_design = _runtime_design_fixture()
        drafts = capability_contract_catalog_payload(runtime_design)["default_contract_drafts"]
        base_contract = _valid_capability_contract(runtime_design, drafts)
        contract = CapabilityContractOutput.model_validate(
            {
                **base_contract.model_dump(mode="json"),
                "tool_specs_to_generate": [
                    {
                        "tool_id": "deliver_report",
                        "purpose": "Deliver a report.",
                        "source": None,
                        "required_by_nodes": ["answer"],
                        "risk_level": "low",
                    }
                ],
            }
        )
        output = ToolManufacturingOutput(
            source_decisions=[
                ToolSourceDecision(
                    tool_id="deliver_report",
                    source="package_generated",
                    rationale="Agent-specific behavior.",
                    required_by_nodes=["answer"],
                )
            ],
            report={"status": "valid"},
        )

        errors = validate_tool_manufacturing_output(output=output, capability_contract=contract)

        self.assertTrue(any("missing manufacturing artifacts" in error for error in errors))

    def test_tool_design_uses_explicit_resource_bindings_not_reversed_selector_map(self) -> None:
        design = ToolDesign.model_validate(
            {
                "tool_id": "fetch_stock_news",
                "purpose": "Fetch stock news.",
                "input_semantics": "Reads optional filters and configured resources.",
                "output_semantics": "Returns normalized news items.",
                "failure_semantics": "Returns structured failures.",
                "resource_bindings": [
                    {
                        "local_name": "news_sources",
                        "selector": "report_config.news_sources",
                        "purpose": "Configured news sources.",
                    }
                ],
            }
        )

        self.assertEqual(design.resource_bindings[0].local_name, "news_sources")
        self.assertEqual(design.resource_bindings[0].selector, "report_config.news_sources")

    def test_tool_design_rejects_legacy_reversed_resource_selectors(self) -> None:
        with self.assertRaises(Exception):
            ToolDesign.model_validate(
                {
                    "tool_id": "fetch_stock_news",
                    "purpose": "Fetch stock news.",
                    "input_semantics": "Reads optional filters and configured resources.",
                    "output_semantics": "Returns normalized news items.",
                    "failure_semantics": "Returns structured failures.",
                    "resource_selectors": {"report_config.news_sources": "默认新闻源列表"},
                }
            )

    def test_tool_manufacturing_prompts_do_not_expose_literal_examples_as_variables(self) -> None:
        expected_variables = {
            PromptId.TOOL_DESIGN_DRAFT: {
                "product_brief",
                "runtime_design",
                "tool_requirement",
                "source_decision",
                "resource_requirements",
                "user_external_resources",
                "validation_feedback",
                "output_json_schema",
            },
            PromptId.TOOL_SPEC_DRAFT: {
                "tool_requirement",
                "source_decision",
                "tool_design",
                "resource_requirements",
                "user_external_resources",
                "validation_feedback",
                "output_json_schema",
            },
        }

        for prompt_id, variables in expected_variables.items():
            with self.subTest(prompt_id=prompt_id):
                self.assertEqual(set(get_prompt(prompt_id).input_variables), variables)

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

    def test_package_build_separates_resource_descriptions_from_runtime_values(self) -> None:
        with TemporaryDirectory() as temp_dir:
            product_brief = ProductBriefOutput.model_validate(
                {
                    "version": "product_brief.v0",
                    "working_title": "Reporter",
                    "agent_goal": "Prepare a report from configured runtime resources.",
                    "target_user": "Local CLI user",
                    "first_version_scope": "Generate a report from runtime resource configuration.",
                    "primary_workflow": "Answer with configured report inputs.",
                    "autonomy_boundary": "Use configured resources only.",
                    "human_review_boundary": "Ask before risky operations.",
                    "resource_boundary": "Use runtime resources only.",
                    "expected_outputs": ["Report text"],
                    "success_criteria": ["Resource descriptors and values are separated"],
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
                    "resources_required": [
                        {
                            "resource_id": "report_config",
                            "description": "Runtime report configuration.",
                            "required": True,
                            "expected_shape": "Object containing API keys, sources, symbols, and output dir.",
                            "value_schema": {
                                "type": "object",
                                "properties": {
                                    "news_api_key": {"type": "string"},
                                    "news_sources": {"type": "array", "items": {"type": "string"}},
                                    "market_symbols": {"type": "array", "items": {"type": "string"}},
                                    "report_output_dir": {"type": "string", "default": "/artifacts/reports"},
                                },
                                "additionalProperties": False,
                            },
                            "default_value": {
                                "news_api_key": "",
                                "news_sources": [],
                                "market_symbols": ["000001.SS"],
                                "report_output_dir": "/artifacts/reports",
                            },
                            "secret_fields": ["news_api_key"],
                            "sandbox_access_expectation": "Container-visible runtime configuration.",
                            "used_by": ["answer"],
                        }
                    ],
                }
            )
            plan = default_package_build_plan(
                factory_run_id="resource_factory_run",
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
            package_root = Path(result.report.package_root)
            resources = json.loads((package_root / "resources.json").read_text(encoding="utf-8"))
            self.assertEqual(
                resources["resources"]["report_config"],
                {
                    "news_api_key": "",
                    "news_sources": [],
                    "market_symbols": ["000001.SS"],
                    "report_output_dir": "/artifacts/reports",
                },
            )
            resource_contract = json.loads((package_root / "contracts" / "resources.json").read_text(encoding="utf-8"))
            descriptor = resource_contract["config"]["resource_descriptors"][0]
            self.assertEqual(descriptor["resource_id"], "report_config")
            self.assertEqual(descriptor["description"], "Runtime report configuration.")
            self.assertIn("news_api_key", descriptor["value_schema"]["properties"])
            self.assertEqual(descriptor["default_value"]["report_output_dir"], "/artifacts/reports")
            self.assertEqual(descriptor["secret_fields"], ["news_api_key"])

    def test_package_build_derives_resource_values_from_schema_defaults(self) -> None:
        with TemporaryDirectory() as temp_dir:
            product_brief = ProductBriefOutput.model_validate(
                {
                    "version": "product_brief.v0",
                    "working_title": "Reporter",
                    "agent_goal": "Prepare a report from configured runtime resources.",
                    "target_user": "Local CLI user",
                    "first_version_scope": "Generate a report from runtime resource configuration.",
                    "primary_workflow": "Answer with configured report inputs.",
                    "autonomy_boundary": "Use configured resources only.",
                    "human_review_boundary": "Ask before risky operations.",
                    "resource_boundary": "Use runtime resources only.",
                    "expected_outputs": ["Report text"],
                    "success_criteria": ["Resource defaults satisfy resource schema"],
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
                    "resources_required": [
                        {
                            "resource_id": "report_config",
                            "description": "Runtime report configuration.",
                            "required": True,
                            "expected_shape": "Object containing symbols and style.",
                            "value_schema": {
                                "type": "object",
                                "properties": {
                                    "symbols": {"type": "array", "items": {"type": "string"}},
                                    "style": {"type": "string", "default": "concise"},
                                },
                                "required": ["symbols", "style"],
                                "additionalProperties": False,
                            },
                            "default_value": {"symbols": ["000001.SS"]},
                            "secret_fields": [],
                            "sandbox_access_expectation": "Container-visible runtime configuration.",
                            "used_by": ["answer"],
                        }
                    ],
                }
            )
            plan = default_package_build_plan(
                factory_run_id="resource_schema_factory_run",
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
            resources = json.loads((Path(result.report.package_root) / "resources.json").read_text(encoding="utf-8"))
            self.assertEqual(
                resources["resources"]["report_config"],
                {"symbols": ["000001.SS"], "style": "concise"},
            )

    def test_package_build_rejects_state_fields_that_duplicate_resources(self) -> None:
        with TemporaryDirectory() as temp_dir:
            product_brief = ProductBriefOutput.model_validate(
                {
                    "version": "product_brief.v0",
                    "working_title": "Reporter",
                    "agent_goal": "Prepare a report from configured runtime resources.",
                    "target_user": "Local CLI user",
                    "first_version_scope": "Generate a report from runtime resource configuration.",
                    "primary_workflow": "Answer with configured report inputs.",
                    "autonomy_boundary": "Use configured resources only.",
                    "human_review_boundary": "Ask before risky operations.",
                    "resource_boundary": "Use runtime resources only.",
                    "expected_outputs": ["Report text"],
                    "success_criteria": ["Resource fields are not duplicated in package state"],
                    "out_of_scope": [],
                    "manufacturing_assumptions": [],
                    "blocking_questions": [],
                    "business_plan_text": "Create a report-capable assistant.",
                    "ready_for_runtime_design": True,
                }
            )
            runtime_design = RuntimeDesignOutput.model_validate(
                {
                    **_runtime_design_fixture().model_dump(mode="json"),
                    "state_namespaces": [
                        {
                            "namespace": "user_config",
                            "purpose": "Store confirmation state for runtime configuration.",
                            "owned_by_nodes": ["approval_gate"],
                            "initial_shape": {"watchlist": [], "confirmed": False},
                        }
                    ],
                }
            )
            drafts = capability_contract_catalog_payload(runtime_design)["default_contract_drafts"]
            base_contract = _valid_capability_contract(runtime_design, drafts)
            contract = CapabilityContractOutput.model_validate(
                {
                    **base_contract.model_dump(mode="json"),
                    "resources_required": [
                        {
                            "resource_id": "report_config",
                            "description": "Runtime report configuration.",
                            "required": True,
                            "expected_shape": "Object containing symbols.",
                            "value_schema": {
                                "type": "object",
                                "properties": {"watchlist": {"type": "array", "items": {"type": "string"}}},
                                "required": ["watchlist"],
                                "additionalProperties": False,
                            },
                            "default_value": {"watchlist": []},
                            "secret_fields": [],
                            "sandbox_access_expectation": "Container-visible runtime configuration.",
                            "used_by": ["answer"],
                        }
                    ],
                }
            )
            plan = default_package_build_plan(
                factory_run_id="state_resource_overlap_factory_run",
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

            self.assertEqual(result.report.status, "invalid")
            self.assertTrue(any("duplicates runtime resource fields" in error for error in result.report.errors))

    def test_package_build_rejects_dependencies_modeled_as_sandbox_services(self) -> None:
        with TemporaryDirectory() as temp_dir:
            product_brief = ProductBriefOutput.model_validate(
                {
                    "version": "product_brief.v0",
                    "working_title": "Reporter",
                    "agent_goal": "Prepare reports with a generated data tool.",
                    "target_user": "Local CLI user",
                    "first_version_scope": "Generate a report.",
                    "primary_workflow": "Answer, call the data tool when needed, and return the result.",
                    "autonomy_boundary": "Use configured tools only.",
                    "human_review_boundary": "Ask before risky operations.",
                    "resource_boundary": "Use runtime resources only.",
                    "expected_outputs": ["Report text"],
                    "success_criteria": ["Dependencies are not modeled as services"],
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
                    "sandbox_requirements": [
                        {
                            "requirement_id": "data_runtime",
                            "description": "Need network and Python dependencies for data retrieval.",
                            "network_required": True,
                            "mounts_required": [],
                            "secrets_required": [],
                            "services_required": ["python_requests"],
                        }
                    ],
                }
            )
            base_plan = default_package_build_plan(
                factory_run_id="dependency_service_factory_run",
                product_brief=product_brief,
                runtime_design=runtime_design,
                capability_contract=contract,
            )
            plan = type(base_plan).model_validate(
                {
                    **base_plan.model_dump(mode="json"),
                    "package_tools": [
                        {
                            "tool_id": "fetch_data",
                            "description": "Fetch remote data.",
                            "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
                            "output_schema": {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]},
                            "resources": {},
                            "risk_level": "low",
                            "concurrent": True,
                            "python_requirements": ["requests"],
                            "system_packages": [],
                            "system_binaries": [],
                            "code": (
                                "import requests\n\n"
                                "def run(arguments: dict, resources: dict) -> dict:\n"
                                "    return {\"ok\": True}\n"
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

            self.assertEqual(result.report.status, "invalid")
            self.assertTrue(any("dependency-like service" in error for error in result.report.errors))

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

    def test_runtime_design_rejects_reserved_package_state_namespace(self) -> None:
        with self.assertRaises(ValueError):
            RuntimeDesignOutput.model_validate(
                {
                    **_runtime_design_fixture().model_dump(mode="json"),
                    "state_namespaces": [
                        {
                            "namespace": "messages",
                            "purpose": "This must stay in LangGraph messages.",
                            "owned_by_nodes": ["answer"],
                        }
                    ],
                }
            )

    def test_runtime_design_validates_required_pattern_slots(self) -> None:
        design = RuntimeDesignOutput.model_validate(
            {
                "version": "runtime_design.v0",
                "design_mode": "reuse_pattern",
                "selected_pattern_id": "scheduled_react_report",
                "graph_intent": "Build a scheduled market report agent.",
                "nodes": [
                    {
                        "node_id": "answer",
                        "node_type": "cognitive",
                        "impl": "cognitive.answer",
                        "purpose": "Generate reports and request data tools.",
                        "model_operation": "tool_bound_chat",
                        "requires_tools": True,
                    },
                    {
                        "node_id": "tool_exec",
                        "node_type": "operational",
                        "impl": "operational.tool_call",
                        "purpose": "Execute model requested tools.",
                    },
                ],
                "required_contracts": ["model", "tools", "resources", "scheduler", "artifact", "context", "trace"],
                "pattern_slots": [
                    {
                        "slot_id": "recurring_report_request",
                        "slot_type": "scheduler",
                        "required_by_nodes": ["ingress"],
                        "purpose": "Run the graph daily with a report request.",
                        "source": "scheduler",
                        "binding_strategy": "Create the recurring job after runtime configuration.",
                        "binding": {
                            "kind": "scheduler",
                            "target_type": "graph_run",
                            "schedule_intent": "Every trading morning.",
                            "target_message": "请生成今日股市日报",
                        },
                    },
                    {
                        "slot_id": "answer_prompt",
                        "slot_type": "prompt",
                        "required_by_nodes": ["answer"],
                        "purpose": "Guide the daily report answer.",
                        "source": "system",
                        "binding_strategy": "Generate an answer prompt.",
                        "binding": {"kind": "prompt", "prompt_id": "daily_stock_report_prompt"},
                    },
                    {
                        "slot_id": "report_tools",
                        "slot_type": "tool",
                        "required_by_nodes": ["answer", "tool_exec"],
                        "purpose": "Provide market data and news retrieval tools.",
                        "source": "package_generated",
                        "binding_strategy": "Generate package tools and bind them to answer/tool_exec.",
                        "binding": {
                            "kind": "tool",
                            "tool_ids": ["fetch_news", "fetch_market_data"],
                            "generated_tool_ids": ["fetch_news", "fetch_market_data"],
                        },
                    },
                    {
                        "slot_id": "report_runtime_config",
                        "slot_type": "resource",
                        "required_by_nodes": ["answer"],
                        "purpose": "Hold user-configured market report settings.",
                        "source": "user_config",
                        "binding_strategy": "Store runtime values in resources.json and descriptions in resources contract.",
                        "binding": {
                            "kind": "resource",
                            "resource_id": "report_config",
                            "value_schema": {
                                "type": "object",
                                "properties": {
                                    "news_api_key": {"type": "string"},
                                    "market_symbols": {"type": "array", "items": {"type": "string"}},
                                },
                                "additionalProperties": False,
                            },
                            "default_value": {"news_api_key": "", "market_symbols": ["000001.SS"]},
                            "secret_fields": ["news_api_key"],
                        },
                    },
                ],
                "runtime_assumptions": [],
                "blocking_questions": [],
                "design_summary_text": "Use the scheduled report preset.",
            }
        )

        report = validate_runtime_design(design)

        self.assertEqual(report.status, "valid", report.errors)

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


def _product_brief_fixture() -> ProductBriefOutput:
    return ProductBriefOutput.model_validate(
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
