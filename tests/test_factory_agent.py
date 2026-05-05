from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ruamel.yaml import YAML

from agent_factory.factory import FactoryAgent
from agent_factory.factory.package_artifacts import PackageArtifactGenerator
from agent_factory.factory.package_verification import PackageVerificationRunner
from agent_factory.factory.package_writer import PackageWriter
from agent_factory.factory.resource_binding import (
    bind_requirement_resources,
    extract_local_resources,
)
from agent_factory.factory.tool_generation import (
    build_tool_generation_request,
    derive_tool_contract,
)
from agent_factory.factory_runtime import (
    FactoryContextBuilder,
    FactoryPromptBuilder,
    FactoryRunContext,
    FactoryToolPolicy,
)
from agent_factory.model import FakeModelAdapter, ModelConfig, ModelService
from agent_factory.package import PackageLoader, PackageValidator
from agent_factory.specs import AgentPackagePrimitives, GeneratedToolDraftSpec
from agent_factory.application import CreateAgentRequest, CreateAgentService
from agent_factory.context import ContextManager, tool_runtime_context


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


def sqlite_customer_ticket_primitives_payload(db_path: str) -> dict:
    payload = valid_primitives_payload()
    metadata = {
        "name": "local-db-manager",
        "version": "1.0.0",
        "description": "本地 SQLite 工单管理 Agent",
    }
    payload["instructions"] = {
        **payload["instructions"],
        "metadata": metadata,
        "persona": "严谨的本地 SQLite 数据库管理助手",
        "goal": "必须通过工具管理 customer_tickets 表，不能假装查询或修改数据库。",
        "principles": [
            "所有数据库访问必须使用工具",
            "所有 SQL 必须参数化",
            "禁止 schema 变更和危险 SQL 操作",
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
            "id": "local_sqlite_customer_ticket_tools",
            "description": "通过 SQLite 参数化查询管理 customer_tickets 工单表。",
            "exposed_tools": [
                "list_customer_tickets",
                "get_customer_ticket",
                "search_customer_tickets",
            ],
            "hidden_tools": [],
            "proposal_only": True,
            "selection_strategy": "auto",
        }
    ]
    payload["knowledge"]["sources"] = [
        {
            "id": "customer_ops_sqlite",
            "type": "file",
            "ref": db_path,
            "visible_to_model": False,
            "citation_required": False,
        }
    ]
    payload["knowledge"]["inject_as"] = "tool"
    return payload


def service_with_responses(responses: list[dict | str]) -> ModelService:
    return ModelService.with_adapter(ModelConfig(provider="fake"), FakeModelAdapter(responses))


