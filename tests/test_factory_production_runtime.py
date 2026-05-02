from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.test_factory_agent import service_with_responses, valid_primitives_payload

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
            self.assertEqual(state.harness_scenario_count, 2)
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


if __name__ == "__main__":
    unittest.main()
