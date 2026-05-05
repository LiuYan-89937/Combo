from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_factory_agent import service_with_responses, valid_primitives_payload

from agent_factory.factory.package_artifacts import PackageArtifactGenerator, PackageArtifactReport
from agent_factory.factory_runtime import FactoryRunContext
from agent_factory.factory_runtime.production import FactoryProductionRuntime
from agent_factory.specs import ValidationReport, ValidationSeverity


class FactoryProductionRuntimeTests(unittest.TestCase):
    def test_clear_requirement_completes_and_writes_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            context = FactoryRunContext.create(start_path=tmpdir)
            runtime = FactoryProductionRuntime(
                model_service=service_with_responses([valid_primitives_payload()])
            )

            state = runtime.run(requirement="创建客服 Agent", context=context)

            self.assertEqual(state.status, "completed")
            self.assertIsNotNone(state.package_path)
            self.assertTrue((state.package_path / "instructions.yaml").exists())
            self.assertTrue((state.package_path / "generated" / "draft_tools" / "order_query.py").exists())
            self.assertTrue(
                (state.package_path / "generated" / "tool_tests" / "test_order_query.py").exists()
            )
            self.assertTrue((state.package_path / "mcp.yaml").exists())
            self.assertTrue((state.package_path / "harness.yaml").exists())
            self.assertTrue(state.validation_report.ok)
            self.assertEqual(state.generated_tool_count, 1)
            self.assertEqual(state.generated_tool_test_count, 1)
            self.assertEqual(state.harness_scenario_count, 3)
            self.assertIsNotNone(state.verification_report)
            self.assertEqual(state.verification_report.status, "passed")
            self.assertTrue(
                (state.package_path / "generated" / "reports" / "factory_verification.json").exists()
            )
            self.assertIn("complete", state.stage_history)

    def test_vague_requirement_needs_clarification_without_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            context = FactoryRunContext.create(start_path=tmpdir)
            runtime = FactoryProductionRuntime(
                model_service=service_with_responses([valid_primitives_payload()])
            )

            state = runtime.run(requirement="客服", context=context)

            self.assertEqual(state.status, "needs_clarification")
            self.assertGreater(len(state.clarification_questions), 0)
            self.assertIsNone(state.package_path)
            self.assertNotIn("plan_primitives", state.stage_history)
            self.assertIn("classify_factory_intent", state.stage_history)
            self.assertGreater(len(state.clarification_options), 0)

    def test_non_agent_request_returns_guidance_without_big_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            context = FactoryRunContext.create(start_path=tmpdir)
            runtime = FactoryProductionRuntime(
                model_service=service_with_responses([valid_primitives_payload()])
            )

            state = runtime.run(requirement="今天吃什么比较好", context=context)

            self.assertEqual(state.status, "not_agent_request")
            self.assertIn("AgentFactory", state.guidance_message or "")
            self.assertIsNone(state.package_path)
            self.assertEqual(state.clarification_questions, [])
            self.assertNotIn("analyze_requirement", state.stage_history)
            self.assertNotIn("plan_primitives", state.stage_history)

    def test_non_agent_request_stream_guidance_is_not_duplicated(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            context = FactoryRunContext.create(start_path=tmpdir)
            runtime = FactoryProductionRuntime(
                model_service=service_with_responses([valid_primitives_payload()])
            )

            events = list(runtime.stream(requirement="今天吃什么比较好", context=context))

            guidance_events = [
                event
                for event in events
                if "AgentFactory" in (event.message or "")
            ]
            self.assertEqual(len(guidance_events), 1)
            self.assertEqual(guidance_events[0].stage, "not_agent_request")
            self.assertEqual(events[-1].stage, "not_agent_request")

    def test_companion_agent_requirement_is_clear_without_agent_keyword(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            context = FactoryRunContext.create(start_path=tmpdir)
            runtime = FactoryProductionRuntime(
                model_service=service_with_responses([valid_primitives_payload()])
            )

            state = runtime.run(requirement="创建一个虚拟恋爱女友叫小美", context=context)

            self.assertEqual(state.status, "completed", state.error)
            self.assertEqual(state.clarification_questions, [])
            self.assertIn("plan_primitives", state.stage_history)
            self.assertEqual(state.factory_intent["intent"], "create_agent_clear")
            self.assertIsNotNone(state.requirement_analysis)
            self.assertEqual(state.requirement_analysis["safety_profile"], "companion_agent")

    def test_requirement_analysis_fallback_keeps_graph_running_without_model_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path.cwd()
            os.chdir(tmpdir)
            try:
                context = FactoryRunContext.create(start_path=tmpdir)
                runtime = FactoryProductionRuntime()

                with patch.dict(os.environ, {}, clear=True):
                    state = runtime.run(requirement="创建一个虚拟恋爱女友叫小美", context=context)
            finally:
                os.chdir(cwd)

            self.assertIn("plan_primitives", state.stage_history)
            self.assertEqual(state.requirement_analysis["safety_profile"], "companion_agent")
            self.assertIn(state.error.code, {"model_config_error", "provider_network_error"})

    def test_invalid_primitives_are_repaired_once(self) -> None:
        invalid = valid_primitives_payload()
        invalid["instructions"] = {**invalid["instructions"], "goal": ""}
        with tempfile.TemporaryDirectory() as tmpdir:
            context = FactoryRunContext.create(start_path=tmpdir)
            runtime = FactoryProductionRuntime(
                model_service=service_with_responses([invalid, valid_primitives_payload()])
            )

            state = runtime.run(requirement="创建客服 Agent", context=context)

            self.assertEqual(state.status, "completed", state.error)
            self.assertEqual(state.repair_attempts, 1)
            self.assertIn("repair_primitives", state.stage_history)

    def test_repaired_primitives_normalize_observability_sensitive_fields(self) -> None:
        repaired = valid_primitives_payload()
        repaired["observability"] = {
            **repaired["observability"],
            "forbidden_fields": [
                "api_key",
                "secret",
                "authorization",
                "auth_header }",
                "tool_auth_token",
            ],
            "allowed_sensitive_fields": ["auth_header", "safe_public_field"],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            context = FactoryRunContext.create(start_path=tmpdir)
            runtime = FactoryProductionRuntime(
                model_service=service_with_responses(
                    ['["Only manage customer_tickets and status values"]', repaired]
                )
            )

            state = runtime.run(requirement="创建客服 Agent", context=context)

            self.assertEqual(state.status, "completed", state.error)
            self.assertEqual(state.repair_attempts, 1)
            self.assertEqual(
                state.primitives.observability.forbidden_fields,
                [
                    "api_key",
                    "secret",
                    "authorization",
                    "auth_header",
                    "tool_auth_token",
                ],
            )
            self.assertEqual(state.primitives.observability.allowed_sensitive_fields, ["safe_public_field"])

    def test_repair_limit_failure(self) -> None:
        invalid = valid_primitives_payload()
        invalid["instructions"] = {**invalid["instructions"], "goal": ""}
        with tempfile.TemporaryDirectory() as tmpdir:
            context = FactoryRunContext.create(start_path=tmpdir)
            runtime = FactoryProductionRuntime(
                model_service=service_with_responses([invalid, invalid])
            )

            state = runtime.run(requirement="创建客服 Agent", context=context)

            self.assertEqual(state.status, "failed")
            self.assertEqual(state.repair_attempts, 1)
            self.assertEqual(state.error.code, "primitive_schema_validation_failed")

    def test_package_validator_failure_fails_graph(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            context = FactoryRunContext.create(start_path=tmpdir)
            runtime = FactoryProductionRuntime(
                model_service=service_with_responses([valid_primitives_payload()]),
                package_writer=FailingPackageWriter(),
            )

            state = runtime.run(requirement="创建客服 Agent", context=context)

            self.assertEqual(state.status, "failed")
            self.assertEqual(state.error.code, "package_validation_failed")
            self.assertIn("generate_harness_scenarios", state.stage_history)
            self.assertIn("validate_package", state.stage_history)

    def test_static_check_failure_fails_graph(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            context = FactoryRunContext.create(start_path=tmpdir)
            runtime = FactoryProductionRuntime(
                model_service=service_with_responses([valid_primitives_payload()]),
                artifact_generator=SyntaxErrorArtifactGenerator(),
            )

            state = runtime.run(requirement="创建客服 Agent", context=context)

            self.assertEqual(state.status, "failed")
            self.assertEqual(state.error.code, "tool_static_check_failed")
            self.assertEqual(state.tool_static_check_report.status, "failed")
            self.assertIn("static_check_tool_scripts", state.stage_history)

    def test_generated_tool_test_failure_completes_with_warnings_after_repair(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            context = FactoryRunContext.create(start_path=tmpdir)
            runtime = FactoryProductionRuntime(
                model_service=service_with_responses([valid_primitives_payload()]),
                artifact_generator=FailingToolTestArtifactGenerator(),
            )

            state = runtime.run(requirement="创建客服 Agent", context=context)

            self.assertEqual(state.status, "completed_with_warnings")
            self.assertIsNone(state.error)
            self.assertEqual(state.tool_test_report.status, "passed_with_warnings")
            self.assertEqual(state.verification_report.status, "passed_with_warnings")
            self.assertEqual(state.tool_test_repair_attempts, 1)
            self.assertIn("repair_tool_tests", state.stage_history)
            self.assertIn("run_generated_tool_tests", state.stage_history)
            self.assertEqual(state.stage_history[-1], "complete")

    def test_generated_tool_test_failure_repairs_and_reruns(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            context = FactoryRunContext.create(start_path=tmpdir)
            runtime = FactoryProductionRuntime(
                model_service=service_with_responses([valid_primitives_payload()]),
                artifact_generator=RepairableBrittleToolTestArtifactGenerator(),
            )

            state = runtime.run(requirement="创建客服 Agent", context=context)

            self.assertEqual(state.status, "completed", state.error)
            self.assertEqual(state.tool_test_repair_attempts, 1)
            self.assertIn("repair_tool_tests", state.stage_history)
            self.assertEqual(state.tool_test_report.status, "passed")

    def test_duplicate_mcp_binding_fails_graph(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            context = FactoryRunContext.create(start_path=tmpdir)
            runtime = FactoryProductionRuntime(
                model_service=service_with_responses([valid_primitives_payload()]),
                artifact_generator=DuplicateMCPArtifactGenerator(),
            )

            state = runtime.run(requirement="创建客服 Agent", context=context)

            self.assertEqual(state.status, "failed")
            self.assertEqual(state.error.code, "mcp_binding_local_check_failed")
            self.assertEqual(state.mcp_binding_report.status, "failed")
            self.assertIn("validate_mcp_bindings_local", state.stage_history)

    def test_duplicate_harness_scenario_fails_graph(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            context = FactoryRunContext.create(start_path=tmpdir)
            runtime = FactoryProductionRuntime(
                model_service=service_with_responses([valid_primitives_payload()]),
                artifact_generator=DuplicateHarnessArtifactGenerator(),
            )

            state = runtime.run(requirement="创建客服 Agent", context=context)

            self.assertEqual(state.status, "failed")
            self.assertEqual(state.error.code, "harness_dry_run_failed")
            self.assertEqual(state.harness_dry_run_report.status, "failed")
            self.assertIn("dry_run_harness_scenarios", state.stage_history)

    def test_no_tool_agent_skips_tool_checks_and_completes(self) -> None:
        payload = valid_primitives_payload()
        payload["toolsets"] = {
            **payload["toolsets"],
            "toolsets": [],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            context = FactoryRunContext.create(start_path=tmpdir)
            runtime = FactoryProductionRuntime(
                model_service=service_with_responses([payload])
            )

            state = runtime.run(requirement="创建客服 Agent", context=context)

            self.assertEqual(state.status, "completed")
            self.assertEqual(state.tool_static_check_report.status, "skipped")
            self.assertEqual(state.tool_test_report.status, "skipped")
            self.assertEqual(state.mcp_binding_report.status, "skipped")
            self.assertEqual(state.harness_dry_run_report.status, "passed")

    def test_stream_yields_progress_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            context = FactoryRunContext.create(start_path=tmpdir)
            runtime = FactoryProductionRuntime(
                model_service=service_with_responses([valid_primitives_payload()])
            )

            events = list(runtime.stream(requirement="创建客服 Agent", context=context))

            self.assertGreaterEqual(len(events), 5)
            self.assertEqual(events[-1].stage, "complete")
            self.assertEqual(events[-1].status, "completed")
            self.assertIn("generate_tool_scripts", [event.stage for event in events])
            self.assertIn("generate_harness_scenarios", [event.stage for event in events])
            self.assertIn("run_generated_tool_tests", [event.stage for event in events])
            self.assertIn("dry_run_harness_scenarios", [event.stage for event in events])

    def test_tool_generation_issues_fail_fast(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            context = FactoryRunContext.create(start_path=tmpdir)
            runtime = FactoryProductionRuntime(
                model_service=service_with_responses([valid_primitives_payload()]),
                artifact_generator=ToolGenerationIssueArtifactGenerator(),
            )

            events = list(runtime.stream(requirement="创建客服 Agent", context=context))
            generation_events = [event for event in events if event.stage == "generate_tool_scripts"]
            generation_event = generation_events[-1]

            self.assertEqual(generation_event.status.value, "failed")
            self.assertIn("tool generation fell back", generation_event.message or "")
            self.assertEqual(events[-1].stage, "failed")


class FailingPackageWriter:
    def write_primitives(self, output_dir: Path, primitives: object) -> ValidationReport:
        output_dir.mkdir(parents=True, exist_ok=True)
        report = ValidationReport(root_path=output_dir)
        report.add(
            ValidationSeverity.FATAL,
            "forced_validation_failure",
            "forced failure",
        )
        return report


class SyntaxErrorArtifactGenerator(PackageArtifactGenerator):
    def generate_tool_scripts(self, package_path, primitives, **kwargs):
        report = super().generate_tool_scripts(package_path, primitives, **kwargs)
        bad_path = package_path / "generated" / "draft_tools" / "broken.py"
        bad_path.write_text("def broken(:\n    pass\n", encoding="utf-8")
        report.artifact_paths.append(bad_path)
        return report


class FailingToolTestArtifactGenerator(PackageArtifactGenerator):
    def generate_tool_tests(self, package_path, primitives):
        report = super().generate_tool_tests(package_path, primitives)
        test_path = package_path / "generated" / "tool_tests" / "test_order_query.py"
        test_path.write_text(
            "import unittest\n\n"
            "class FailingGeneratedToolTest(unittest.TestCase):\n"
            "    def test_failure(self):\n"
            "        self.fail('forced failure')\n",
            encoding="utf-8",
        )
        return report

    def repair_generated_tool_tests(self, package_path, primitives, **kwargs):
        return self.generate_tool_tests(package_path, primitives)


class RepairableBrittleToolTestArtifactGenerator(PackageArtifactGenerator):
    def generate_tool_tests(self, package_path, primitives):
        report = super().generate_tool_tests(package_path, primitives)
        test_path = package_path / "generated" / "tool_tests" / "test_order_query.py"
        test_path.write_text(
            "import importlib.util\n"
            "from pathlib import Path\n"
            "import unittest\n\n"
            "MODULE_PATH = Path(__file__).resolve().parents[1] / 'draft_tools' / 'order_query.py'\n\n"
            "class BrittleGeneratedToolTest(unittest.TestCase):\n"
            "    def test_brittle_exact_field(self):\n"
            "        spec = importlib.util.spec_from_file_location('generated_tool_order_query', MODULE_PATH)\n"
            "        module = importlib.util.module_from_spec(spec)\n"
            "        spec.loader.exec_module(module)\n"
            "        result = module.run({'query': '订单 123'}, {})\n"
            "        self.assertEqual(result.get('impossible_exact_field'), 'T-1001')\n",
            encoding="utf-8",
        )
        return report


class ToolGenerationIssueArtifactGenerator(PackageArtifactGenerator):
    def generate_tool_scripts(self, package_path, primitives, **kwargs):
        report = PackageArtifactReport(tool_count=1)
        report.issues.append("custom_tool: tool generation fell back to a generic placeholder")
        return report


class DuplicateMCPArtifactGenerator(PackageArtifactGenerator):
    def generate_mcp_bindings(self, package_path, primitives):
        path = package_path / "mcp.yaml"
        path.write_text(
            "schema_version: '0.1'\n"
            "kind: MCPBindingSpec\n"
            "servers:\n"
            "  - id: duplicate\n"
            "  - id: duplicate\n"
            "bindings:\n"
            "  - id: binding\n"
            "    source_id: duplicate\n"
            "    capability_ref: mcp.duplicate.default@1.0.0\n"
            "    risk_level: medium\n"
            "  - id: binding\n"
            "    source_id: duplicate\n"
            "    capability_ref: mcp.duplicate.default@1.0.0\n"
            "    risk_level: medium\n",
            encoding="utf-8",
        )
        return PackageArtifactReport(artifact_paths=[path], mcp_binding_count=2)


class DuplicateHarnessArtifactGenerator(PackageArtifactGenerator):
    def generate_harness_scenarios(self, package_path, primitives):
        path = package_path / "harness.yaml"
        path.write_text(
            "schema_version: '0.1'\n"
            "kind: HarnessSpec\n"
            "fixtures:\n"
            "  tools: {}\n"
            "scenarios:\n"
            "  - id: duplicate\n"
            "    turns:\n"
            "      - user: hello\n"
            "    expected: {}\n"
            "    observe: {}\n"
            "  - id: duplicate\n"
            "    turns:\n"
            "      - user: hello again\n"
            "    expected: {}\n"
            "    observe: {}\n",
            encoding="utf-8",
        )
        return PackageArtifactReport(artifact_paths=[path], harness_scenario_count=2)


if __name__ == "__main__":
    unittest.main()
