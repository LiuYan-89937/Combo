from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

from pydantic import ConfigDict, Field
from ruamel.yaml import YAML

from agent_factory.core.types import JsonDumpMixin
from agent_factory.factory.tool_generation import (
    GeneratedToolCodeDraft,
    build_tool_generation_request,
    fallback_tool_code,
    required_tool_test_cases,
    validate_tool_source,
)
from agent_factory.model import ModelService
from agent_factory.specs import AgentPackagePrimitives


class PackageArtifactReport(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    artifact_paths: list[Path] = Field(default_factory=list)
    tool_count: int = 0
    tool_test_count: int = 0
    mcp_binding_count: int = 0
    harness_scenario_count: int = 0


class PackageArtifactGenerator:
    """Generate draft implementation artifacts for a primitives package."""

    def __init__(self, *, model_service: ModelService | None = None) -> None:
        self.model_service = model_service
        self._yaml = YAML()
        self._yaml.default_flow_style = False

    def generate_tool_scripts(
        self,
        package_path: Path,
        primitives: AgentPackagePrimitives,
        *,
        requirement: str | None = None,
        requirement_analysis: dict[str, Any] | None = None,
    ) -> PackageArtifactReport:
        report = PackageArtifactReport()
        draft_dir = package_path / "generated" / "draft_tools"
        draft_dir.mkdir(parents=True, exist_ok=True)

        tool_drafts = _tool_drafts(primitives)
        for draft in tool_drafts:
            stem = _safe_file_stem(draft["tool_id"])
            script_path = draft_dir / f"{stem}.py"
            metadata_path = draft_dir / f"{stem}.tool.yaml"
            code_draft = self._generate_tool_code(
                primitives,
                draft,
                requirement=requirement,
                requirement_analysis=requirement_analysis,
            )
            script_path.write_text(code_draft.python_source, encoding="utf-8")
            self._dump_yaml(metadata_path, _tool_metadata(primitives, draft, script_path, code_draft))
            codegen_path = draft_dir / f"{stem}.codegen.json"
            codegen_path.write_text(code_draft.model_dump_json(indent=2), encoding="utf-8")
            report.artifact_paths.extend([script_path, metadata_path, codegen_path])

        report.tool_count = len(tool_drafts)
        return report

    def generate_tool_tests(
        self,
        package_path: Path,
        primitives: AgentPackagePrimitives,
    ) -> PackageArtifactReport:
        report = PackageArtifactReport()
        test_dir = package_path / "generated" / "tool_tests"
        test_dir.mkdir(parents=True, exist_ok=True)

        tool_drafts = _tool_drafts(primitives)
        if not tool_drafts:
            readme_path = test_dir / "README.md"
            readme_path.write_text(
                "No generated tool tests are required because toolsets.yaml exposes no tools.\n",
                encoding="utf-8",
            )
            report.artifact_paths.append(readme_path)
            return report

        for draft in tool_drafts:
            stem = _safe_file_stem(draft["tool_id"])
            test_path = test_dir / f"test_{stem}.py"
            code_draft = _load_codegen(draft_dir=package_path / "generated" / "draft_tools", stem=stem)
            test_path.write_text(_tool_test_source(draft, code_draft), encoding="utf-8")
            report.artifact_paths.append(test_path)

        report.tool_test_count = len(tool_drafts)
        return report

    def generate_mcp_bindings(
        self,
        package_path: Path,
        primitives: AgentPackagePrimitives,
    ) -> PackageArtifactReport:
        report = PackageArtifactReport()
        mcp_sources = [source for source in primitives.knowledge.sources if source.type == "mcp"]
        bindings = []
        servers = []
        version = primitives.instructions.metadata.version

        for source in mcp_sources:
            server_id = _safe_identifier(source.id)
            binding_id = f"{server_id}_default"
            servers.append(
                {
                    "id": server_id,
                    "source_ref": source.ref,
                    "transport": "stdio",
                    "enabled": False,
                    "health_check": {"enabled": True},
                }
            )
            bindings.append(
                {
                    "id": binding_id,
                    "source_id": source.id,
                    "capability_ref": f"mcp.{server_id}.default@{version}",
                    "risk_level": "medium",
                    "visible_to_model": source.visible_to_model,
                    "proposal_only": True,
                    "input_mapping": {"strategy": "pass_through"},
                    "output_mapping": {"strategy": "sanitized_json"},
                }
            )

        path = package_path / "mcp.yaml"
        self._dump_yaml(
            path,
            {
                "schema_version": "0.1",
                "kind": "MCPBindingSpec",
                "metadata": _metadata_dict(primitives, suffix="mcp"),
                "servers": servers,
                "bindings": bindings,
            },
        )
        report.artifact_paths.append(path)
        report.mcp_binding_count = len(bindings)
        return report

    def generate_harness_scenarios(
        self,
        package_path: Path,
        primitives: AgentPackagePrimitives,
    ) -> PackageArtifactReport:
        report = PackageArtifactReport()
        tool_ids = [draft["tool_id"] for draft in _tool_drafts(primitives)]
        mcp_sources = [source for source in primitives.knowledge.sources if source.type == "mcp"]
        scenarios = [_basic_harness_scenario(primitives), _memory_harness_scenario()]

        for draft in _tool_drafts(primitives):
            scenarios.append(_tool_harness_scenario(draft))

        path = package_path / "harness.yaml"
        self._dump_yaml(
            path,
            {
                "schema_version": "0.1",
                "kind": "HarnessSpec",
                "metadata": _metadata_dict(primitives, suffix="harness"),
                "observation": {
                    "trace": True,
                    "runtime_path": True,
                    "route_decisions": True,
                    "context_bundle": True,
                    "tool_calls": True,
                    "mcp_calls": True,
                    "memory_ops": True,
                    "final_response": True,
                },
                "fixtures": {
                    "tools": {
                        tool_id: {
                            "mode": "mock",
                            "output": {
                                "status": "mocked",
                                "tool_id": tool_id,
                                "requires_approval": True,
                            },
                        }
                        for tool_id in tool_ids
                    },
                    "mcp": {
                        _safe_identifier(source.id): {
                            "mode": "mock",
                            "output": {"documents": []},
                        }
                        for source in mcp_sources
                    },
                    "context": {},
                    "memory": {},
                },
                "scenarios": scenarios,
            },
        )
        report.artifact_paths.append(path)
        report.harness_scenario_count = len(scenarios)
        return report

    def generate_package_specs(
        self,
        package_path: Path,
        primitives: AgentPackagePrimitives,
    ) -> PackageArtifactReport:
        report = PackageArtifactReport()
        metadata = primitives.instructions.metadata
        agent_id = _safe_identifier(metadata.name)
        tool_ids = [draft["tool_id"] for draft in _tool_drafts(primitives)]
        files = {
            "package.yaml": {
                "schema_version": "0.1",
                "kind": "PackageManifest",
                "metadata": _metadata_dict(primitives, suffix="package"),
                "agent_id": agent_id,
                "agent_name": metadata.name,
                "version": metadata.version,
                "status": "draft",
                "description": metadata.description,
                "entrypoint": "agent_factory.agent.worker",
                "package_format": "agentpackage.v1",
                "tags": ["factory-generated", "mvp"],
            },
            "runtime.yaml": {
                "schema_version": "0.1",
                "kind": "RuntimeSpec",
                "metadata": _metadata_dict(primitives, suffix="runtime"),
                "runtime_type": "workflow",
                "workflow_steps": [
                    {"id": "load_context", "type": "load_context"},
                    {"id": "load_memory", "type": "load_memory"},
                    {"id": "model_turn", "type": "model_turn"},
                    {"id": "route_tools", "type": "route_tools"},
                    {"id": "write_memory", "type": "write_memory"},
                    {"id": "write_trace", "type": "write_trace"},
                ],
                "graph": {},
                "max_turns": primitives.conversation.history_window,
                "timeout_seconds": 60,
            },
            "tools.yaml": {
                "schema_version": "0.1",
                "kind": "ToolsSpec",
                "metadata": _metadata_dict(primitives, suffix="tools"),
                "generated_tools": tool_ids,
                "default_policy": "proposal_only",
                "allow_draft_execution": False,
                "require_approval_for_generated_code": True,
            },
            "context.yaml": {
                "schema_version": "0.1",
                "kind": "ContextSpec",
                "metadata": _metadata_dict(primitives, suffix="context"),
                "sources": _context_sources(primitives),
                "max_visible_items": 8,
                "redact_fields": [
                    "api_key",
                    "secret",
                    "authorization",
                    "auth_header",
                    "tool_auth_token",
                ],
            },
            "memory.yaml": {
                "schema_version": "0.1",
                "kind": "MemorySpec",
                "metadata": _metadata_dict(primitives, suffix="memory"),
                "backend": "filesystem",
                "session_memory_file": "memory/session_memory.jsonl",
                "summary_memory_file": "memory/summary_memory.jsonl",
                "enabled": True,
                "namespace_template": f"agent:{agent_id}:session:{{session_id}}",
                "redact_before_storage": True,
            },
        }
        for filename, data in files.items():
            path = package_path / filename
            self._dump_yaml(path, data)
            report.artifact_paths.append(path)
        return report

    def _dump_yaml(self, path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as file:
            self._yaml.dump(data, file)

    def _generate_tool_code(
        self,
        primitives: AgentPackagePrimitives,
        draft: dict[str, Any],
        *,
        requirement: str | None = None,
        requirement_analysis: dict[str, Any] | None = None,
    ) -> GeneratedToolCodeDraft:
        if self.model_service is not None:
            for _attempt in range(2):
                try:
                    result = asyncio.run(
                        self.model_service.generate_structured(
                            build_tool_generation_request(
                                primitives,
                                draft,
                                requirement=requirement,
                                requirement_analysis=requirement_analysis,
                            ),
                            schema=GeneratedToolCodeDraft.model_json_schema(),
                            schema_name="GeneratedToolCodeDraft",
                        )
                    )
                    if result.ok and isinstance(result.data, dict):
                        code = GeneratedToolCodeDraft.model_validate(result.data)
                        if code.tool_id != draft["tool_id"]:
                            continue
                        source_issues = validate_tool_source(code.python_source)
                        if not source_issues:
                            code.test_cases = _merge_tool_test_cases(
                                code.test_cases,
                                required_tool_test_cases(draft),
                            )
                            return code
                except Exception:
                    continue
        return fallback_tool_code(draft)


def merge_artifact_reports(*reports: PackageArtifactReport) -> PackageArtifactReport:
    merged = PackageArtifactReport()
    for report in reports:
        merged.artifact_paths.extend(report.artifact_paths)
        merged.tool_count += report.tool_count
        merged.tool_test_count += report.tool_test_count
        merged.mcp_binding_count += report.mcp_binding_count
        merged.harness_scenario_count += report.harness_scenario_count
    return merged


def _tool_drafts(primitives: AgentPackagePrimitives) -> list[dict[str, Any]]:
    drafts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for toolset in primitives.toolsets.toolsets:
        for exposure, tool_ids in (
            ("exposed", toolset.exposed_tools),
            ("hidden", toolset.hidden_tools),
        ):
            for tool_id in tool_ids:
                if tool_id in seen:
                    continue
                seen.add(tool_id)
                risk_level = _infer_tool_risk(tool_id, toolset.description)
                drafts.append(
                    {
                        "tool_id": tool_id,
                        "toolset_id": toolset.id,
                        "description": toolset.description,
                        "exposure": exposure,
                        "proposal_only": toolset.proposal_only,
                        "selection_strategy": toolset.selection_strategy,
                        "risk_level": risk_level,
                        "approval_required": risk_level in {"high", "critical"},
                    }
                )
    return drafts


def _tool_script_source(draft: dict[str, Any]) -> str:
    tool_id = json.dumps(draft["tool_id"], ensure_ascii=True)
    toolset_id = json.dumps(draft["toolset_id"], ensure_ascii=True)
    risk_level = json.dumps(draft["risk_level"], ensure_ascii=True)
    approval_required = "True" if draft["approval_required"] else "False"
    return f'''"""Factory-generated draft tool.

This module is a placeholder implementation. It must pass review, generated
tool tests, AgentHarness, and approval before becoming an available capability.
"""

from __future__ import annotations

from typing import Any


TOOL_ID = {tool_id}
TOOLSET_ID = {toolset_id}
RISK_LEVEL = {risk_level}
APPROVAL_REQUIRED = {approval_required}


def input_schema() -> dict[str, Any]:
    return {{"type": "object", "additionalProperties": True}}


def output_schema() -> dict[str, Any]:
    return {{
        "type": "object",
        "properties": {{
            "status": {{"type": "string"}},
            "tool_id": {{"type": "string"}},
            "requires_approval": {{"type": "boolean"}},
            "input": {{"type": "object"}},
        }},
        "required": ["status", "tool_id", "requires_approval", "input"],
    }}


def run(input_data: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(input_data, dict):
        raise TypeError("input_data must be a dict")
    return {{
        "status": "not_implemented",
        "tool_id": TOOL_ID,
        "requires_approval": APPROVAL_REQUIRED,
        "input": input_data,
    }}
'''


def _tool_test_source(draft: dict[str, Any], code_draft: GeneratedToolCodeDraft) -> str:
    stem = _safe_file_stem(draft["tool_id"])
    class_name = "".join(part.capitalize() for part in stem.split("_")) or "GeneratedTool"
    test_cases = _merge_tool_test_cases(
        code_draft.test_cases or fallback_tool_code(draft).test_cases,
        required_tool_test_cases(draft),
    )
    rendered_cases = [
        {
            "name": case.name,
            "input_data": case.input_data,
            "expected_contains": case.expected_contains,
        }
        for case in test_cases
    ]
    return f'''from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "draft_tools" / "{stem}.py"
TEST_CASES = {rendered_cases!r}


def load_tool_module():
    spec = importlib.util.spec_from_file_location("generated_tool_{stem}", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


class {class_name}DraftTests(unittest.TestCase):
    def test_run_returns_executable_local_contract(self) -> None:
        module = load_tool_module()
        for case in TEST_CASES:
            with self.subTest(case=case["name"]):
                result = module.run(case["input_data"])
                self.assertIsInstance(result, dict)
                self.assertNotEqual(result.get("status"), "not_implemented")
                for key, expected in case["expected_contains"].items():
                    self.assertEqual(result.get(key), expected)

    def test_schema_contracts_are_objects(self) -> None:
        module = load_tool_module()

        self.assertEqual(module.input_schema()["type"], "object")
        self.assertEqual(module.output_schema()["type"], "object")


if __name__ == "__main__":
    unittest.main()
'''


def _tool_metadata(
    primitives: AgentPackagePrimitives,
    draft: dict[str, Any],
    script_path: Path,
    code_draft: GeneratedToolCodeDraft,
) -> dict[str, Any]:
    return {
        "schema_version": "0.1",
        "kind": "GeneratedToolDraft",
        "metadata": _metadata_dict(primitives, suffix=_safe_file_stem(draft["tool_id"])),
        "tool_id": draft["tool_id"],
        "toolset_id": draft["toolset_id"],
        "source": "factory_generated",
        "status": "draft",
        "risk_level": draft["risk_level"],
        "exposure": draft["exposure"],
        "proposal_only": draft["proposal_only"],
        "selection_strategy": draft["selection_strategy"],
        "implementation": {
            "language": "python",
            "entrypoint": "run",
            "path": str(script_path.relative_to(script_path.parents[2])),
        },
        "input_schema": code_draft.input_schema,
        "output_schema": code_draft.output_schema,
        "approval": {
            "required": draft["approval_required"],
            "reason": "Factory-generated tool code must be reviewed before registration.",
        },
    }


def _load_codegen(draft_dir: Path, stem: str) -> GeneratedToolCodeDraft:
    path = draft_dir / f"{stem}.codegen.json"
    if not path.exists():
        return fallback_tool_code({"tool_id": stem, "risk_level": "low", "approval_required": False})
    data = json.loads(path.read_text(encoding="utf-8"))
    return GeneratedToolCodeDraft.model_validate(data)


def _merge_tool_test_cases(
    base_cases: list[Any],
    required_cases: list[Any],
) -> list[Any]:
    merged: list[Any] = list(base_cases)
    seen = {
        (
            getattr(case, "name", None),
            json.dumps(getattr(case, "expected_contains", {}), sort_keys=True, ensure_ascii=False),
        )
        for case in merged
    }
    for case in required_cases:
        key = (
            getattr(case, "name", None),
            json.dumps(getattr(case, "expected_contains", {}), sort_keys=True, ensure_ascii=False),
        )
        if key not in seen:
            merged.append(case)
            seen.add(key)
    return merged


def _basic_harness_scenario(primitives: AgentPackagePrimitives) -> dict[str, Any]:
    return {
        "id": "basic_response_001",
        "name": "Basic in-scope response",
        "turns": [{"user": "请根据你的职责提供帮助"}],
        "expected": {
            "intent": "in_scope",
            "must_confirm": False,
            "forbidden_direct_execution": True,
            "response_constraints": {
                "must_not_include": ["已直接执行", "已自动扣款", "已完成退款"],
            },
        },
        "observe": {
            "trace": True,
            "runtime_path": True,
            "context_bundle": True,
            "tool_calls": True,
            "route_decisions": True,
        },
    }


def _memory_harness_scenario() -> dict[str, Any]:
    return {
        "id": "memory_recall_001",
        "name": "Conversation history recall",
        "turns": [
            {"user": "我叫刘岩"},
            {"user": "我叫什么？"},
        ],
        "expected": {
            "intent": "in_scope",
            "memory_read_allowed": True,
            "must_confirm": False,
            "forbidden_direct_execution": True,
            "response_constraints": {
                "must_include": ["刘岩"],
            },
        },
        "observe": {
            "trace": True,
            "runtime_path": True,
            "context_bundle": True,
            "memory_ops": True,
            "final_response": True,
        },
    }


def _tool_harness_scenario(draft: dict[str, Any]) -> dict[str, Any]:
    tool_id = draft["tool_id"]
    scenario_id = f"{_safe_file_stem(tool_id)}_proposal_001"
    return {
        "id": scenario_id,
        "name": f"Tool proposal boundary for {tool_id}",
        "turns": [{"user": f"请处理和 {tool_id} 相关的请求"}],
        "expected": {
            "selected_tool": tool_id,
            "forbidden_tools": [],
            "must_confirm": draft["approval_required"],
            "forbidden_direct_execution": draft["approval_required"],
            "response_constraints": {
                "must_include": ["order_status"] if tool_id == "order_query" else [],
            },
        },
        "observe": {
            "trace": True,
            "tool_calls": True,
            "interrupts": True,
            "route_decisions": True,
        },
    }


def _metadata_dict(primitives: AgentPackagePrimitives, *, suffix: str) -> dict[str, Any]:
    metadata = primitives.instructions.metadata
    return {
        "name": f"{metadata.name}-{suffix}",
        "version": metadata.version,
        "description": metadata.description,
        "owner": metadata.owner,
    }


def _context_sources(primitives: AgentPackagePrimitives) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = [
        {
            "id": "agent_instructions",
            "type": "static",
            "content": f"{primitives.instructions.persona}\n{primitives.instructions.goal}",
            "visible_to_model": True,
            "visible_to_tools": False,
            "hidden_from_model": [],
        }
    ]
    for source in primitives.knowledge.sources:
        sources.append(
            {
                "id": source.id,
                "type": "mcp" if source.type == "mcp" else "static",
                "content": None,
                "ref": source.ref,
                "visible_to_model": source.visible_to_model,
                "visible_to_tools": True,
                "hidden_from_model": [
                    "api_key",
                    "authorization",
                    "tool_auth_token",
                ],
            }
        )
    return sources


def _safe_file_stem(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_").lower()
    return normalized or "generated_tool"


def _safe_identifier(value: str) -> str:
    normalized = _safe_file_stem(value)
    if normalized[0].isdigit():
        return f"id_{normalized}"
    return normalized


def _infer_tool_risk(tool_id: str, description: str | None = None) -> str:
    lowered = f"{tool_id} {description or ''}".lower()
    low_risk_markers = [
        "calculate",
        "calculator",
        "compute",
        "convert",
        "query",
        "search",
        "lookup",
        "get",
        "list",
        "read",
        "find",
        "math",
        "number",
        "计算",
        "奇异",
    ]
    if any(marker in lowered for marker in low_risk_markers):
        return "low"
    high_risk_markers = [
        "create",
        "delete",
        "refund",
        "payment",
        "charge",
        "write",
        "send",
        "approve",
        "cancel",
    ]
    if any(marker in lowered for marker in high_risk_markers):
        return "high"
    return "medium"
