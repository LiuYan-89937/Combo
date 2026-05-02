from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from agent_factory.factory import FactoryAgent
from agent_factory.factory.package_artifacts import PackageArtifactGenerator
from agent_factory.factory.package_verification import PackageVerificationRunner
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


def strange_number_primitives_payload() -> dict:
    payload = valid_primitives_payload()
    metadata = {
        "name": "strange-number-agent",
        "version": "1.0.0",
        "description": "奇异数计算 Agent",
    }
    payload["instructions"] = {
        **payload["instructions"],
        "metadata": metadata,
        "persona": "精确的奇异数计算助手",
        "goal": "必须使用工具计算奇异数：正数返回平方，负数返回两倍。",
        "principles": ["始终使用工具计算奇异数", "返回计算过程和结果"],
        "few_shots": [
            {
                "user": "5 的奇异数是多少？",
                "assistant": "5 是正数，奇异数为 25。",
                "notes": "positive_square",
            },
            {
                "user": "-9 的奇异数是多少？",
                "assistant": "-9 是负数，奇异数为 -18。",
                "notes": "negative_double",
            },
        ],
    }
    for key in [
        "output",
        "conversation",
        "run_context",
        "toolsets",
        "knowledge",
        "guardrails",
        "handoffs",
        "observability",
    ]:
        payload[key]["metadata"] = metadata
    payload["toolsets"]["toolsets"] = [
        {
            "id": "strange_number_calculator",
            "description": "奇异数计算工具：正数平方，负数两倍。",
            "exposed_tools": ["calculate_strange_number"],
            "hidden_tools": [],
            "proposal_only": True,
            "selection_strategy": "required",
        }
    ]
    return payload


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

    def test_factory_prompt_requests_json_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            context = FactoryRunContext.create(start_path=tmpdir)
            request = FactoryPromptBuilder().build_primitives_request(
                context,
                requirement="创建客服 Agent",
            )

            self.assertEqual(request.response_format, "json_schema")
            self.assertEqual(request.json_schema_name, "AgentPackagePrimitives")
            self.assertIsNotNone(request.json_schema)
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
            self.assertIsNotNone(result.verification_report)
            self.assertEqual(result.verification_report.status, "passed")
            self.assertTrue((result.output_path / "generated" / "reports").exists())
            self.assertTrue(result.memory_path.exists())
            self.assertTrue(result.trace_path.exists())

    def test_package_artifact_generator_uses_structured_tool_code(self) -> None:
        source = '''from __future__ import annotations
from typing import Any

TOOL_ID = "order_query"

def input_schema() -> dict[str, Any]:
    return {"type": "object"}

def output_schema() -> dict[str, Any]:
    return {"type": "object"}

def run(input_data: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"status": "completed", "tool_id": TOOL_ID, "marker": "llm_generated"}
'''
        payload = {
            "tool_id": "order_query",
            "python_source": source,
            "input_schema": {"type": "object"},
            "output_schema": {"type": "object"},
            "test_cases": [
                {
                    "name": "returns_marker",
                    "input_data": {"query": "订单 123"},
                    "expected_contains": {"status": "completed", "marker": "llm_generated"},
                }
            ],
            "risk_notes": ["local deterministic test"],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            primitives = AgentPackagePrimitives.model_validate(valid_primitives_payload())
            generator = PackageArtifactGenerator(
                model_service=service_with_responses([payload])
            )

            report = generator.generate_tool_scripts(root, primitives)
            generator.generate_tool_tests(root, primitives)

            self.assertEqual(report.tool_count, 1)
            self.assertIn("llm_generated", (root / "generated" / "draft_tools" / "order_query.py").read_text())
            self.assertTrue((root / "generated" / "draft_tools" / "order_query.codegen.json").exists())

    def test_package_artifact_generator_falls_back_from_unsafe_tool_code(self) -> None:
        payload = {
            "tool_id": "order_query",
            "python_source": "import os\n\ndef run(input_data, context=None):\n    os.system('echo unsafe')\n    return {}\n",
            "input_schema": {"type": "object"},
            "output_schema": {"type": "object"},
            "test_cases": [],
            "risk_notes": ["unsafe"],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            primitives = AgentPackagePrimitives.model_validate(valid_primitives_payload())
            generator = PackageArtifactGenerator(
                model_service=service_with_responses([payload])
            )

            generator.generate_tool_scripts(root, primitives)

            source = (root / "generated" / "draft_tools" / "order_query.py").read_text()
            self.assertNotIn("os.system", source)
            self.assertIn("order_status", source)

    def test_factory_production_uses_same_model_service_for_tool_code(self) -> None:
        source = '''from __future__ import annotations
from typing import Any

TOOL_ID = "order_query"

def input_schema() -> dict[str, Any]:
    return {"type": "object"}

def output_schema() -> dict[str, Any]:
    return {"type": "object"}

def run(input_data: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "status": "completed",
        "tool_id": TOOL_ID,
        "order_id": "123",
        "order_status": "in_transit",
        "marker": "same_model_service",
    }
'''
        tool_payload = {
            "tool_id": "order_query",
            "python_source": source,
            "input_schema": {"type": "object"},
            "output_schema": {"type": "object"},
            "test_cases": [
                {
                    "name": "returns_marker",
                    "input_data": {"query": "订单 123"},
                    "expected_contains": {"status": "completed", "marker": "same_model_service"},
                }
            ],
            "risk_notes": ["local deterministic test"],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            service = CreateAgentService(
                model_service=service_with_responses([valid_primitives_payload(), tool_payload])
            )

            result = service.create_agent(
                CreateAgentRequest(prompt="创建客服 Agent", start_path=Path(tmpdir))
            )

            self.assertTrue(result.implemented, result.error)
            assert result.output_path is not None
            generated = result.output_path / "generated" / "draft_tools" / "order_query.py"
            self.assertIn("same_model_service", generated.read_text(encoding="utf-8"))

    def test_strange_number_tool_generation_tests_business_logic(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            primitives = AgentPackagePrimitives.model_validate(strange_number_primitives_payload())
            generator = PackageArtifactGenerator()

            generator.generate_tool_scripts(
                root,
                primitives,
                requirement="创建一个能够计算奇异数的 agent，正数平方，负数两倍，计算采用工具",
            )
            generator.generate_tool_tests(root, primitives)
            report = PackageVerificationRunner().run_generated_tool_tests(root)

            self.assertTrue(report.ok, report.issues)
            source = (root / "generated" / "draft_tools" / "calculate_strange_number.py").read_text(
                encoding="utf-8"
            )
            self.assertIn("positive_square", source)
            test_source = (
                root / "generated" / "tool_tests" / "test_calculate_strange_number.py"
            ).read_text(encoding="utf-8")
            self.assertIn("negative_number_returns_double", test_source)


if __name__ == "__main__":
    unittest.main()
