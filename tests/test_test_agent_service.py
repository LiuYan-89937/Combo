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
from agent_factory.harness import AgentHarnessRunner
from agent_factory.runtime import AgentInstanceRuntime


class TestAgentServiceTests(unittest.TestCase):
    def test_runs_generic_harness_when_factory_verification_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package_path = _generated_package(Path(tmpdir))
            runner = AgentHarnessRunner(
                runtime=AgentInstanceRuntime(model_service=service_with_responses(["AF-TEST-USER"]))
            )

            result = TestAgentService(runner=runner).test_agent(TestAgentRequest(path=package_path))

            self.assertTrue(result.ok, result.issues)
            self.assertEqual(result.status, "passed")
            self.assertIsNotNone(result.verification_report)
            self.assertIsNotNone(result.harness_run)
            self.assertGreaterEqual(result.scenario_count, 1)

    def test_missing_report_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            result = TestAgentService().test_agent(TestAgentRequest(path=root))

            self.assertFalse(result.ok)
            self.assertIn("factory_verification_report_missing", {issue.code for issue in result.issues})


def _generated_package(start_path: Path) -> Path:
    service = CreateAgentService(model_service=service_with_responses([valid_primitives_payload()]))
    result = service.create_agent(
        CreateAgentRequest(prompt="创建一个通用资料问答 Agent", start_path=start_path, stream=False)
    )
    assert result.output_path is not None
    return result.output_path


if __name__ == "__main__":
    unittest.main()
