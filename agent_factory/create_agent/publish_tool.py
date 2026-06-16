from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import shutil
from uuid import uuid4
from typing import Any

from agent_factory.assembly.compiler import AgentAssemblyCompiler
from agent_factory.create_agent.mcp_inheritance import materialize_referenced_factory_mcp
from agent_factory.create_agent.models import PUBLISH_FILE
from agent_factory.create_agent.validation_state import package_fingerprint
from agent_factory.create_agent.workspace import CreateAgentWorkspace
from agent_factory.package_runtime import register_package_patterns
from agent_factory.paths import factory_artifact_path
from agent_factory.runtime_contracts import AgentPackageLoader, RuntimeBuildPlanner
from agent_factory.runtime_contracts.builtins import default_runtime_contract_registry
from agent_factory.runtime_kernel.kernel import RuntimeKernelFacade
from agent_factory.runtime_kernel.persistence import LangGraphCheckpointerConfig, LangGraphStoreConfig
from agent_factory.tooling.envelope import tool_envelope
from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolRiskResult, ToolSpec


CREATE_AGENT_PUBLISH_TOOL_ID = "create_agent_publish"
CREATE_AGENT_PACKAGE_REGISTRY_RESOURCE = "create_agent_package_registry"


def build_create_agent_publish_tool_spec() -> ToolSpec:
    return ToolSpec(
        id=CREATE_AGENT_PUBLISH_TOOL_ID,
        description=(
            "Publish a fully validated create-agent workspace into the AgentPackage registry. "
            "Use only after the user confirms publication."
        ),
        entrypoint="agent_factory.create_agent.publish_tool:run",
        input_schema={
            "type": "object",
            "properties": {
                "confirmation": {
                    "type": "string",
                    "description": "Short natural-language record of the user's publish confirmation.",
                }
            },
            "required": ["confirmation"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "published": {"type": "boolean"},
                "package_id": {"type": "string"},
                "package_path": {"type": "string"},
                "manifest_path": {"type": "string"},
                "published_at": {"type": "string"},
                "report_path": {"type": "string"},
                "publish_state_path": {"type": "string"},
            },
            "required": [
                "published",
                "package_id",
                "package_path",
                "manifest_path",
                "published_at",
                "report_path",
                "publish_state_path",
            ],
            "additionalProperties": False,
        },
        resources={
            "workspace": "create_agent_workspace",
            "package_registry": CREATE_AGENT_PACKAGE_REGISTRY_RESOURCE,
        },
        risk_level="medium",
        risk_evaluator=ToolRiskEvaluatorConfig(hard="agent_factory.create_agent.publish_tool:evaluate_risk"),
        concurrent=False,
    )


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    workspace = _workspace(resources)
    confirmation = str(arguments.get("confirmation") or "").strip()
    if not confirmation:
        raise ValueError("confirmation is required")
    registry_root = _registry_root(resources)
    materialize_referenced_factory_mcp(workspace.root)
    _assert_publish_ready(workspace)

    package = AgentPackageLoader().load_path(workspace.package_manifest_path())
    package_id = _package_id(package)
    target = _safe_child(registry_root, package_id)
    staging_root = _safe_child(registry_root, ".publish_staging")
    staging = staging_root / f"{package_id}-{uuid4().hex}"
    staging_root.mkdir(parents=True, exist_ok=True)
    if staging.exists():
        shutil.rmtree(staging)
    shutil.copytree(workspace.root, staging, ignore=_copy_ignore)
    _assert_runtime_ready(staging)

    registry_root.mkdir(parents=True, exist_ok=True)
    backup = _safe_child(registry_root, f".publish_backup_{package_id}_{uuid4().hex}")
    try:
        if target.exists():
            target.replace(backup)
        staging.replace(target)
    except Exception:
        if target.exists():
            shutil.rmtree(target)
        if backup.exists():
            backup.replace(target)
        raise
    finally:
        if backup.exists():
            shutil.rmtree(backup)
        if staging.exists():
            shutil.rmtree(staging)

    published_at = datetime.now(UTC).isoformat()
    report = {
        "version": "agent_package_publish_report.v0",
        "status": "available",
        "package_id": package_id,
        "source_workspace": str(workspace.root),
        "package_path": str(target),
        "manifest_path": str(target / "agent_package.json"),
        "published_at": published_at,
        "confirmation": confirmation,
        "validation": workspace.read_validation().to_digest().model_dump(mode="json") if workspace.read_validation() else None,
        "package_fingerprint": package_fingerprint(target),
    }
    report_path = target / "package_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    workspace.write_publish_report(report)
    return tool_envelope({
        "published": True,
        "package_id": package_id,
        "package_path": str(target),
        "manifest_path": str(target / "agent_package.json"),
        "published_at": published_at,
        "report_path": str(report_path),
        "publish_state_path": str(workspace.publish_path),
    })


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    confirmation = str(arguments.get("confirmation") or "").strip()
    if not confirmation:
        return ToolRiskResult(
            action="deny",
            risk_level="medium",
            reasons=["confirmation is required before publishing"],
        ).model_dump(mode="json")
    return ToolRiskResult(
        action="allow",
        risk_level="medium",
        reasons=["publish confirmation is present; runtime readiness is checked by the tool"],
    ).model_dump(mode="json")


