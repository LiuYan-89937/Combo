from __future__ import annotations

import ast
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from agent_factory.model import LLMRequest, MessageBuilder
from agent_factory.specs import (
    AgentPackagePrimitives,
    JsonSchema,
    ResourceContractsSpec,
    ToolImplementationPlan,
)


class GeneratedToolTestCase(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    name: str
    input_data: dict[str, Any] = Field(default_factory=dict)
    expected_contains: dict[str, Any] = Field(default_factory=dict)


class GeneratedToolCodeDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    tool_id: str
    python_source: str
    logic_source: str | None = None
    logic_path: str | None = None
    input_schema: JsonSchema = Field(default_factory=lambda: {"type": "object"})
    output_schema: JsonSchema = Field(default_factory=lambda: {"type": "object"})
    test_cases: list[GeneratedToolTestCase] = Field(default_factory=list)
    implementation_plan: ToolImplementationPlan | None = None
    risk_notes: list[str] = Field(default_factory=list)
    generation_status: Literal[
        "model_generated",
        "model_repaired",
        "generation_failed",
    ] = "model_generated"
    fallback_used: bool = False
    repair_attempts: int = 0
    generation_errors: list[str] = Field(default_factory=list)


class ToolContract(BaseModel):
    """Small, code-free contract used before asking the model to write a tool."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    tool_id: str
    toolset_id: str
    purpose: str
    risk_level: str = "low"
    approval_required: bool = False
    input_schema: JsonSchema = Field(default_factory=lambda: {"type": "object"})
    output_schema: JsonSchema = Field(default_factory=lambda: {"type": "object"})
    required_behaviors: list[str] = Field(default_factory=list)
    forbidden_behaviors: list[str] = Field(default_factory=list)
    resource_refs: list[str] = Field(default_factory=list)
    test_requirements: list[GeneratedToolTestCase] = Field(default_factory=list)


class ToolContractBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    tools: list[ToolContract] = Field(default_factory=list)


FORBIDDEN_IMPORT_ROOTS = {
    "httpx",
    "importlib",
    "os",
    "pathlib",
    "requests",
    "shutil",
    "socket",
    "subprocess",
    "sys",
    "urllib",
}
FORBIDDEN_CALLS = {
    "__import__",
    "compile",
    "eval",
    "exec",
    "input",
    "open",
}
FORBIDDEN_ATTRS = {
    "open",
    "popen",
    "remove",
    "rmtree",
    "run",
    "system",
    "unlink",
    "write_text",
}


def build_tool_generation_request(
    primitives: AgentPackagePrimitives,
    draft: dict[str, Any],
    *,
    contract: ToolContract | None = None,
    requirement: str | None = None,
    requirement_analysis: dict[str, Any] | None = None,
    resource_contracts: ResourceContractsSpec | None = None,
) -> LLMRequest:
    contract = contract or derive_tool_contract(
        primitives,
        draft,
        requirement=requirement,
        requirement_analysis=requirement_analysis,
        resource_contracts=resource_contracts,
    )
    return (
        MessageBuilder.start()
        .system(
            "You generate only the business logic for one safe local Python tool. "
            "Return raw Python code only, not JSON, not markdown, and not explanations. "
            "The code must define exactly this callable: execute(input_data, resources). "
            "Do not define run(), input_schema(), output_schema(), CLI entrypoints, tests, or wrappers. "
            "The code must not import network libraries, read environment variables, run shell, or access files outside "
            "the explicit resources argument. If external HTTP is required, it may only use "
            "resources['external_http_client'].request(...). Implement only the single tool contract provided."
        )
        .user(
            "Generate the logic.py content for exactly this one tool. Do not implement any other tool.\n\n"
            f"Agent persona: {primitives.instructions.persona}\n"
            f"Agent goal: {primitives.instructions.goal}\n"
            f"Agent boundaries: {json.dumps(primitives.instructions.boundaries, ensure_ascii=False)}\n"
            f"Requirement analysis summary:\n"
            f"{json.dumps(_compact_requirement_analysis(requirement_analysis), ensure_ascii=False, indent=2)}\n\n"
            f"Single tool contract:\n{contract.model_dump_json(indent=2)}\n\n"
            f"Resource contracts and environment facts:\n"
            f"{_resource_contracts_json(resource_contracts)}\n\n"
            "External API facts, when present, come only from research_brief inside the resource contracts. "
            "Never use unverified raw page text as facts. Treat unresolved_fields and empty external_config "
            "values as runtime configuration gaps.\n\n"
            "execute(input_data, resources) must return a dict. On success include status='completed'. "
            "Use resources['resources'], resources['sqlite_databases'], resources['filesystem_root'], "
            "resources['runtime'], resources['external_config'], or resources['external_http_client']; "
            "do not make a real user path the only data source.\n\n"
            "External configuration protocol:\n"
            "- resources['external_config'] is a dict with metadata keys: values, resolved_values, "
            "required_keys, secret_keys, source_urls, missing_required_keys, and path.\n"
            "- Read runtime configuration from resources['external_config']['resolved_values']; do not read "
            "os.environ. The generated wrapper may also expose resolved keys at the top level for convenience, "
            "but resolved_values is canonical.\n"
            "- Treat resources['external_config']['missing_required_keys'] as authoritative. If it is non-empty, "
            "return status='needs_configuration' before doing any external request.\n\n"
            "External HTTP protocol:\n"
            "- resources['external_http_client'].request(method, url, headers=..., params=..., json_data=...) "
            "returns a dict, not an httpx/requests response object.\n"
            "- The result dict shape is: status, http_status, url, json, text, or status='needs_configuration' "
            "with missing_fields.\n"
            "- Never use response.status_code, response.text, or response.json(). Use result.get('http_status'), "
            "result.get('json'), and result.get('text'). If result['status'] is not 'completed', return it or "
            "wrap it as a safe failed result.\n\n"
            "If this tool depends on an external service, realtime data, API credentials, or an endpoint "
            "that is not fully configured in resources['external_config'], first inspect "
            "resources['external_config']['missing_required_keys']. If it is non-empty, do not fake data and "
            "do not return status='completed'. Return status='needs_configuration' with tool_id, a concise message, "
            "configuration_file='external_config.yaml', and missing_fields listing the exact fields the user "
            "must fill. Missing external configuration is not an execution error. If configuration is present, "
            "make external HTTP requests only through resources['external_http_client'].request(...); never "
            "import requests/httpx/urllib or read os.environ directly.\n\n"
            "If the requirement describes a local SQLite database tool, implement it with sqlite3, "
            "parameterized SQL only, and no schema-changing statements. Resolve the database path from "
            "resources['sqlite_databases'] or resources['resources'] first. Never fake database results."
        )
        .request(
            response_format="text",
            metadata={"tool_id": str(draft.get("tool_id") or "")},
        )
    )


def build_tool_repair_request(
    primitives: AgentPackagePrimitives,
    draft: dict[str, Any],
    *,
    contract: ToolContract | None = None,
    previous_data: Any,
    validation_errors: list[str],
    requirement: str | None = None,
    requirement_analysis: dict[str, Any] | None = None,
    resource_contracts: ResourceContractsSpec | None = None,
) -> LLMRequest:
    contract = contract or derive_tool_contract(
        primitives,
        draft,
        requirement=requirement,
        requirement_analysis=requirement_analysis,
        resource_contracts=resource_contracts,
    )
    return (
        MessageBuilder.start()
        .system(
            "You repair unsafe or invalid Factory-generated Python tool logic. "
            "Return raw Python code only, not JSON, not markdown, and not explanations. "
            "The code must define execute(input_data, resources). Repair only this one tool."
        )
        .user(
            "Repair the generated tool logic so it is safe, executable, and business-complete.\n\n"
            f"Agent goal: {primitives.instructions.goal}\n"
            f"Single tool contract:\n{contract.model_dump_json(indent=2)}\n\n"
            f"Resource contracts and environment facts:\n"
            f"{_resource_contracts_json(resource_contracts)}\n\n"
            "Use only ResearchBrief-backed facts from resource contracts for external APIs. "
            "Do not invent endpoint, authentication, parameter, or response details.\n\n"
            "Previous generated code or data:\n"
            f"{json.dumps(previous_data, ensure_ascii=False, indent=2, default=str)}\n\n"
            "Validation/security/test-generation errors:\n"
            f"{json.dumps(validation_errors, ensure_ascii=False, indent=2)}\n\n"
            "The repaired logic must define execute(input_data, resources). It must not access network, "
            "environment variables, shell, secrets, or files outside the explicitly requested local data source. "
            "External configuration values must be read from "
            "resources['external_config']['resolved_values']; missing values must be determined from "
            "resources['external_config']['missing_required_keys']. "
            "External HTTP must use resources['external_http_client'].request(...), which returns a dict with "
            "status/http_status/json/text. Do not use response.status_code, response.text, or response.json(). "
            "If an external service is not fully configured, repair the logic to return "
            "status='needs_configuration' with configuration_file='external_config.yaml' and missing_fields; "
            "do not return status='error' or fake completed realtime data. If external configuration is present, "
            "use resources['external_http_client'].request(...) for HTTP; do not import network libraries. "
            "For SQLite tools, use sqlite3 with parameterized SQL only and resolve the database path "
            "from resources['sqlite_databases'] or resources['resources']."
        )
        .request(
            response_format="text",
            metadata={"tool_id": str(draft.get("tool_id") or ""), "repair": True},
        )
    )


def build_tool_contracts_request(
    primitives: AgentPackagePrimitives,
    tool_drafts: list[dict[str, Any]],
    *,
    requirement: str | None = None,
    requirement_analysis: dict[str, Any] | None = None,
    resource_contracts: ResourceContractsSpec | None = None,
) -> LLMRequest:
    schema = ToolContractBatch.model_json_schema()
    sources = [
        source.model_dump(mode="json")
        for source in primitives.knowledge.sources
        if source.type in {"file", "mcp"}
    ]
    return (
        MessageBuilder.start()
        .system(
            "You create code-free tool contracts for an AgentPackage. Return exactly one JSON object "
            "with a top-level 'tools' array matching ToolContractBatch. Do not write Python code."
        )
        .user(
            "Create one concise contract for each requested tool. Contracts describe behavior, inputs, "
            "outputs, resources, forbidden behavior, and test requirements. Do not include python_source.\n\n"
            f"Original requirement:\n{requirement or ''}\n\n"
            f"Requirement analysis:\n{json.dumps(requirement_analysis or {}, ensure_ascii=False, indent=2)}\n\n"
            f"Agent goal: {primitives.instructions.goal}\n"
            f"Agent boundaries: {json.dumps(primitives.instructions.boundaries, ensure_ascii=False)}\n"
            f"Knowledge/resource sources:\n{json.dumps(sources, ensure_ascii=False, indent=2)}\n\n"
            f"Resource contracts and environment facts:\n{_resource_contracts_json(resource_contracts)}\n\n"
            "For external APIs, contracts must reference ResearchBrief-backed facts and unresolved_fields; "
            "do not promote raw search snippets into behavior requirements.\n\n"
            f"Tool drafts:\n{json.dumps(tool_drafts, ensure_ascii=False, indent=2)}\n\n"
            "Return contracts only. Never include Python code."
        )
        .request(
            response_format="json_schema",
            json_schema=schema,
            json_schema_name="ToolContractBatch",
            json_schema_strict=True,
            metadata={"tool_count": len(tool_drafts), "phase": "tool_contracts"},
        )
    )


def derive_tool_contract(
    primitives: AgentPackagePrimitives,
    draft: dict[str, Any],
    *,
    requirement: str | None = None,
    requirement_analysis: dict[str, Any] | None = None,
    resource_contracts: ResourceContractsSpec | None = None,
) -> ToolContract:
    test_cases = required_tool_test_cases(
        draft,
        primitives=primitives,
        requirement=requirement,
    )
    resource_refs = [
        source.id
        for source in primitives.knowledge.sources
        if source.type in {"file", "directory", "mcp"}
    ]
    if resource_contracts is not None:
        for resource in resource_contracts.resources:
            if resource.id not in resource_refs:
                resource_refs.append(resource.id)
    forbidden = [
        "do_not_read_env_or_secrets",
        "do_not_execute_shell",
        "do_not_access_network",
        "do_not_access_files_outside_runtime_context",
    ]
    return ToolContract(
        tool_id=str(draft.get("tool_id") or "generated_tool"),
        toolset_id=str(draft.get("toolset_id") or "default"),
        purpose=str(draft.get("description") or primitives.instructions.goal),
        risk_level=str(draft.get("risk_level") or "low"),
        approval_required=bool(draft.get("approval_required")),
        input_schema={"type": "object", "additionalProperties": True},
        output_schema={"type": "object", "additionalProperties": True},
        required_behaviors=_contract_required_behaviors(draft, test_cases),
        forbidden_behaviors=forbidden,
        resource_refs=resource_refs,
        test_requirements=test_cases,
    )


def _resource_contracts_json(resource_contracts: ResourceContractsSpec | None) -> str:
    if resource_contracts is None:
        return "{}"
    return resource_contracts.model_dump_json(indent=2)


def _compact_requirement_analysis(value: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    allowed = {
        "agent_name",
        "agent_type",
        "safety_profile",
        "goals",
        "in_scope",
        "out_of_scope",
        "confidence",
    }
    return {key: value[key] for key in allowed if key in value}


def _contract_required_behaviors(
    draft: dict[str, Any],
    test_cases: list[GeneratedToolTestCase],
) -> list[str]:
    behaviors = [str(draft.get("description") or draft.get("tool_id") or "Implement the tool contract.")]
    for case in test_cases:
        behaviors.append(f"Pass test case '{case.name}' with expected fields {case.expected_contains}.")
    return behaviors


def validate_tool_source(source: str) -> list[str]:
    issues: list[str] = []
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        return [f"syntax_error: {error}"]

    functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    for required in {"input_schema", "output_schema", "run"}:
        if required not in functions:
            issues.append(f"missing_required_function: {required}")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in FORBIDDEN_IMPORT_ROOTS:
                    issues.append(f"forbidden_import: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in FORBIDDEN_IMPORT_ROOTS:
                issues.append(f"forbidden_import: {node.module}")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_CALLS:
                issues.append(f"forbidden_call: {node.func.id}")
            if isinstance(node.func, ast.Attribute) and node.func.attr in FORBIDDEN_ATTRS:
                issues.append(f"forbidden_call: {node.func.attr}")
    return issues


def validate_tool_logic_source(source: str) -> list[str]:
    issues = _validate_python_safety(source)
    if issues and any(issue.startswith("syntax_error") for issue in issues):
        return issues
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        return [f"syntax_error: {error}"]
    functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    if "execute" not in functions:
        issues.append("missing_required_function: execute")
    forbidden_wrapper_functions = {"run", "input_schema", "output_schema"}
    overlap = functions.intersection(forbidden_wrapper_functions)
    for name in sorted(overlap):
        issues.append(f"logic_must_not_define_wrapper_function: {name}")
    issues.extend(_validate_external_http_protocol(source))
    return issues


def _validate_external_http_protocol(source: str) -> list[str]:
    if "external_http_client" not in source:
        return []
    issues: list[str] = []
    if re.search(r"\.\s*status_code\b", source):
        issues.append(
            "external_http_client_returns_dict_not_response_object: use result.get('http_status')"
        )
    if re.search(r"\.\s*text\b", source):
        issues.append("external_http_client_returns_dict_not_response_object: use result.get('text')")
    if re.search(r"\.\s*json\s*\(", source):
        issues.append("external_http_client_returns_dict_not_response_object: use result.get('json')")
    return issues


def _validate_python_safety(source: str) -> list[str]:
    issues: list[str] = []
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        return [f"syntax_error: {error}"]

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in FORBIDDEN_IMPORT_ROOTS:
                    issues.append(f"forbidden_import: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in FORBIDDEN_IMPORT_ROOTS:
                issues.append(f"forbidden_import: {node.module}")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_CALLS:
                issues.append(f"forbidden_call: {node.func.id}")
            if isinstance(node.func, ast.Attribute) and node.func.attr in FORBIDDEN_ATTRS:
                issues.append(f"forbidden_call: {node.func.attr}")
    return issues


def fallback_tool_code(
    draft: dict[str, Any],
    *,
    primitives: AgentPackagePrimitives | None = None,
    requirement: str | None = None,
    generation_errors: list[str] | None = None,
    repair_attempts: int = 0,
) -> GeneratedToolCodeDraft:
    tool_id = str(draft.get("tool_id") or "generated_tool")
    risk_level = str(draft.get("risk_level") or "low")
    approval_required = bool(draft.get("approval_required"))
    errors = list(generation_errors or [])
    return GeneratedToolCodeDraft(
        tool_id=tool_id,
        python_source=_generation_failed_tool_source(tool_id, risk_level, approval_required),
        input_schema={"type": "object", "additionalProperties": True},
        output_schema={"type": "object", "additionalProperties": True},
        test_cases=[],
        implementation_plan=ToolImplementationPlan(
            tool_id=tool_id,
            resource_refs=[],
            preconditions=["tool_contract_available", "sandbox_context_available"],
            allowed_operations=[],
            forbidden_operations=[
                "read_env_or_secrets",
                "execute_shell",
                "network_access",
                "access_files_outside_runtime_context",
            ],
            failure_cases=["model_generation_failed"],
        ),
        risk_notes=["model generation failed; no business implementation was inferred by Factory"],
        generation_status="generation_failed",
        fallback_used=True,
        repair_attempts=repair_attempts,
        generation_errors=errors,
    )


def required_tool_test_cases(
    draft: dict[str, Any],
    *,
    primitives: AgentPackagePrimitives | None = None,
    requirement: str | None = None,
) -> list[GeneratedToolTestCase]:
    return []


def _generation_failed_tool_source(tool_id: str, risk_level: str, approval_required: bool) -> str:
    return f'''"""Factory-generated tool stub for failed model code generation."""

from __future__ import annotations

from typing import Any


TOOL_ID = {tool_id!r}
RISK_LEVEL = {risk_level!r}
APPROVAL_REQUIRED = {approval_required!r}


def input_schema() -> dict[str, Any]:
    return {{"type": "object", "additionalProperties": True}}


def output_schema() -> dict[str, Any]:
    return {{
        "type": "object",
        "properties": {{
            "status": {{"type": "string"}},
            "tool_id": {{"type": "string"}},
            "message": {{"type": "string"}},
        }},
        "required": ["status", "tool_id", "message"],
        "additionalProperties": True,
    }}


def run(input_data: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(input_data, dict):
        raise TypeError("input_data must be a dict")
    return {{
        "status": "generation_failed",
        "tool_id": TOOL_ID,
        "message": "Tool code generation failed; this tool has no inferred business implementation.",
        "requires_approval": APPROVAL_REQUIRED,
        "input": input_data,
    }}
'''
