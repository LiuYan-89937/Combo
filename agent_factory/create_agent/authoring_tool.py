from __future__ import annotations

import ast
import json
from pathlib import Path
import shutil
import sys
from typing import Any

from agent_factory.assembly.schema import AgentAssemblySpec
from agent_factory.create_agent.contract_catalog import base_contract_paths, default_contract_payload
from agent_factory.create_agent.mcp_inheritance import materialize_referenced_factory_mcp
from agent_factory.create_agent.package_scaffold import _default_render_manifest
from agent_factory.create_agent.workspace import CreateAgentWorkspace
from agent_factory.runtime_kernel.activation import PLAN_AND_EXECUTE_ACTIVATION_FIELDS
from agent_factory.runtime_contracts.schema import (
    AgentIdentitySpec,
    AgentPackageManifest,
    DependenciesContract,
    ResourceDescriptor,
    ResourcesContract,
    SchedulerSeedContract,
    StateContract,
    ToolsContract,
)
from agent_factory.scheduler_system.schema import SchedulerSeedPlan
from agent_factory.tooling.envelope import tool_envelope
from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolRiskResult, ToolSpec


CREATE_AGENT_AUTHORING_TOOL_ID = "create_agent_authoring"
DEFAULT_INHERITED_RUNTIME_TOOL_IDS = ("knowledge", "scheduler")
CREATE_AGENT_AUTHORING_ACTIONS = {
    "reset_contract",
    "materialize_mcp_inheritance",
    "remove_package_tool",
    "set_identity",
    "configure_pattern_assembly",
    "upsert_knowledge_file",
    "upsert_package_tool",
    "upsert_resources",
    "upsert_scheduler_seed",
    "upsert_state",
}
SUPPORTED_PATTERN_IDS = {"react_agent", "plan_and_execute"}
RESETTABLE_CONTRACT_KEYS = frozenset(base_contract_paths())


