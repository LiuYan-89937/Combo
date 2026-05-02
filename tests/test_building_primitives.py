from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from ruamel.yaml import YAML

from agent_factory.package import PackageLoader, PackageValidator
from agent_factory.specs import (
    AgentPackagePrimitives,
    ConversationSpec,
    GuardrailSpec,
    HandoffSpec,
    InstructionSpec,
    KnowledgeSpec,
    ObservabilitySpec,
    OutputSpec,
    RunContextSpec,
    ToolsetSpec,
)


REQUIRED_FILES = {
    "instructions.yaml": "instructions",
    "output.yaml": "output",
    "conversation.yaml": "conversation",
    "run_context.yaml": "run_context",
    "toolsets.yaml": "toolsets",
    "knowledge.yaml": "knowledge",
    "guardrails.yaml": "guardrails",
    "handoffs.yaml": "handoffs",
    "observability.yaml": "observability",
}


def valid_primitives() -> dict[str, dict]:
    metadata = {"name": "customer-service-agent", "version": "1.0.0"}
    return {
        "instructions.yaml": {
            "schema_version": "0.1",
            "kind": "InstructionSpec",
            "metadata": metadata,
            "persona": "温和、专业的客服 Agent",
            "goal": "处理退款、投诉、转人工和订单查询",
            "style": "简洁、安抚、给出下一步",
            "boundaries": ["不承诺已退款", "不泄露内部工具鉴权信息"],
        },
        "output.yaml": {
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
                "required": ["intent", "answer"],
            },
        },
        "conversation.yaml": {
            "schema_version": "0.1",
            "kind": "ConversationSpec",
            "metadata": metadata,
            "history_window": 12,
            "summarize_after": 20,
            "summary_strategy": "rolling",
        },
        "run_context.yaml": {
            "schema_version": "0.1",
            "kind": "RunContextSpec",
            "metadata": metadata,
            "namespace_template": "agent:{agent_name}:version:{version}:instance:{instance_id}",
            "dependency_refs": ["model.default", "toolset.customer_service"],
        },
        "toolsets.yaml": {
            "schema_version": "0.1",
            "kind": "ToolsetSpec",
            "metadata": metadata,
            "toolsets": [
                {
                    "id": "customer_service_tools",
                    "exposed_tools": ["order_query", "refund_policy_query"],
                    "hidden_tools": ["payment_refund_execute"],
                    "proposal_only": True,
                    "selection_strategy": "auto",
                }
            ],
        },
        "knowledge.yaml": {
            "schema_version": "0.1",
            "kind": "KnowledgeSpec",
            "metadata": metadata,
            "sources": [
                {
                    "id": "customer_policy_kb",
                    "type": "mcp",
                    "ref": "mcp.customer_kb.search_policy",
                    "citation_required": True,
                }
            ],
            "retrievers": [
                {
                    "id": "policy_retriever",
                    "source_refs": ["customer_policy_kb"],
                    "strategy": "hybrid",
                    "top_k": 5,
                }
            ],
            "default_retriever": "policy_retriever",
            "inject_as": "context",
        },
        "guardrails.yaml": {
            "schema_version": "0.1",
            "kind": "GuardrailSpec",
            "metadata": metadata,
            "rules": [
                {
                    "id": "high_risk_tool_confirm",
                    "stage": "tool",
                    "action": "human_confirm",
                    "risk_level": "high",
                    "description": "高风险工具必须确认",
                }
            ],
        },
        "handoffs.yaml": {
            "schema_version": "0.1",
            "kind": "HandoffSpec",
            "metadata": metadata,
            "targets": [],
        },
        "observability.yaml": {
            "schema_version": "0.1",
            "kind": "ObservabilitySpec",
            "metadata": metadata,
            "trace_enabled": True,
            "spans": [
                {"type": "agent_run", "enabled": True},
                {"type": "model_generation", "enabled": True},
                {"type": "tool_call", "enabled": True},
            ],
            "record_usage": True,
            "record_prompt_hash": True,
            "record_response_hash": True,
            "record_content": False,
        },
    }


def write_package(root: Path, data: dict[str, dict]) -> None:
    yaml = YAML()
    yaml.default_flow_style = False
    for filename, content in data.items():
        with (root / filename).open("w", encoding="utf-8") as handle:
            yaml.dump(content, handle)


