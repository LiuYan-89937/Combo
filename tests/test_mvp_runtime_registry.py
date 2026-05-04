from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ruamel.yaml import YAML

from agent_factory.application import CreateAgentRequest, CreateAgentService
from agent_factory.application.patch_plan_service import PatchPlanService
from agent_factory.application.registry_service import RegisterAgentRequest, RegistryService
from agent_factory.application.run_agent_service import RunAgentService, RunAgentServiceRequest
from agent_factory.factory.web_search import (
    FactoryWebSearchService,
    WebSearchConfig,
    WebSearchProvider,
    WebSearchRequest,
    WebSearchReport,
    WebSearchResult,
)
from agent_factory.model import FakeModelAdapter, LLMResponse, ModelConfig, ModelService, ToolCallProposal
from agent_factory.package import PackageValidator
from agent_factory.registry import FilesystemRegistry
from agent_factory.runtime import AgentRunRequest, WorkflowRuntime
from agent_factory.specs import BuiltinCapabilitySpec
from agent_factory.tools import ToolExecutor, ToolInvocation
from tests.test_factory_agent import (
    service_with_responses,
    strange_number_primitives_payload,
    valid_primitives_payload,
)


class StaticSearchProvider(WebSearchProvider):
    provider = "static"

    def search(self, request: WebSearchRequest) -> WebSearchReport:
        max_results = request.max_results or 5
        results = [
            WebSearchResult(
                title="AgentFactory docs",
                url="https://example.com/agentfactory",
                snippet=f"Result for {request.query}",
                source="static",
            )
        ][:max_results]
        return WebSearchReport(
            status="passed",
            provider=self.provider,
            queries=[request.query],
            results=results,
        )


class _BrowserResponse:
    headers = {"content-type": "text/html; charset=utf-8"}
    text = "<html><head><title>Docs</title></head><body><h1>Hello browser</h1></body></html>"
    url = "https://example.com/docs"

    def raise_for_status(self) -> None:
        return None


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

    def test_run_agent_approved_draft_tool_rerun_executes_by_tool_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package_path = _generated_package(Path(tmpdir))
            _mark_order_query_requires_approval(package_path)

            first_service = RunAgentService(
                model_service=_tool_call_service(call_id="call-first", summary=""),
            )
            first = first_service.run_agent(
                RunAgentServiceRequest(target=str(package_path), user_input="帮我查订单 123")
            )

            self.assertTrue(first.result is not None)
            self.assertEqual(first.result.status, "interrupted")
            self.assertEqual(first.result.tool_results[0].tool_id, "order_query")

            second_service = RunAgentService(
                model_service=_tool_call_service(call_id="call-second", summary="订单 123 已查询。"),
            )
            second = second_service.run_agent(
                RunAgentServiceRequest(
                    target=str(package_path),
                    user_input="帮我查订单 123",
                    approved_tool_call_id="order_query",
                )
            )

            self.assertTrue(second.result is not None)
            self.assertEqual(second.result.status, "completed")
            self.assertEqual(second.result.tool_results[0].status, "completed")
            self.assertIn("订单 123", second.result.answer)

    def test_run_agent_exposes_package_tools_to_model_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package_path = _generated_package(Path(tmpdir))
            adapter = FakeModelAdapter([""])
            service = RunAgentService(
                model_service=ModelService.with_adapter(ModelConfig(provider="fake"), adapter)
            )

            result = service.run_agent(
                RunAgentServiceRequest(target=str(package_path), user_input="帮我查订单 123")
            )

            self.assertTrue(result.ok, result.error)
            first_request = adapter.requests[0]
            self.assertEqual(first_request.tool_choice, "auto")
            tool_names = [tool.function["name"] for tool in first_request.tools]
            self.assertIn("order_query", tool_names)

    def test_run_agent_executes_builtin_web_search_capability(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package_path = _generated_package(Path(tmpdir))
            _add_builtin_web_search(package_path)
            adapter = FakeModelAdapter(
                [
                    LLMResponse(
                        provider="fake",
                        model="fake",
                        tool_call_proposals=[
                            ToolCallProposal(
                                id="search-call",
                                name="web_search",
                                arguments={"query": "AgentFactory"},
                            )
                        ],
                    ),
                    "搜索到了 AgentFactory 文档。",
                ]
            )
            runtime = WorkflowRuntime(
                model_service=ModelService.with_adapter(ModelConfig(provider="fake"), adapter),
                web_search_service=FactoryWebSearchService(
                    WebSearchConfig(provider="tavily"),
                    provider=StaticSearchProvider(),
                ),
            )

            result = runtime.run(
                AgentRunRequest(package_path=package_path, user_input="联网搜索 AgentFactory")
            )

            self.assertEqual(result.status, "completed", result.error)
            self.assertEqual(result.tool_results[0].tool_id, "web_search")
            self.assertEqual(result.tool_results[0].status, "completed")
            self.assertEqual(result.tool_results[0].output["result_count"], 1)
            tool_names = [tool.function["name"] for tool in adapter.requests[0].tools]
            self.assertIn("web_search", tool_names)

    def test_tool_executor_fetches_builtin_browser_page(self) -> None:
        capability = BuiltinCapabilitySpec(
            id="browser_fetch",
            type="browser_fetch",
            description="Fetch allowed docs page.",
            allowed_domains=["example.com"],
        )
        invocation = ToolInvocation(
            tool_id="browser_fetch",
            arguments={"url": "https://example.com/docs"},
        )

        with patch("agent_factory.tools.web.httpx.get") as get:
            get.return_value = _BrowserResponse()
            result = ToolExecutor().execute(Path("."), capability, invocation)

        self.assertEqual(result.status, "completed", result.error)
        assert result.output is not None
        self.assertEqual(result.output["title"], "Docs")
        self.assertIn("Hello browser", result.output["text"])

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


def _tool_call_service(*, call_id: str, summary: str) -> ModelService:
    adapter = FakeModelAdapter(
        [
            LLMResponse(
                provider="fake",
                model="fake",
                tool_call_proposals=[
                    ToolCallProposal(
                        id=call_id,
                        name="order_query",
                        arguments={"order_id": "123"},
                    )
                ],
            ),
            summary,
        ]
    )
    return ModelService.with_adapter(ModelConfig(provider="fake"), adapter)


def _mark_order_query_requires_approval(package_path: Path) -> None:
    yaml = YAML()
    path = package_path / "generated" / "draft_tools" / "order_query.tool.yaml"
    data = YAML(typ="safe").load(path.read_text(encoding="utf-8"))
    data["risk_level"] = "high"
    data.setdefault("approval", {})["required"] = True
    data["approval"]["reason"] = "test requires human confirmation"
    with path.open("w", encoding="utf-8") as file:
        yaml.dump(data, file)


def _add_builtin_web_search(package_path: Path) -> None:
    yaml = YAML()
    path = package_path / "tools.yaml"
    data = YAML(typ="safe").load(path.read_text(encoding="utf-8"))
    data["builtin_capabilities"] = [
        {
            "id": "web_search",
            "type": "web_search",
            "description": "Search the public web through configured provider.",
            "exposure": "exposed",
            "risk_level": "low",
            "proposal_only": False,
            "approval_required": False,
            "allowed_domains": [],
            "blocked_domains": [],
            "max_uses": 5,
            "max_results": 5,
            "max_content_chars": 6000,
        }
    ]
    with path.open("w", encoding="utf-8") as file:
        yaml.dump(data, file)


if __name__ == "__main__":
    unittest.main()