def build_create_agent_authoring_tool_spec() -> ToolSpec:
    return ToolSpec(
        id=CREATE_AGENT_AUTHORING_TOOL_ID,
        description=(
            "Deterministically writes coherent AgentPackage authoring increments. Use this instead of manually "
            "hand-editing cross-file contracts for identity, built-in pattern assembly, package tools, scheduler seeds, "
            "runtime resources, package knowledge files, or package state."
        ),
        entrypoint="agent_factory.create_agent.authoring_tool:run",
        input_schema={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": sorted(CREATE_AGENT_AUTHORING_ACTIONS)},
                "agent": {"type": "object", "additionalProperties": True},
                "pattern_id": {"type": "string", "enum": sorted(SUPPORTED_PATTERN_IDS)},
                "prompts": {"type": "object", "additionalProperties": {"type": "string"}},
                "activation": {"type": "object", "additionalProperties": {"type": "string"}},
                "allowed_tool_ids": {"type": "array", "items": {"type": "string"}},
                "tool_spec": {"type": "object", "additionalProperties": True},
                "tool_id": {"type": "string"},
                "tool_source": {"type": "string"},
                "python_requirements": {"type": "array", "items": {"type": "string"}},
                "expose_to_nodes": {"type": "array", "items": {"type": "string"}},
                "seed": {"type": "object", "additionalProperties": True},
                "resources": {"type": "object", "additionalProperties": True},
                "resource_descriptors": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
                "knowledge_path": {"type": "string"},
                "knowledge_content": {"type": "string"},
                "state_namespace": {"type": "string"},
                "state_schema": {"type": "object", "additionalProperties": True},
                "initial_state": {"type": "object", "additionalProperties": True},
                "writable_node_ids": {"type": "array", "items": {"type": "string"}},
                "contract_key": {"type": "string", "enum": sorted(RESETTABLE_CONTRACT_KEYS)},
            },
            "required": ["action"],
            "allOf": [
                {"if": {"properties": {"action": {"const": "set_identity"}}}, "then": {"required": ["agent"]}},
                {
                    "if": {"properties": {"action": {"const": "configure_pattern_assembly"}}},
                    "then": {"required": ["pattern_id", "prompts", "allowed_tool_ids"]},
                },
                {
                    "if": {"properties": {"action": {"const": "upsert_package_tool"}}},
                    "then": {"required": ["tool_spec", "tool_source", "python_requirements", "expose_to_nodes"]},
                },
                {"if": {"properties": {"action": {"const": "remove_package_tool"}}}, "then": {"required": ["tool_id"]}},
                {"if": {"properties": {"action": {"const": "upsert_scheduler_seed"}}}, "then": {"required": ["seed"]}},
                {"if": {"properties": {"action": {"const": "upsert_resources"}}}, "then": {"required": ["resources", "resource_descriptors"]}},
                {"if": {"properties": {"action": {"const": "upsert_knowledge_file"}}}, "then": {"required": ["knowledge_path", "knowledge_content"]}},
                {
                    "if": {"properties": {"action": {"const": "upsert_state"}}},
                    "then": {"required": ["state_namespace", "state_schema", "initial_state", "writable_node_ids"]},
                },
                {"if": {"properties": {"action": {"const": "reset_contract"}}}, "then": {"required": ["contract_key"]}},
            ],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "changed_files": {"type": "array", "items": {"type": "string"}},
                "summary": {"type": "string"},
            },
            "required": ["action", "changed_files", "summary"],
            "additionalProperties": True,
        },
        resources={"workspace": "create_agent_workspace"},
        risk_level="medium",
        risk_evaluator=ToolRiskEvaluatorConfig(hard="agent_factory.create_agent.authoring_tool:evaluate_risk"),
        concurrent=False,
    )


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    workspace = _workspace(resources)
    action = str(arguments.get("action") or "").strip()
    if action not in CREATE_AGENT_AUTHORING_ACTIONS:
        raise ValueError(f"unsupported create-agent authoring action: {action}")
    if action == "set_identity":
        result = _set_identity(workspace, arguments)
    elif action == "configure_pattern_assembly":
        result = _configure_pattern_assembly(workspace, arguments)
    elif action == "upsert_package_tool":
        result = _upsert_package_tool(workspace, arguments)
    elif action == "remove_package_tool":
        result = _remove_package_tool(workspace, arguments)
    elif action == "upsert_scheduler_seed":
        result = _upsert_scheduler_seed(workspace, arguments)
    elif action == "upsert_resources":
        result = _upsert_resources(workspace, arguments)
    elif action == "upsert_knowledge_file":
        result = _upsert_knowledge_file(workspace, arguments)
    elif action == "reset_contract":
        result = _reset_contract(workspace, arguments)
    elif action == "materialize_mcp_inheritance":
        result = _materialize_mcp_inheritance(workspace)
    else:
        result = _upsert_state(workspace, arguments)
    return tool_envelope(result, evidence={"authoring": result}, summary=result["summary"])


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    del context
    action = str(arguments.get("action") or "").strip()
    if action not in CREATE_AGENT_AUTHORING_ACTIONS:
        return ToolRiskResult(action="deny", risk_level="medium", reasons=["unknown create-agent authoring action"]).model_dump(mode="json")
    return ToolRiskResult(
        action="allow",
        risk_level="medium",
        reasons=["create-agent authoring performs controlled package-relative writes"],
        facts={"action": action},
    ).model_dump(mode="json")


def _set_identity(workspace: CreateAgentWorkspace, arguments: dict[str, Any]) -> dict[str, Any]:
    agent = AgentIdentitySpec.model_validate(_required_dict(arguments, "agent"))
    manifest_path = workspace.root / "agent_package.json"
    assembly_path = workspace.root / "assembly_spec.json"
    manifest = _read_json(manifest_path)
    assembly = _read_json(assembly_path)
    payload = agent.model_dump(mode="json", exclude_none=True)
    manifest["agent"] = payload
    assembly["agent"] = payload
    manifest_payload = AgentPackageManifest.model_validate(manifest).model_dump(mode="json", exclude_none=True)
    assembly_payload = _validated_assembly(assembly)
    _write_json(manifest_path, manifest_payload)
    _write_json(assembly_path, assembly_payload)
    return _result("set_identity", ["agent_package.json", "assembly_spec.json"], f"Updated produced Agent identity: {agent.id}.")


