from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_factory.application import CreateAgentRequest, CreateAgentService
from agent_factory.application.patch_plan_service import PatchPlanService
from agent_factory.application.registry_service import RegisterAgentRequest, RegistryService
from agent_factory.application.run_agent_service import RunAgentService, RunAgentServiceRequest
from agent_factory.package import PackageValidator
from agent_factory.registry import FilesystemRegistry
from tests.test_factory_agent import (
    service_with_responses,
    strange_number_primitives_payload,
    valid_primitives_payload,
)


class MVPRuntimeRegistryTests(unittest.TestCase):
    def test_generated_package_passes_full_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package_path = _generated_package(Path(tmpdir))

            report = PackageValidator().validate_full_package(package_path)

            self.assertTrue(report.ok, report.issues)
            self.assertTrue((package_path / "package.yaml").exists())
            self.assertTrue((package_path / "runtime.yaml").exists())
            self.assertTrue((package_path / "tools.yaml").exists())
            self.assertTrue((package_path / "context.yaml").exists())
            self.assertTrue((package_path / "memory.yaml").exists())

    def test_run_agent_executes_safe_order_query_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package_path = _generated_package(Path(tmpdir))
            service = RunAgentService(model_service=service_with_responses([""]))

            result = service.run_agent(
                RunAgentServiceRequest(target=str(package_path), user_input="帮我查订单 123")
            )

            self.assertTrue(result.ok, result.error)
            assert result.result is not None
            self.assertEqual(result.result.intent, "order_query")
            self.assertEqual(result.result.tool_results[0].status, "completed")
            self.assertEqual(result.result.tool_results[0].output["order_status"], "in_transit")
            self.assertIn("order_status", result.result.answer)
            self.assertTrue(result.result.trace_path.exists())
            self.assertTrue(result.result.memory_path.exists())

    def test_run_agent_reads_file_memory_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package_path = _generated_package(Path(tmpdir))
            service = RunAgentService(model_service=service_with_responses([""]))

            first = service.run_agent(
                RunAgentServiceRequest(
                    target=str(package_path),
                    user_input="我叫刘岩",
                    session_id="history-test",
                )
            )
            second = service.run_agent(
                RunAgentServiceRequest(
                    target=str(package_path),
                    user_input="我叫什么？",
                    session_id="history-test",
                )
            )

            self.assertTrue(first.ok, first.error)
            self.assertTrue(second.ok, second.error)
            assert second.result is not None
            self.assertEqual(second.result.history_turn_count, 1)
            self.assertIn("刘岩", second.result.answer)
            self.assertIn("load_memory", {event.stage for event in second.result.events})

    def test_run_agent_executes_required_calculation_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package_path = _generated_strange_number_package(Path(tmpdir))
            service = RunAgentService(model_service=service_with_responses([""]))

            result = service.run_agent(
                RunAgentServiceRequest(target=str(package_path), user_input="-9的奇异数是多少")
            )

            self.assertTrue(result.ok, result.error)
            assert result.result is not None
            self.assertEqual(result.result.intent, "calculate_strange_number")
            self.assertEqual(result.result.tool_results[0].status, "completed")
            self.assertEqual(result.result.tool_results[0].output["result"], -18)
            self.assertIn("-18", result.result.answer)

    def test_process_run_agent_reads_file_memory_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package_path = _generated_package(Path(tmpdir))
            service = RunAgentService()

            with patch.dict(os.environ, {"AGENTFACTORY_LLM_PROVIDER": "fake"}):
                service.run_agent(
                    RunAgentServiceRequest(
                        target=str(package_path),
                        user_input="我叫刘岩",
                        session_id="process-history",
                        process=True,
                    )
                )
                second = service.run_agent(
                    RunAgentServiceRequest(
                        target=str(package_path),
                        user_input="我叫什么？",
                        session_id="process-history",
                        process=True,
                    )
                )

            assert second.result is not None
            self.assertEqual(second.result.history_turn_count, 1)
            self.assertIn("刘岩", second.result.answer)

    def test_unknown_intent_writes_upgrade_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package_path = _generated_package(Path(tmpdir))
            service = RunAgentService(model_service=service_with_responses([""]))

            result = service.run_agent(
                RunAgentServiceRequest(target=str(package_path), user_input="我要返厂维修")
            )

            assert result.result is not None
            self.assertEqual(result.result.status, "needs_upgrade")
            self.assertTrue(result.result.upgrade_request_path.exists())

    def test_registry_register_and_run_by_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            package_path = _generated_package(root)
            registry = FilesystemRegistry(root / "registry")
            registry_service = RegistryService(registry)
            record = registry_service.register(RegisterAgentRequest(package_path=package_path))
            service = RunAgentService(
                model_service=service_with_responses([""]),
                registry=registry,
            )

            result = service.run_agent(
                RunAgentServiceRequest(target=record.agent_name, user_input="你好")
            )

            self.assertTrue(result.ok, result.error)
            self.assertEqual(result.package_path, record.package_path)

    def test_patch_plan_apply_adds_repair_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            package_path = _generated_package(root)
            output = root / "customer-service-agent-v1.1.0"
            service = PatchPlanService()
            plan = service.plan_upgrade(package_path, prompt="增加返厂维修意图")

            service.apply_plan(plan, output)

            self.assertTrue((output / "generated" / "draft_tools" / "repair_ticket_create.py").exists())
            harness = (output / "harness.yaml").read_text(encoding="utf-8")
            self.assertIn("repair_ticket_confirm_001", harness)


def _generated_package(start_path: Path) -> Path:
    service = CreateAgentService(model_service=service_with_responses([valid_primitives_payload()]))
    result = service.create_agent(
        CreateAgentRequest(prompt="创建客服 Agent", start_path=start_path, stream=False)
    )
    assert result.output_path is not None
    return result.output_path


def _generated_strange_number_package(start_path: Path) -> Path:
    service = CreateAgentService(
        model_service=service_with_responses([strange_number_primitives_payload()])
    )
    result = service.create_agent(
        CreateAgentRequest(prompt="创建奇异数计算 Agent", start_path=start_path, stream=False)
    )
    assert result.output_path is not None
    return result.output_path


if __name__ == "__main__":
    unittest.main()
