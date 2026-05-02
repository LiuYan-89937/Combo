from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from agent_factory.factory import FactoryAgent
from agent_factory.factory.package_writer import PackageWriter
from agent_factory.factory_runtime import (
    FactoryContextBuilder,
    FactoryPromptBuilder,
    FactoryRunContext,
    FactoryToolPolicy,
)
from agent_factory.model import FakeModelAdapter, ModelConfig, ModelService
from agent_factory.package import PackageLoader, PackageValidator
from agent_factory.specs import AgentPackagePrimitives
from agent_factory.application import CreateAgentRequest, CreateAgentService


def valid_primitives_payload() -> dict:
    metadata = {"name": "customer-service-agent", "version": "1.0.0"}
    return {
        "instructions": {
            "schema_version": "0.1",
            "kind": "InstructionSpec",
            "metadata": metadata,
            "persona": "温和、专业的客服 Agent",
            "goal": "处理退款、投诉、转人工和订单查询",
            "style": "简洁、安抚、给出下一步",
            "boundaries": ["不承诺已退款"],
        },
        "output": {
            "schema_version": "0.1",
            "kind": "OutputSpec",
            "metadata": metadata,
            "output_mode": "json_object",
            "schema": {
                "type": "object",
                "properties": {
                    "intent": {"type": "string"},
                    "answer": {"type": "string"},
                    "requires_human": {"type": "boolean"},
                },
                "required": ["intent", "answer", "requires_human"],
            },
        },
        "conversation": {
            "schema_version": "0.1",
            "kind": "ConversationSpec",
            "metadata": metadata,
        },
        "run_context": {
            "schema_version": "0.1",
            "kind": "RunContextSpec",
            "metadata": metadata,
        },
        "toolsets": {
            "schema_version": "0.1",
            "kind": "ToolsetSpec",
            "metadata": metadata,
            "toolsets": [
                {
                    "id": "customer_service_tools",
                    "exposed_tools": ["order_query"],
                    "hidden_tools": [],
                    "proposal_only": True,
                    "selection_strategy": "auto",
                }
            ],
        },
        "knowledge": {
            "schema_version": "0.1",
            "kind": "KnowledgeSpec",
            "metadata": metadata,
            "sources": [],
            "retrievers": [],
            "inject_as": "none",
        },
        "guardrails": {
            "schema_version": "0.1",
            "kind": "GuardrailSpec",
            "metadata": metadata,
            "rules": [],
        },
        "handoffs": {
            "schema_version": "0.1",
            "kind": "HandoffSpec",
            "metadata": metadata,
            "targets": [],
        },
        "observability": {
            "schema_version": "0.1",
            "kind": "ObservabilitySpec",
            "metadata": metadata,
            "record_content": False,
        },
    }


def service_with_responses(responses: list[dict | str]) -> ModelService:
    return ModelService.with_adapter(ModelConfig(provider="fake"), FakeModelAdapter(responses))


class FactoryAgentTests(unittest.TestCase):
    def test_prompt_context_excludes_secrets_and_agent_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            context = FactoryRunContext.create(start_path=tmpdir)
            context_text = FactoryContextBuilder().build_prompt_text(
                context,
                requirement="创建客服 Agent",
            )

            self.assertIn("AgentInstance memory", context_text)
            self.assertNotIn("api_key", context_text)

    def test_tool_policy_classifies_factory_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            context = FactoryRunContext.create(start_path=tmpdir)
            policy = FactoryToolPolicy.from_registry(context.tool_registry)
            modes = {entry.tool_id: entry.mode for entry in policy.entries}

            self.assertEqual(modes["model.generate_structured"], "model_only")
            self.assertEqual(modes["package.validate"], "direct_internal")
            self.assertEqual(modes["memory.append"], "direct_internal")

    def test_factory_prompt_requests_json_object(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            context = FactoryRunContext.create(start_path=tmpdir)
            request = FactoryPromptBuilder().build_primitives_request(
                context,
                requirement="创建客服 Agent",
            )

            self.assertEqual(request.response_format, "json_object")
            self.assertIn("AgentPackagePrimitives", request.messages[-1].content)

    def test_create_package_writes_and_validates_yaml(self) -> None:
        async def run() -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                context = FactoryRunContext.create(start_path=tmpdir)
                output_dir = context.drafts_path / "customer-service-agent"
                agent = FactoryAgent(service_with_responses([valid_primitives_payload()]))

                draft = await agent.create_package("创建客服 Agent", output_dir, context)

                self.assertTrue(draft.ok, draft.error)
                self.assertTrue((output_dir / "instructions.yaml").exists())
                self.assertTrue(draft.validation_report.ok)
                loaded = PackageLoader().load_primitives(output_dir)
                self.assertIsInstance(loaded, AgentPackagePrimitives)

        asyncio.run(run())

    def test_factory_agent_repairs_invalid_primitives_once(self) -> None:
        async def run() -> None:
            with tempfile.TemporaryDirectory() as tmpdir:
                invalid = valid_primitives_payload()
                invalid["instructions"] = {**invalid["instructions"], "goal": ""}
                context = FactoryRunContext.create(start_path=tmpdir)
                agent = FactoryAgent(service_with_responses([invalid, valid_primitives_payload()]))

                draft = await agent.create_primitives("创建客服 Agent", context)

                self.assertTrue(draft.ok, draft.error)
                self.assertEqual(draft.repair_attempts, 1)

        asyncio.run(run())

    def test_package_writer_validation_failure_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            primitives = AgentPackagePrimitives.model_validate(valid_primitives_payload())
            report = PackageWriter(PackageValidator()).write_primitives(Path(tmpdir), primitives)

            self.assertTrue(report.ok)
            self.assertTrue((Path(tmpdir) / "output.yaml").exists())

    def test_create_agent_service_with_fake_model_creates_package_and_records_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = CreateAgentService(
                model_service=service_with_responses([valid_primitives_payload()])
            )

            result = service.create_agent(
                CreateAgentRequest(prompt="创建客服 Agent", start_path=Path(tmpdir))
            )

            self.assertTrue(result.implemented, result.error)
            self.assertIsNotNone(result.output_path)
            self.assertTrue((result.output_path / "instructions.yaml").exists())
            self.assertTrue(result.validation_report.ok)
            self.assertEqual(result.generated_tool_count, 1)
            self.assertEqual(result.generated_tool_test_count, 1)
            self.assertTrue((result.output_path / "mcp.yaml").exists())
            self.assertTrue((result.output_path / "harness.yaml").exists())
            self.assertTrue(result.memory_path.exists())
            self.assertTrue(result.trace_path.exists())


if __name__ == "__main__":
    unittest.main()