def _configure_pattern_assembly(workspace: CreateAgentWorkspace, arguments: dict[str, Any]) -> dict[str, Any]:
    pattern_id = str(arguments.get("pattern_id") or "").strip()
    if pattern_id not in SUPPORTED_PATTERN_IDS:
        raise ValueError("pattern_id must be react_agent or plan_and_execute")
    prompts = arguments.get("prompts") if isinstance(arguments.get("prompts"), dict) else {}
    allowed_tool_ids = _string_list(arguments.get("allowed_tool_ids"))
    manifest_path = workspace.root / "agent_package.json"
    assembly_path = workspace.root / "assembly_spec.json"
    render_path = workspace.root / "render_manifest.json"
    manifest = _read_json(manifest_path)
    assembly = _read_json(assembly_path)
    manifest.setdefault("runtime", {})["pattern_id"] = pattern_id
    assembly.setdefault("runtime", {})["pattern_id"] = pattern_id
    agent_config = assembly.setdefault("runtime", {}).setdefault("agent_config", {})
    if pattern_id == "plan_and_execute":
        agent_config["activation"] = _activation_payload(arguments.get("activation"))
    else:
        agent_config.pop("activation", None)
    if isinstance(manifest.get("agent"), dict):
        assembly["agent"] = manifest["agent"]
    assembly["bindings"] = _standard_bindings(pattern_id=pattern_id, prompts=prompts, allowed_tool_ids=allowed_tool_ids)
    manifest_payload = AgentPackageManifest.model_validate(manifest).model_dump(mode="json", exclude_none=True)
    assembly_payload = _validated_assembly(assembly)
    render_payload = _default_render_manifest(pattern_id).model_dump(mode="json")
    _write_json(manifest_path, manifest_payload)
    _write_json(assembly_path, assembly_payload)
    _write_json(render_path, render_payload)
    return _result(
        "configure_pattern_assembly",
        ["agent_package.json", "assembly_spec.json", "render_manifest.json"],
        f"Configured standard {pattern_id} assembly.",
    )