class OpenAIProviderFakeAdapter(FakeModelAdapter):
    provider = "openai_compatible_chat"


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
            self.assertEqual(modes["factory.shell_exec"], "proposal_or_future")

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
            self.assertIn("Return exactly one JSON object", request.messages[-1].content)
            self.assertIn("Never return a top-level JSON array/list", request.messages[-1].content)
            self.assertIn("Minimal valid json object example", request.messages[-1].content)
            self.assertIn("Never return a top-level JSON array/list", request.messages[0].content)

    def test_requirement_resource_binding_adds_local_file_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "customer_ops.sqlite3"
            _seed_customer_ticket_db(db_path)
            primitives = AgentPackagePrimitives.model_validate(valid_primitives_payload())

            bound = bind_requirement_resources(
                primitives,
                f"管理本地 SQLite 数据库：{db_path}",
                start_path=root,
            )

            self.assertEqual(len(bound.knowledge.sources), 1)
            source = bound.knowledge.sources[0]
            self.assertEqual(source.id, "customer_ops_sqlite")
            self.assertEqual(source.type, "file")
            self.assertEqual(source.ref, str(db_path.resolve()))
            self.assertFalse(source.visible_to_model)
            self.assertTrue(source.visible_to_tools)
            self.assertEqual(source.access_mode, "read_write")
            self.assertTrue(source.sandbox_required)
            self.assertEqual(bound.knowledge.inject_as, "tool")

    def test_extract_local_resources_ignores_nonexistent_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            existing = root / "orders.csv"
            existing.write_text("id,total\n1,9\n", encoding="utf-8")

            resources = extract_local_resources(
                f"读取 {existing} 和 {root / 'missing.csv'}",
                start_path=root,
            )

            self.assertEqual(resources, [existing.resolve()])

    def test_resource_binding_uses_task_model_for_semantic_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "customer_ops.sqlite3"
            _seed_customer_ticket_db(db_path)
            primitives = AgentPackagePrimitives.model_validate(valid_primitives_payload())
            adapter = OpenAIProviderFakeAdapter(
                [
                    {
                        "bindings": [
                            {
                                "candidate_id": "customer_ops_sqlite",
                                "source_id": "tickets_resource",
                                "purpose": "Customer ticket operations datastore.",
                                "visible_to_model": False,
                                "visible_to_tools": True,
                                "access_mode": "read_write",
                                "sandbox_required": True,
                            }
                        ]
                    }
                ]
            )
            service = ModelService.with_adapter(
                ModelConfig(
                    provider="openai_compatible_chat",
                    base_url="https://api.deepseek.com",
                    api_key="sk-test-key",
                    model="deepseek-v4-pro",
                    task_model="deepseek-v4-flash",
                    task_thinking="disabled",
                ),
                adapter,
            )

            bound = bind_requirement_resources(
                primitives,
                f"管理本地 SQLite 数据库：{db_path}",
                start_path=root,
                model_service=service,
            )

            source = bound.knowledge.sources[0]
            self.assertEqual(source.id, "tickets_resource")
            self.assertEqual(source.ref, str(db_path.resolve()))
            self.assertEqual(source.access_mode, "read_write")
            self.assertEqual(adapter.requests[0].model, "deepseek-v4-flash")
            self.assertEqual(adapter.requests[0].thinking, "disabled")
            self.assertEqual(adapter.requests[0].metadata["model_role"], "task")

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

    def test_package_artifact_generator_writes_model_logic_artifact(self) -> None:
        logic_source = '''from __future__ import annotations
from typing import Any


def execute(input_data: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    query = str(input_data.get("query") or "")
    digits = "".join(ch for ch in query if ch.isdigit()) or "unknown"
    return {"status": "completed", "tool_id": "order_query", "order_id": digits, "marker": "logic_artifact"}
'''
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            primitives = AgentPackagePrimitives.model_validate(valid_primitives_payload())
            generator = PackageArtifactGenerator(
                model_service=service_with_responses([logic_source])
            )

            generator.generate_tool_scripts(root, primitives)
            generator.generate_tool_tests(root, primitives)
            report = PackageVerificationRunner().run_generated_tool_tests(root)
            wrapper = root / "generated" / "draft_tools" / "order_query.py"
            logic = root / "generated" / "draft_tools" / "order_query_logic.py"
            codegen = json.loads(
                (root / "generated" / "draft_tools" / "order_query.codegen.json").read_text(
                    encoding="utf-8"
                )
            )

            self.assertTrue(report.ok, report.stderr)
            self.assertTrue(logic.exists())
            self.assertIn("from order_query_logic import execute", wrapper.read_text(encoding="utf-8"))
            self.assertEqual(codegen["generation_status"], "model_generated")
            self.assertFalse(codegen["fallback_used"])
            self.assertEqual(codegen["logic_path"], "generated/draft_tools/order_query_logic.py")
            tool_yaml = YAML(typ="safe").load(
                (root / "generated" / "draft_tools" / "order_query.tool.yaml").read_text(
                    encoding="utf-8"
                )
            )
            tool_spec = GeneratedToolDraftSpec.model_validate(tool_yaml)
            self.assertEqual(
                tool_spec.implementation.logic_path,
                "generated/draft_tools/order_query_logic.py",
            )

    def test_full_package_validator_accepts_and_checks_logic_path(self) -> None:
        logic_source = '''from __future__ import annotations
from typing import Any


def execute(input_data: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    return {"status": "completed", "tool_id": "order_query", "order_status": "ok"}
'''
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            primitives = AgentPackagePrimitives.model_validate(valid_primitives_payload())
            writer = PackageWriter()
            generator = PackageArtifactGenerator(
                model_service=service_with_responses([logic_source])
            )

            writer.write_primitives(root, primitives)
            generator.generate_tool_scripts(root, primitives)
            generator.generate_mcp_bindings(root, primitives)
            generator.generate_harness_scenarios(root, primitives)
            generator.generate_package_specs(root, primitives)

            report = PackageValidator().validate_full_package(root)
            self.assertTrue(report.ok, report.issues)

            (root / "generated" / "draft_tools" / "order_query_logic.py").unlink()
            missing_report = PackageValidator().validate_full_package(root)

            self.assertFalse(missing_report.ok)
            self.assertIn(
                "generated_tool_implementation_missing",
                {issue.code for issue in missing_report.issues},
            )

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

    def test_package_artifact_generator_repairs_invalid_tool_code(self) -> None:
        unsafe_payload = {
            "tool_id": "normalize_text",
            "python_source": "import os\n\ndef run(input_data, context=None):\n    os.system('echo unsafe')\n    return {}\n",
            "input_schema": {"type": "object"},
            "output_schema": {"type": "object"},
            "test_cases": [],
            "risk_notes": ["unsafe"],
        }
        repaired_source = '''from __future__ import annotations
from typing import Any

TOOL_ID = "normalize_text"

def input_schema() -> dict[str, Any]:
    return {"type": "object"}

def output_schema() -> dict[str, Any]:
    return {"type": "object"}

def run(input_data: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    value = str(input_data.get("text") or "").strip().lower()
    return {"status": "completed", "tool_id": TOOL_ID, "normalized": value}
'''
        repaired_payload = {
            "tool_id": "normalize_text",
            "python_source": repaired_source,
            "input_schema": {"type": "object"},
            "output_schema": {"type": "object"},
            "test_cases": [
                {
                    "name": "normalizes_text",
                    "input_data": {"text": "  Hello  "},
                    "expected_contains": {"status": "completed", "normalized": "hello"},
                }
            ],
            "risk_notes": ["repaired deterministic local implementation"],
        }
        payload = valid_primitives_payload()
        payload["toolsets"]["toolsets"] = [
            {
                "id": "text_tools",
                "description": "文本标准化工具",
                "exposed_tools": ["normalize_text"],
                "hidden_tools": [],
                "proposal_only": True,
                "selection_strategy": "auto",
            }
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            primitives = AgentPackagePrimitives.model_validate(payload)
            generator = PackageArtifactGenerator(
                model_service=service_with_responses([unsafe_payload, repaired_payload])
            )

            report = generator.generate_tool_scripts(root, primitives)
            generator.generate_tool_tests(root, primitives)
            test_report = PackageVerificationRunner().run_generated_tool_tests(root)
            codegen = json.loads(
                (root / "generated" / "draft_tools" / "normalize_text.codegen.json").read_text(
                    encoding="utf-8"
                )
            )

            self.assertEqual(report.issues, [])
            self.assertTrue(test_report.ok, test_report.issues)
            self.assertEqual(codegen["generation_status"], "model_repaired")
            self.assertEqual(codegen["repair_attempts"], 1)

    def test_generated_tool_tests_treat_expected_contains_as_examples(self) -> None:
        source = '''from __future__ import annotations
from typing import Any

TOOL_ID = "example_tool"

def input_schema() -> dict[str, Any]:
    return {"type": "object"}

def output_schema() -> dict[str, Any]:
    return {"type": "object"}

def run(input_data: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"status": "completed", "tool_id": TOOL_ID, "items": [{"id": "actual"}]}
'''
        code_draft_payload = {
            "tool_id": "example_tool",
            "python_source": source,
            "input_schema": {"type": "object"},
            "output_schema": {"type": "object"},
            "test_cases": [
                {
                    "name": "example_not_hard_assertion",
                    "input_data": {"query": "anything"},
                    "expected_contains": {"id": "not-present"},
                }
            ],
            "risk_notes": [],
        }
        payload = valid_primitives_payload()
        payload["toolsets"]["toolsets"] = [
            {
                "id": "example_tools",
                "description": "示例工具",
                "exposed_tools": ["example_tool"],
                "hidden_tools": [],
                "proposal_only": True,
                "selection_strategy": "auto",
            }
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            primitives = AgentPackagePrimitives.model_validate(payload)
            generator = PackageArtifactGenerator(
                model_service=service_with_responses([code_draft_payload])
            )

            generator.generate_tool_scripts(root, primitives)
            generator.generate_tool_tests(root, primitives)
            report = PackageVerificationRunner().run_generated_tool_tests(root)

            self.assertTrue(report.ok, report.stderr)

    def test_generated_tool_tests_accept_pending_external_configuration(self) -> None:
        source = '''from __future__ import annotations
from typing import Any

TOOL_ID = "weather_query"

def input_schema() -> dict[str, Any]:
    return {"type": "object"}

def output_schema() -> dict[str, Any]:
    return {"type": "object"}

def run(input_data: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "status": "needs_configuration",
        "tool_id": TOOL_ID,
        "configuration_file": "external_config.yaml",
        "missing_fields": ["credential_ref", "operation_weather_query"],
    }
'''
        code_draft_payload = {
            "tool_id": "weather_query",
            "python_source": source,
            "input_schema": {"type": "object"},
            "output_schema": {"type": "object"},
            "test_cases": [
                {
                    "name": "weather_waits_for_configuration",
                    "input_data": {"city": "婺源"},
                    "expected_contains": {"status": "completed"},
                }
            ],
            "risk_notes": [],
        }
        payload = valid_primitives_payload()
        payload["toolsets"]["toolsets"] = [
            {
                "id": "weather_tools",
                "description": "天气工具",
                "exposed_tools": ["weather_query"],
                "hidden_tools": [],
                "proposal_only": True,
                "selection_strategy": "auto",
            }
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            primitives = AgentPackagePrimitives.model_validate(payload)
            generator = PackageArtifactGenerator(
                model_service=service_with_responses([code_draft_payload])
            )

            generator.generate_tool_scripts(root, primitives)
            generator.generate_tool_tests(root, primitives)
            report = PackageVerificationRunner().run_generated_tool_tests(root)

            self.assertTrue(report.ok, report.stderr)

    def test_generic_tool_generation_failure_is_reported(self) -> None:
        payload = valid_primitives_payload()
        payload["toolsets"]["toolsets"] = [
            {
                "id": "unknown_tools",
                "description": "未知业务工具",
                "exposed_tools": ["custom_unhandled_tool"],
                "hidden_tools": [],
                "proposal_only": True,
                "selection_strategy": "auto",
            }
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            primitives = AgentPackagePrimitives.model_validate(payload)
            generator = PackageArtifactGenerator()

            report = generator.generate_tool_scripts(root, primitives)
            codegen = json.loads(
                (root / "generated" / "draft_tools" / "custom_unhandled_tool.codegen.json").read_text(
                    encoding="utf-8"
                )
            )

            self.assertTrue(report.issues)
            self.assertEqual(codegen["generation_status"], "generic_fallback")

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

    def test_create_agent_binds_requirement_resources_into_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "customer_ops.sqlite3"
            _seed_customer_ticket_db(db_path)
            service = CreateAgentService(
                model_service=service_with_responses([valid_primitives_payload()])
            )

            result = service.create_agent(
                CreateAgentRequest(
                    prompt=f"创建一个 Agent 管理本地资源 {db_path}",
                    start_path=root,
                )
            )

            self.assertTrue(result.implemented, result.error)
            assert result.output_path is not None
            loaded = PackageLoader().load_primitives(result.output_path)
            refs = {source.id: source.ref for source in loaded.knowledge.sources}
            self.assertEqual(refs["customer_ops_sqlite"], str(db_path.resolve()))

    def test_tool_code_prompt_is_scoped_to_one_contract(self) -> None:
        payload = sqlite_customer_ticket_primitives_payload("/tmp/customer_ops.sqlite3")
        payload["toolsets"]["toolsets"][0]["exposed_tools"] = [
            "list_customer_tickets",
            "get_customer_ticket",
        ]
        primitives = AgentPackagePrimitives.model_validate(payload)
        draft = {
            "tool_id": "get_customer_ticket",
            "toolset_id": "local_sqlite_customer_ticket_tools",
            "description": "按 ticket_id 查询单个工单。",
            "risk_level": "low",
            "approval_required": False,
        }
        contract = derive_tool_contract(primitives, draft)

        request = build_tool_generation_request(primitives, draft, contract=contract)
        content = request.messages[-1].content

        self.assertIn("Single tool contract", content)
        self.assertIn("get_customer_ticket", content)
        self.assertNotIn("list_customer_tickets", content)
        self.assertNotIn("Tool draft", content)

    def test_real_provider_tool_generation_uses_parallel_workers(self) -> None:
        service = ModelService.with_adapter(
            ModelConfig(
                provider="openai_compatible_chat",
                base_url="https://example.invalid",
                api_key="test-key",
                model="test-model",
            ),
            FakeModelAdapter([]),
        )
        generator = PackageArtifactGenerator(model_service=service)

        self.assertEqual(generator._tool_generation_worker_count(1), 1)
        self.assertEqual(generator._tool_generation_worker_count(2), 2)
        self.assertEqual(generator._tool_generation_worker_count(8), 4)

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
            self.assertTrue(report.sandbox_enabled)
            source = (root / "generated" / "draft_tools" / "calculate_strange_number.py").read_text(
                encoding="utf-8"
            )
            self.assertIn("positive_square", source)
            test_source = (
                root / "generated" / "tool_tests" / "test_calculate_strange_number.py"
            ).read_text(encoding="utf-8")
            self.assertIn("negative_number_returns_double", test_source)

    def test_sqlite_customer_ticket_tools_are_real_and_business_tested(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "customer_ops.sqlite3"
            _seed_customer_ticket_db(db_path)
            primitives = AgentPackagePrimitives.model_validate(
                sqlite_customer_ticket_primitives_payload(str(db_path))
            )
            PackageWriter().write_primitives(root, primitives)
            generator = PackageArtifactGenerator()
            before_rows = _ticket_rows(db_path)

            script_report = generator.generate_tool_scripts(
                root,
                primitives,
                requirement=(
                    f"创建本地 SQLite 数据库管理 Agent，数据库路径：{db_path}，"
                    "只允许管理 customer_tickets 表。"
                ),
            )
            generator.generate_tool_tests(root, primitives)
            test_report = PackageVerificationRunner().run_generated_tool_tests(root)
            get_source = (
                root / "generated" / "draft_tools" / "get_customer_ticket.py"
            ).read_text(encoding="utf-8")
            search_report = test_report.diff_summary["per_test_file"]["test_search_customer_tickets.py"]

            self.assertEqual(script_report.issues, [])
            self.assertIn("sqlite3", get_source)
            self.assertIn("_resolve_db_path", get_source)
            self.assertNotIn("已完成本地模拟处理", get_source)
            self.assertTrue(test_report.ok, test_report.issues)
            self.assertTrue(test_report.sandbox_enabled)
            self.assertEqual(test_report.resource_count, 1)
            self.assertEqual(search_report["changed_count"], 0)
            self.assertEqual(_ticket_rows(db_path), before_rows)

    def test_context_keeps_sqlite_binary_hidden_from_model_and_visible_to_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "customer_ops.sqlite3"
            _seed_customer_ticket_db(db_path)
            primitives = AgentPackagePrimitives.model_validate(
                sqlite_customer_ticket_primitives_payload(str(db_path))
            )
            PackageWriter().write_primitives(root, primitives)
            generator = PackageArtifactGenerator()
            generator.generate_tool_scripts(root, primitives, requirement=f"数据库路径：{db_path}")
            generator.generate_mcp_bindings(root, primitives)
            generator.generate_harness_scenarios(root, primitives)
            generator.generate_package_specs(root, primitives)

            bundle = ContextManager().compile(root)
            runtime_context = tool_runtime_context(bundle)

            self.assertFalse(any("SQLite format 3" in item for item in bundle.visible_to_model))
            self.assertNotIn("customer_ops_sqlite", "\n".join(bundle.visible_to_model))
            self.assertEqual(runtime_context["sqlite_databases"]["customer_ops_sqlite"], str(db_path))
            self.assertEqual(runtime_context["resources"]["customer_ops_sqlite"]["type"], "sqlite")
            self.assertIsNone(runtime_context["resources"]["customer_ops_sqlite"].get("content"))

    def test_tool_test_sandbox_blocks_legacy_real_path_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "customer_ops.sqlite3"
            _seed_customer_ticket_db(db_path)
            primitives = AgentPackagePrimitives.model_validate(
                sqlite_customer_ticket_primitives_payload(str(db_path))
            )
            PackageWriter().write_primitives(root, primitives)
            generator = PackageArtifactGenerator()
            generator.generate_tool_scripts(root, primitives, requirement=f"数据库路径：{db_path}")
            generator.generate_tool_tests(root, primitives)
            tool_path = root / "generated" / "draft_tools" / "get_customer_ticket.py"
            tool_path.write_text(
                f'''from __future__ import annotations
from typing import Any

TOOL_ID = "get_customer_ticket"
DB_PATH = {str(db_path)!r}

def input_schema() -> dict[str, Any]:
    return {{"type": "object"}}

def output_schema() -> dict[str, Any]:
    return {{"type": "object"}}

def run(input_data: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    return {{"status": "completed", "tool_id": TOOL_ID, "path": DB_PATH}}
''',
                encoding="utf-8",
            )

            report = PackageVerificationRunner().run_generated_tool_tests(root)

            self.assertFalse(report.ok)
            self.assertTrue(report.sandbox_enabled)
            self.assertIn(
                "tool_used_real_resource_path",
                {issue.code for issue in report.issues},
            )


def _seed_customer_ticket_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "CREATE TABLE customer_tickets ("
            "ticket_id TEXT PRIMARY KEY, "
            "customer_name TEXT, "
            "channel TEXT, "
            "title TEXT, "
            "description TEXT, "
            "status TEXT, "
            "priority TEXT, "
            "assignee TEXT, "
            "created_at TEXT, "
            "updated_at TEXT)"
        )
        conn.execute(
            "INSERT INTO customer_tickets "
            "(ticket_id, customer_name, channel, title, description, status, priority, assignee, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "T-1001",
                "刘岩",
                "web",
                "订单查询",
                "用户想查询订单状态",
                "open",
                "high",
                "agentfactory",
                "2026-05-03T00:00:00Z",
                "2026-05-03T00:00:00Z",
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _ticket_rows(path: Path) -> list[tuple[str, str]]:
    conn = sqlite3.connect(path)
    try:
        rows = conn.execute(
            "SELECT ticket_id, status FROM customer_tickets ORDER BY ticket_id"
        ).fetchall()
        return [(str(ticket_id), str(status)) for ticket_id, status in rows]
    finally:
        conn.close()


if __name__ == "__main__":
    unittest.main()
