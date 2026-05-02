from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.test_factory_agent import service_with_responses, valid_primitives_payload

from agent_factory.application import (
    CreateAgentRequest,
    CreateAgentService,
    TestAgentRequest,
    TestAgentService,
)


class TestAgentServiceTests(unittest.TestCase):
    def test_reads_verification_reports_and_harness(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package_path = _generated_package(Path(tmpdir))

            result = TestAgentService().test_agent(TestAgentRequest(path=package_path))

            self.assertTrue(result.ok, result.issues)
            self.assertEqual(result.status, "passed")
            self.assertEqual(result.verification_report.status, "passed")
            self.assertIsNotNone(result.harness_run)
            self.assertEqual(result.harness_run.status, "passed")
            self.assertTrue((package_path / "generated" / "reports" / "harness_run.json").exists())
            self.assertEqual(result.scenario_count, 3)
            self.assertTrue(all(scenario.status == "passed" for scenario in result.scenarios))

    def test_filters_selected_scenario(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package_path = _generated_package(Path(tmpdir))

            result = TestAgentService().test_agent(
                TestAgentRequest(path=package_path, scenario="basic_response_001")
            )

            self.assertTrue(result.ok, result.issues)
            self.assertEqual(result.scenario_count, 1)
            self.assertEqual(result.scenarios[0].id, "basic_response_001")
            self.assertEqual(result.scenarios[0].status, "passed")

    def test_missing_report_fails(self) -> None:
        result = TestAgentService().test_agent(
            TestAgentRequest(path=Path("examples/customer_service_agent"))
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "failed")
        self.assertIn("factory_verification_report_missing", {issue.code for issue in result.issues})

    def test_missing_scenario_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package_path = _generated_package(Path(tmpdir))

            result = TestAgentService().test_agent(
                TestAgentRequest(path=package_path, scenario="missing")
            )

            self.assertFalse(result.ok)
            self.assertIn("harness_scenario_not_found", {issue.code for issue in result.issues})

    def test_runner_failure_fails_test_agent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package_path = _generated_package(Path(tmpdir))
            harness_path = package_path / "harness.yaml"
            text = harness_path.read_text(encoding="utf-8")
            harness_path.write_text(
                text.replace("selected_tool: order_query", "selected_tool: missing_tool"),
                encoding="utf-8",
            )

            result = TestAgentService().test_agent(TestAgentRequest(path=package_path))

            self.assertFalse(result.ok)
            self.assertEqual(result.harness_run.status, "failed")
            self.assertIn("failed", {scenario.status for scenario in result.scenarios})


def _generated_package(start_path: Path) -> Path:
    service = CreateAgentService(model_service=service_with_responses([valid_primitives_payload()]))
    result = service.create_agent(
        CreateAgentRequest(prompt="创建客服 Agent", start_path=start_path, stream=False)
    )
    assert result.output_path is not None
    return result.output_path


if __name__ == "__main__":
    unittest.main()
