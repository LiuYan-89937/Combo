from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

from agent_factory.factory.package_artifacts import PackageArtifactGenerator
from agent_factory.factory.package_writer import PackageWriter
from agent_factory.factory.tool_generation import validate_tool_logic_source
from agent_factory.model import FakeModelAdapter, ModelConfig, ModelService
from agent_factory.package import PackageLoader, PackageValidator
from agent_factory.specs import AgentPackagePrimitives


def valid_primitives_payload() -> dict:
    metadata = {
        "name": "generic-resource-agent",
        "version": "1.0.0",
        "description": "Generic AgentPackage fixture",
    }
    return {
        "instructions": {
            "schema_version": "0.1",
            "kind": "InstructionSpec",
            "metadata": metadata,
            "persona": "严谨、透明的通用 Agent",
            "goal": "根据用户需求和受控能力边界完成任务；缺少证据或配置时必须说明缺口。",
            "style": "简洁、明确、可追踪",
            "boundaries": ["不编造工具结果", "不声称已经执行未通过 Runtime 的操作"],
        },
        "output": {
            "schema_version": "0.1",
            "kind": "OutputSpec",
            "metadata": metadata,
            "output_mode": "text",
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
            "toolsets": [],
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


def tool_primitives_payload() -> dict:
    payload = valid_primitives_payload()
    payload["toolsets"]["toolsets"] = [
        {
            "id": "generic_tools",
            "description": "通用受控工具组",
            "exposed_tools": ["lookup_resource"],
            "hidden_tools": [],
            "proposal_only": True,
            "selection_strategy": "auto",
        }
    ]
    return payload


def service_with_responses(responses: list[dict | str]) -> ModelService:
    return ModelService.with_adapter(ModelConfig(provider="fake"), FakeModelAdapter(responses))


class FactoryAgentProtocolTests(unittest.TestCase):
    def test_package_writer_round_trips_primitives(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            primitives = AgentPackagePrimitives.model_validate(valid_primitives_payload())

            PackageWriter().write_primitives(root, primitives)

            loaded = PackageLoader().load_primitives(root)
            report = PackageValidator().validate_primitives(root)
            self.assertTrue(report.ok, report.issues)
            self.assertEqual(loaded.instructions.metadata.name, "generic-resource-agent")

    def test_tool_logic_validator_rejects_response_object_external_http_usage(self) -> None:
        source = """
def execute(input_data, resources):
    response = resources["external_http_client"].request("GET", "/v1/items")
    return {"status": "completed", "code": response.status_code, "body": response.text}
"""

        issues = validate_tool_logic_source(source)

        self.assertTrue(
            any("external_http_client_returns_dict_not_response_object" in item for item in issues)
        )

    def test_missing_model_tool_generation_creates_failed_stub_not_business_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            primitives = AgentPackagePrimitives.model_validate(tool_primitives_payload())
            PackageWriter().write_primitives(root, primitives)

            report = PackageArtifactGenerator().generate_tool_scripts(root, primitives)

            self.assertTrue(report.issues)
            self.assertEqual(len(report.issues), 1)
            generated = root / "generated" / "draft_tools" / "lookup_resource.py"
            self.assertTrue(generated.exists())
            source = generated.read_text(encoding="utf-8")
            self.assertIn("generation_failed", source)

            spec = importlib.util.spec_from_file_location("generated_lookup_resource", generated)
            module = importlib.util.module_from_spec(spec)
            assert spec is not None and spec.loader is not None
            spec.loader.exec_module(module)
            result = module.run({"query": "anything"}, {})
            self.assertEqual(result["status"], "generation_failed")
            self.assertEqual(result["tool_id"], "lookup_resource")


if __name__ == "__main__":
    unittest.main()