def _activation_payload(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError(
            "activation is required for plan_and_execute and must define workflow_goal, start_when, and ask_when_missing"
        )
    payload: dict[str, str] = {}
    for key in PLAN_AND_EXECUTE_ACTIVATION_FIELDS:
        text = str(value.get(key) or "").strip()
        if not text:
            raise ValueError(f"activation.{key} is required for plan_and_execute")
        payload[key] = text
    return payload


def _upsert_package_tool(workspace: CreateAgentWorkspace, arguments: dict[str, Any]) -> dict[str, Any]:
    spec = ToolSpec.model_validate(_required_dict(arguments, "tool_spec"))
    tool_id = _package_tool_id(spec.id)
    source = str(arguments.get("tool_source") or "")
    if not source.strip():
        raise ValueError("tool_source is required")
    ast.parse(source)
    python_requirements = _string_list(arguments.get("python_requirements"))
    third_party_imports = _third_party_import_roots(source)
    if third_party_imports and not python_requirements:
        raise ValueError(
            "python_requirements is required before package tool files are written because tool_source imports third-party modules: "
            + ", ".join(sorted(third_party_imports))
        )
    manifest_path = workspace.root / "agent_package.json"
    tools_contract_path = workspace.root / "contracts" / "tools.json"
    dependencies_path = workspace.root / "contracts" / "dependencies.json"
    assembly_path = workspace.root / "assembly_spec.json"
    tool_dir = workspace.root / "tools" / tool_id
    tool_manifest_path = tool_dir / "manifest.json"
    tool_source_path = tool_dir / "tool.py"
    manifest = _read_json(manifest_path)
    _append_unique(manifest.setdefault("tools", []), f"tools/{tool_id}/manifest.json")
    manifest_payload = AgentPackageManifest.model_validate(manifest).model_dump(mode="json", exclude_none=True)

    tools_contract = _read_json(tools_contract_path)
    tools_config = tools_contract.setdefault("config", {})
    tools_config["package_tools_enabled"] = True
    tools_config.setdefault("builtin_tools_enabled", True)
    tools_config.setdefault("builtin_tool_ids", [])
    tools_contract_payload = ToolsContract.model_validate(tools_contract).model_dump(mode="json")

    dependencies = _read_json(dependencies_path)
    dependency_config = dependencies.setdefault("config", {})
    requirements = dependency_config.setdefault("python_requirements", [])
    for requirement in python_requirements:
        _append_unique(requirements, requirement)
    dependency_config.setdefault("system_packages", [])
    dependency_config.setdefault("system_binaries", [])
    dependency_config.setdefault("install_mode", "sandbox_init")
    dependencies_payload = DependenciesContract.model_validate(dependencies).model_dump(mode="json")

    assembly = _read_json(assembly_path)
    tools = assembly.setdefault("tools", [])
    _upsert_by_id(tools, spec.model_dump(mode="json"))
    _add_tool_access(assembly, tool_id, expose_to_nodes=_string_list(arguments.get("expose_to_nodes")))
    assembly_payload = _validated_assembly(assembly)
    tool_dir.mkdir(parents=True, exist_ok=True)
    _write_json(tool_manifest_path, spec.model_dump(mode="json"))
    tool_source_path.write_text(source, encoding="utf-8")
    _write_json(manifest_path, manifest_payload)
    _write_json(tools_contract_path, tools_contract_payload)
    _write_json(dependencies_path, dependencies_payload)
    _write_json(assembly_path, assembly_payload)
    changed = [
        f"tools/{tool_id}/manifest.json",
        f"tools/{tool_id}/tool.py",
        "agent_package.json",
        "contracts/tools.json",
        "contracts/dependencies.json",
        "assembly_spec.json",
    ]
    return _result("upsert_package_tool", changed, f"Upserted package tool {tool_id}.")


def _remove_package_tool(workspace: CreateAgentWorkspace, arguments: dict[str, Any]) -> dict[str, Any]:
    tool_id = _package_tool_id(str(arguments.get("tool_id") or ""))
    manifest_path = workspace.root / "agent_package.json"
    assembly_path = workspace.root / "assembly_spec.json"
    manifest = _read_json(manifest_path)
    assembly = _read_json(assembly_path)
    manifest["tools"] = [
        item
        for item in (manifest.get("tools") if isinstance(manifest.get("tools"), list) else [])
        if str(item) != f"tools/{tool_id}/manifest.json"
    ]
    assembly["tools"] = [
        item
        for item in (assembly.get("tools") if isinstance(assembly.get("tools"), list) else [])
        if not (isinstance(item, dict) and str(item.get("id") or "") == tool_id)
    ]
    _remove_tool_access(assembly, tool_id)
    manifest_payload = AgentPackageManifest.model_validate(manifest).model_dump(mode="json", exclude_none=True)
    assembly_payload = _validated_assembly(assembly)
    tool_dir = workspace.root / "tools" / tool_id
    _write_json(manifest_path, manifest_payload)
    _write_json(assembly_path, assembly_payload)
    if tool_dir.exists():
        shutil.rmtree(tool_dir)
    return _result(
        "remove_package_tool",
        ["agent_package.json", "assembly_spec.json", f"tools/{tool_id}"],
        f"Removed package tool {tool_id}.",
    )


def _third_party_import_roots(source: str) -> set[str]:
    tree = ast.parse(source)
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(_import_root(alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                continue
            imports.add(_import_root(node.module or ""))
    return {name for name in imports if _requires_declared_dependency(name)}


def _import_root(value: str) -> str:
    return value.split(".", 1)[0].strip()


def _requires_declared_dependency(name: str) -> bool:
    if not name:
        return False
    if name in sys.stdlib_module_names:
        return False
    if name in {"agent_factory", "tools"}:
        return False
    return True


def _upsert_scheduler_seed(workspace: CreateAgentWorkspace, arguments: dict[str, Any]) -> dict[str, Any]:
    seed = SchedulerSeedPlan.model_validate(_required_dict(arguments, "seed"))
    path = workspace.root / "contracts" / "scheduler_seed.json"
    contract = _read_json(path)
    config = contract.setdefault("config", {})
    seeds = config.setdefault("seeds", [])
    _upsert_by_key(seeds, seed.model_dump(mode="json"), key="seed_id")
    contract["type"] = "scheduler_seed"
    contract["version"] = "scheduler_seed_contract.v0"
    contract.setdefault("enabled", True)
    _write_json(path, SchedulerSeedContract.model_validate(contract).model_dump(mode="json"))
    return _result("upsert_scheduler_seed", ["contracts/scheduler_seed.json"], f"Upserted scheduler seed {seed.seed_id}.")


def _upsert_resources(workspace: CreateAgentWorkspace, arguments: dict[str, Any]) -> dict[str, Any]:
    values = _required_dict(arguments, "resources")
    descriptors = [
        ResourceDescriptor.model_validate(item).model_dump(mode="json")
        for item in (arguments.get("resource_descriptors") if isinstance(arguments.get("resource_descriptors"), list) else [])
    ]
    resources_path = workspace.root / "resources.json"
    contract_path = workspace.root / "contracts" / "resources.json"
    resources = _read_json(resources_path)
    resources.update(values)
    contract = _read_json(contract_path)
    config = contract.setdefault("config", {})
    config["resources_path"] = "resources.json"
    descriptor_list = config.setdefault("resource_descriptors", [])
    for descriptor in descriptors:
        _upsert_by_key(descriptor_list, descriptor, key="resource_id")
    contract_payload = ResourcesContract.model_validate(contract).model_dump(mode="json")
    _write_json(resources_path, resources)
    _write_json(contract_path, contract_payload)
    return _result("upsert_resources", ["resources.json", "contracts/resources.json"], "Upserted package runtime resources.")


def _upsert_knowledge_file(workspace: CreateAgentWorkspace, arguments: dict[str, Any]) -> dict[str, Any]:
    relative_path = _knowledge_relative_path(str(arguments.get("knowledge_path") or ""))
    content = str(arguments.get("knowledge_content") or "")
    if not content.strip():
        raise ValueError("knowledge_content is required")
    target = workspace.root / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return _result("upsert_knowledge_file", [relative_path], f"Upserted package knowledge file {relative_path}.")


def _upsert_state(workspace: CreateAgentWorkspace, arguments: dict[str, Any]) -> dict[str, Any]:
    namespace = _state_namespace(str(arguments.get("state_namespace") or "package"))
    schema = _required_dict(arguments, "state_schema")
    initial_state = _required_dict(arguments, "initial_state")
    writable_node_ids = _string_list(arguments.get("writable_node_ids"))
    schema_relative = f"state/{namespace}.schema.json"
    initial_relative = f"state/{namespace}.initial.json"
    contract = StateContract.model_validate(
        {
            "type": "state",
            "version": "state_contract.v0",
            "enabled": True,
            "config": {
                "namespace": namespace,
                "schema_path": schema_relative,
                "initial_state_path": initial_relative,
                "writable_node_ids": writable_node_ids,
            },
        }
    )
    contract_path = workspace.root / "contracts" / "state.json"
    schema_path = workspace.root / schema_relative
    initial_path = workspace.root / initial_relative
    _write_json(contract_path, contract.model_dump(mode="json"))
    _write_json(schema_path, schema)
    _write_json(initial_path, initial_state)
    return _result(
        "upsert_state",
        ["contracts/state.json", schema_relative, initial_relative],
        f"Upserted package state namespace {namespace}.",
    )


def _reset_contract(workspace: CreateAgentWorkspace, arguments: dict[str, Any]) -> dict[str, Any]:
    contract_key = str(arguments.get("contract_key") or "").strip()
    if contract_key not in RESETTABLE_CONTRACT_KEYS:
        raise ValueError("contract_key is not a resettable scaffold contract")
    relative = f"contracts/{contract_key}.json"
    _write_json(workspace.root / relative, default_contract_payload(contract_key))
    return _result("reset_contract", [relative], f"Reset scaffold contract {contract_key}.")


def _materialize_mcp_inheritance(workspace: CreateAgentWorkspace) -> dict[str, Any]:
    result = materialize_referenced_factory_mcp(workspace.root)
    changed_files = list(result.changed_files)
    inherited = ", ".join(result.inherited_tool_ids) if result.inherited_tool_ids else "none"
    summary = f"Materialized inherited MCP extension config for referenced tools: {inherited}."
    if not changed_files and not result.inherited_tool_ids:
        summary = "No referenced factory MCP candidates require inheritance materialization."
    return {
        "action": "materialize_mcp_inheritance",
        "changed_files": changed_files,
        "summary": summary,
        "mcp_inheritance": result.model_dump(),
    }


def _standard_bindings(*, pattern_id: str, prompts: dict[str, Any], allowed_tool_ids: list[str]) -> dict[str, Any]:
    inherited_tool_ids = _default_inherited_tool_ids(allowed_tool_ids)
    if pattern_id == "react_agent":
        answer_prompt = str(prompts.get("answer") or prompts.get("answer_prompt") or "Answer the user using package capabilities and approved tools when useful.")
        return {
            "services": [],
            "node_bindings": [
                _prompt_binding("answer", "cognitive.answer", "answer_prompt", answer_prompt),
                _tool_access_binding("answer", "cognitive.answer", inherited_tool_ids),
                _model_binding("answer", "cognitive.answer", "answer_prompt"),
            ],
            "hooks": [],
        }
    planner_prompt = str(prompts.get("planner") or "Create and maintain a concise dynamic plan with runtime_plan.")
    executor_prompt = str(prompts.get("executor") or "Execute the current plan step using available tools when useful, then update runtime_plan.")
    final_prompt = str(prompts.get("final_answer") or "Summarize completed plan evidence for the user. Do not call tools.")
    executor_tools = ["runtime_plan", *[tool_id for tool_id in inherited_tool_ids if tool_id != "runtime_plan"]]
    planner_tools = ["runtime_plan", *[tool_id for tool_id in inherited_tool_ids if tool_id != "runtime_plan"]]
    return {
        "services": [],
        "node_bindings": [
            _prompt_binding("planner", "cognitive.answer", "planner_prompt", planner_prompt),
            _tool_access_binding("planner", "cognitive.answer", planner_tools),
            _model_binding("planner", "cognitive.answer", "planner_prompt"),
            _prompt_binding("executor", "cognitive.answer", "executor_prompt", executor_prompt),
            _tool_access_binding("executor", "cognitive.answer", executor_tools),
            _model_binding("executor", "cognitive.answer", "executor_prompt"),
            _prompt_binding("final_answer", "cognitive.answer", "final_answer_prompt", final_prompt),
            _model_binding("final_answer", "cognitive.answer", "final_answer_prompt"),
        ],
        "hooks": [],
    }


def _prompt_binding(node_id: str, impl: str, prompt_id: str, template: str) -> dict[str, Any]:
    return {
        "binding_id": f"{node_id}_prompt",
        "binding_type": "prompt",
        "target": {"node_id": node_id, "impl": impl},
        "payload": {"prompt_id": prompt_id, "template": template, "variables": []},
    }


def _tool_access_binding(node_id: str, impl: str, allowed_tool_ids: list[str]) -> dict[str, Any]:
    return {
        "binding_id": f"{node_id}_tool_access",
        "binding_type": "tool_access",
        "target": {"node_id": node_id, "impl": impl},
        "payload": {"allowed_tool_ids": _unique_strings(allowed_tool_ids), "approval_policy": "standard"},
    }


def _default_inherited_tool_ids(allowed_tool_ids: list[str]) -> list[str]:
    return _unique_strings([*DEFAULT_INHERITED_RUNTIME_TOOL_IDS, *allowed_tool_ids])


def _model_binding(node_id: str, impl: str, prompt_id: str) -> dict[str, Any]:
    return {
        "binding_id": f"{node_id}_model_operation",
        "binding_type": "model_operation",
        "target": {"node_id": node_id, "impl": impl},
        "payload": {
            "operation": "tool_bound_chat",
            "model_role": "main",
            "output_schema": {"type": "object", "additionalProperties": True},
            "write_target": {"section": "context"},
            "max_attempts": 3,
            "prompt_id": prompt_id,
        },
    }


def _add_tool_access(assembly: dict[str, Any], tool_id: str, *, expose_to_nodes: list[str]) -> None:
    pattern_id = str((assembly.get("runtime") or {}).get("pattern_id") or "react_agent")
    default_nodes = ["executor"] if pattern_id == "plan_and_execute" else ["answer"]
    node_ids = expose_to_nodes or default_nodes
    bindings = assembly.setdefault("bindings", {}).setdefault("node_bindings", [])
    impl_by_node = {"answer": "cognitive.answer", "planner": "cognitive.answer", "executor": "cognitive.answer"}
    for node_id in node_ids:
        binding = _find_tool_access_binding(bindings, node_id)
        if binding is None:
            binding = _tool_access_binding(node_id, impl_by_node.get(node_id, "cognitive.answer"), [])
            bindings.append(binding)
        allowed = binding.setdefault("payload", {}).setdefault("allowed_tool_ids", [])
        _append_unique(allowed, tool_id)
        binding["payload"]["allowed_tool_ids"] = _unique_strings(allowed)


def _find_tool_access_binding(bindings: list[Any], node_id: str) -> dict[str, Any] | None:
    for binding in bindings:
        if not isinstance(binding, dict) or binding.get("binding_type") != "tool_access":
            continue
        target = binding.get("target") if isinstance(binding.get("target"), dict) else {}
        if target.get("node_id") == node_id:
            return binding
    return None


def _remove_tool_access(assembly: dict[str, Any], tool_id: str) -> None:
    bindings = assembly.setdefault("bindings", {}).setdefault("node_bindings", [])
    for binding in bindings:
        if not isinstance(binding, dict) or binding.get("binding_type") != "tool_access":
            continue
        payload = binding.setdefault("payload", {})
        allowed = payload.get("allowed_tool_ids")
        if isinstance(allowed, list):
            payload["allowed_tool_ids"] = [item for item in _unique_strings(allowed) if item != tool_id]


def _workspace(resources: dict[str, Any]) -> CreateAgentWorkspace:
    raw = resources.get("workspace")
    if isinstance(raw, str):
        return CreateAgentWorkspace(raw)
    if isinstance(raw, dict) and isinstance(raw.get("root"), str):
        return CreateAgentWorkspace(raw["root"])
    raise ValueError("create_agent workspace resource is missing")


def _required_dict(arguments: dict[str, Any], key: str) -> dict[str, Any]:
    value = arguments.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be an object")
    return value


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return payload


def _knowledge_relative_path(value: str) -> str:
    requested = Path(value.strip())
    if requested.is_absolute() or not value.strip():
        raise ValueError("knowledge_path must be a non-empty package-relative path under knowledge/")
    normalized = requested.as_posix()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if normalized == "knowledge":
        raise ValueError("knowledge_path must identify a file under knowledge/")
    if normalized.startswith("knowledge/"):
        relative = normalized
    else:
        relative = f"knowledge/{normalized}"
    resolved = Path(relative)
    if any(part in {"", ".", ".."} for part in resolved.parts):
        raise ValueError("knowledge_path must not contain empty, current, or parent directory segments")
    return resolved.as_posix()


def _state_namespace(value: str) -> str:
    namespace = value.strip() or "package"
    path = Path(namespace)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("state_namespace must be a simple package state namespace")
    if "/" in namespace or "\\" in namespace:
        raise ValueError("state_namespace must not contain path separators")
    return namespace


def _package_tool_id(value: str) -> str:
    tool_id = value.strip()
    if not tool_id:
        raise ValueError("tool_id is required")
    path = Path(tool_id)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("tool_id must be a simple package tool id")
    if "/" in tool_id or "\\" in tool_id:
        raise ValueError("tool_id must not contain path separators")
    return tool_id


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _validated_assembly(payload: dict[str, Any]) -> dict[str, Any]:
    return AgentAssemblySpec.model_validate(payload).model_dump(mode="json", exclude_none=True)


def _append_unique(values: list[Any], value: str) -> None:
    if value and value not in values:
        values.append(value)


def _unique_strings(values: list[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _string_list(value: Any) -> list[str]:
    return _unique_strings(value if isinstance(value, list) else [])


def _upsert_by_id(values: list[Any], payload: dict[str, Any]) -> None:
    _upsert_by_key(values, payload, key="id")


def _upsert_by_key(values: list[Any], payload: dict[str, Any], *, key: str) -> None:
    target = str(payload.get(key) or "")
    for index, item in enumerate(values):
        if isinstance(item, dict) and str(item.get(key) or "") == target:
            values[index] = payload
            return
    values.append(payload)


def _result(action: str, changed_files: list[str], summary: str) -> dict[str, Any]:
    return {"action": action, "changed_files": changed_files, "summary": summary}