class BuildingPrimitiveTests(unittest.TestCase):
    def test_each_standard_model_can_validate(self) -> None:
        data = valid_primitives()
        self.assertIsInstance(InstructionSpec.model_validate(data["instructions.yaml"]), InstructionSpec)
        self.assertIsInstance(OutputSpec.model_validate(data["output.yaml"]), OutputSpec)
        self.assertIsInstance(ConversationSpec.model_validate(data["conversation.yaml"]), ConversationSpec)
        self.assertIsInstance(RunContextSpec.model_validate(data["run_context.yaml"]), RunContextSpec)
        self.assertIsInstance(ToolsetSpec.model_validate(data["toolsets.yaml"]), ToolsetSpec)
        self.assertIsInstance(KnowledgeSpec.model_validate(data["knowledge.yaml"]), KnowledgeSpec)
        self.assertIsInstance(GuardrailSpec.model_validate(data["guardrails.yaml"]), GuardrailSpec)
        self.assertIsInstance(HandoffSpec.model_validate(data["handoffs.yaml"]), HandoffSpec)
        self.assertIsInstance(ObservabilitySpec.model_validate(data["observability.yaml"]), ObservabilitySpec)

    def test_loader_returns_agent_package_primitives(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_package(root, valid_primitives())

            package = PackageLoader().load_primitives(root)

            self.assertIsInstance(package, AgentPackagePrimitives)
            self.assertEqual(package.instructions.persona, "温和、专业的客服 Agent")
            self.assertEqual(package.toolsets.toolsets[0].id, "customer_service_tools")

    def test_customer_service_package_validates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_package(root, valid_primitives())

            report = PackageValidator().validate_primitives(root)

            self.assertTrue(report.ok, report.issues)

    def test_missing_required_file_is_fatal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            data = valid_primitives()
            data.pop("guardrails.yaml")
            write_package(root, data)

            report = PackageValidator().validate_primitives(root)

            self.assertFalse(report.ok)
            self.assertIn("missing_required_file", [issue.code for issue in report.issues])
            self.assertIn("guardrails.yaml", [issue.file for issue in report.issues])

    def test_blank_instruction_persona_or_goal_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            data = valid_primitives()
            data["instructions.yaml"]["persona"] = ""
            write_package(root, data)

            report = PackageValidator().validate_primitives(root)

            self.assertFalse(report.ok)
            self.assertIn("schema_validation_error", [issue.code for issue in report.issues])

    def test_output_schema_root_type_must_match_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            data = valid_primitives()
            data["output.yaml"]["schema"] = {"type": "string"}
            write_package(root, data)

            report = PackageValidator().validate_primitives(root)

            self.assertFalse(report.ok)
            self.assertIn("schema_validation_error", [issue.code for issue in report.issues])

    def test_conversation_numeric_limits_are_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            data = valid_primitives()
            data["conversation.yaml"]["history_window"] = 0
            write_package(root, data)

            report = PackageValidator().validate_primitives(root)

            self.assertFalse(report.ok)
            self.assertIn("schema_validation_error", [issue.code for issue in report.issues])

    def test_toolset_cannot_expose_and_hide_same_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            data = valid_primitives()
            data["toolsets.yaml"]["toolsets"][0]["hidden_tools"].append("order_query")
            write_package(root, data)

            report = PackageValidator().validate_primitives(root)

            self.assertFalse(report.ok)
            self.assertIn("schema_validation_error", [issue.code for issue in report.issues])

    def test_guardrail_unknown_stage_or_action_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            data = valid_primitives()
            data["guardrails.yaml"]["rules"][0]["stage"] = "unknown"
            data["guardrails.yaml"]["rules"][0]["action"] = "explode"
            write_package(root, data)

            report = PackageValidator().validate_primitives(root)

            self.assertFalse(report.ok)
            self.assertIn("schema_validation_error", [issue.code for issue in report.issues])

    def test_handoff_target_ids_must_be_unique(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            data = valid_primitives()
            target = {
                "id": "human_support",
                "type": "human",
                "target_ref": "queue.customer_service",
            }
            data["handoffs.yaml"]["targets"] = [copy.deepcopy(target), copy.deepcopy(target)]
            write_package(root, data)

            report = PackageValidator().validate_primitives(root)

            self.assertFalse(report.ok)
            self.assertIn("schema_validation_error", [issue.code for issue in report.issues])

    def test_observability_cannot_allow_sensitive_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            data = valid_primitives()
            data["observability.yaml"]["allowed_sensitive_fields"] = ["api_key"]
            write_package(root, data)

            report = PackageValidator().validate_primitives(root)

            self.assertFalse(report.ok)
            self.assertIn("schema_validation_error", [issue.code for issue in report.issues])


if __name__ == "__main__":
    unittest.main()