def _assert_publish_ready(workspace: CreateAgentWorkspace) -> None:
    active = workspace.read_system_state().active_stage()
    if active is None or active.system_id != "validation_publish":
        raise ValueError("publish requires active focus validation_publish")
    validation = workspace.read_validation()
    if validation is None or validation.status != "passed":
        raise ValueError("publish requires validation to pass")
    validation_state = workspace.read_validation_state()
    if validation_state is None:
        raise ValueError("publish requires validation fingerprint state")
    if validation_state.validation_scope != "full_static":
        raise ValueError("publish requires the latest package-changing validation to be full_static")
    current_fingerprint = package_fingerprint(workspace.root)
    if current_fingerprint != validation_state.package_fingerprint:
        raise ValueError("package files changed after validation; run final validation again before publishing")
    decision = workspace.read_publish_decision()
    if decision.decision != "approve":
        raise ValueError("publish requires explicit user approval from the publish confirmation gate")
    if decision.package_fingerprint != current_fingerprint:
        raise ValueError("package files changed after user approval; run final validation and ask for publish confirmation again")
    if decision.validation_scope != "full_static" or decision.validation_status != "passed":
        raise ValueError("publish approval must correspond to a passed full_static validation")
    if not workspace.package_manifest_path().is_file():
        raise ValueError("agent_package.json is missing")


def _assert_runtime_ready(package_root: Path) -> None:
    package = AgentPackageLoader().load_path(package_root / "agent_package.json")
    compiler = AgentAssemblyCompiler(
        facade=RuntimeKernelFacade(
            checkpointer_config=LangGraphCheckpointerConfig(backend="memory"),
            memory_store_config=LangGraphStoreConfig(backend="memory"),
        )
    )
    runtime_build = RuntimeBuildPlanner(registry=default_runtime_contract_registry()).build(
        package,
        base_services=compiler.facade.instance.services,
    )
    register_package_patterns(facade=compiler.facade, package=package, runtime_build=runtime_build)
    compiler.compile(package.assembly_spec, runtime_build=runtime_build)


def _package_id(package: Any) -> str:
    value = str(getattr(package.assembly_spec.agent, "id", "") or "").strip()
    if not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise ValueError(f"invalid package id: {value!r}")
    return value


def _workspace(resources: dict[str, Any]) -> CreateAgentWorkspace:
    raw = resources.get("workspace")
    if isinstance(raw, str):
        return CreateAgentWorkspace(raw)
    if isinstance(raw, dict) and isinstance(raw.get("root"), str):
        return CreateAgentWorkspace(raw["root"])
    raise ValueError("create_agent workspace resource is missing")


def _registry_root(resources: dict[str, Any]) -> Path:
    raw = resources.get("package_registry")
    if isinstance(raw, str) and raw.strip():
        return Path(raw).expanduser().resolve()
    return factory_artifact_path("packages")


def _safe_child(root: Path, child: str) -> Path:
    target = (root / child).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"path escapes package registry: {child}") from exc
    return target


def _copy_ignore(directory: str, names: list[str]) -> set[str]:
    ignored = {"__pycache__", ".DS_Store"}
    if Path(directory).name == ".":
        ignored.update({PUBLISH_FILE})
    ignored.update(name for name in names if name in {".factory", ".agent_runtime"})
    return ignored
