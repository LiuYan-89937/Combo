from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import shutil
from uuid import uuid4
from typing import Any

from agent_factory.assembly.compiler import AgentAssemblyCompiler
from agent_factory.agent_registry import refresh_agent_registry_index
from agent_factory.create_agent.models import CreateAgentPublishDecision, PUBLISH_FILE
from agent_factory.create_agent.package_paths import is_transient_package_path, normalize_package_relative
from agent_factory.create_agent.stage_sync import sync_publish_stage
from agent_factory.create_agent.validation_state import package_fingerprint
from agent_factory.create_agent.workspace import CreateAgentWorkspace
from agent_factory.environment_system import EnvironmentResolver
from agent_factory.resource_system import ResourceStore
from agent_factory.runtime_contracts import ResourcesContract
from agent_factory.paths import factory_artifact_path
from agent_factory.runtime_contracts import AgentPackageLoader, RuntimeBuildPlanner
from agent_factory.runtime_contracts.builtins import default_runtime_contract_registry
from agent_factory.runtime_kernel.kernel import RuntimeKernelFacade
from agent_factory.runtime_kernel.persistence import LangGraphCheckpointerConfig, LangGraphStoreConfig


CREATE_AGENT_PACKAGE_REGISTRY_RESOURCE = "create_agent_package_registry"
PACKAGE_ASSET_DIRS = {
    "artifacts",
    "extensions",
    "formatters",
    "knowledge",
    "patterns",
    "policies",
    "prompts",
    "resources",
    "strategies",
    "tools",
}


def confirm_and_publish(
    *,
    workspace: CreateAgentWorkspace,
    confirmation: str,
    registry_root: Path | None = None,
) -> dict[str, Any]:
    confirmation_text = str(confirmation or "").strip()
    if not confirmation_text:
        raise ValueError("confirmation is required")
    validation = workspace.read_validation()
    workspace.write_publish_decision(
        CreateAgentPublishDecision(
            decision="approve",
            input_text=confirmation_text,
            package_fingerprint=package_fingerprint(workspace.root),
            validation_scope=validation.validation_scope if validation else "",
            validation_status=validation.status if validation else "",
        )
    )
    return publish_workspace(
        workspace=workspace,
        confirmation=confirmation_text,
        registry_root=registry_root,
    )


def publish_workspace(
    *,
    workspace: CreateAgentWorkspace,
    confirmation: str,
    registry_root: Path | None = None,
) -> dict[str, Any]:
    confirmation_text = str(confirmation or "").strip()
    if not confirmation_text:
        raise ValueError("confirmation is required")
    registry_root = registry_root or factory_artifact_path("packages")
    _assert_publish_ready(workspace)
    package = AgentPackageLoader().load_path(workspace.package_manifest_path())
    package_id = _package_id(package)
    resource_contract = ResourcesContract.model_validate(package.contracts.get("resources") or {})
    target = _safe_child(registry_root, package_id)
    staging_root = _safe_child(registry_root, ".publish_staging")
    staging = staging_root / f"{package_id}-{uuid4().hex}"
    staging_root.mkdir(parents=True, exist_ok=True)
    if staging.exists():
        shutil.rmtree(staging)
    _copy_publishable_package(workspace.root, staging)
    EnvironmentResolver().ensure(staging)
    _assert_runtime_ready(staging)
    _prune_transient_paths(staging)

    registry_root.mkdir(parents=True, exist_ok=True)
    backup = _safe_child(registry_root, f".publish_backup_{package_id}_{uuid4().hex}")
    try:
        if target.exists():
            target.replace(backup)
        staging.replace(target)
        ResourceStore().transfer(workspace.root.name, package_id, resource_contract.config.resource_descriptors)
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
        "confirmation": confirmation_text,
        "validation": workspace.read_validation().to_digest().model_dump(mode="json") if workspace.read_validation() else None,
        "package_fingerprint": package_fingerprint(target),
    }
    report_path = target / "package_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    workspace.write_publish_report(report)
    sync_publish_stage(workspace)
    agent_registry_refresh = _refresh_agent_registry_index(package_id)
    return {
        "published": True,
        "package_id": package_id,
        "package_path": str(target),
        "manifest_path": str(target / "agent_package.json"),
        "published_at": published_at,
        "report_path": str(report_path),
        "publish_state_path": str(workspace.publish_path),
        "agent_registry_refresh": agent_registry_refresh,
    }


def _refresh_agent_registry_index(package_id: str) -> dict[str, Any]:
    try:
        return refresh_agent_registry_index(package_id)
    except Exception as exc:
        return {"status": "failed", "message": f"{type(exc).__name__}: {exc}"}


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
        raise ValueError("publish requires explicit user approval from the Web publish API")
    if decision.package_fingerprint != current_fingerprint:
        raise ValueError("package files changed after user approval; run final validation and publish from the Web UI again")
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
    compiler.compile(package.assembly_spec, runtime_build=runtime_build)


def _package_id(package: Any) -> str:
    value = str(getattr(package.manifest.agent, "id", "") or "").strip()
    if not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise ValueError(f"invalid package id: {value!r}")
    return value


def _safe_child(root: Path, child: str) -> Path:
    target = (root / child).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"path escapes package registry: {child}") from exc
    return target


def _copy_publishable_package(source: Path, target: Path) -> None:
    manifest = _read_manifest_payload(source)
    publishable_files, publishable_dirs = _publishable_paths(manifest)
    target.mkdir(parents=True, exist_ok=True)
    for path in sorted(item for item in source.rglob("*") if item.is_file()):
        relative = path.relative_to(source).as_posix()
        if not _is_publishable(relative, publishable_files=publishable_files, publishable_dirs=publishable_dirs):
            continue
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)


def _read_manifest_payload(root: Path) -> dict[str, Any]:
    path = root / "agent_package.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError("agent_package.json must be readable before publish") from exc
    if not isinstance(payload, dict):
        raise ValueError("agent_package.json must contain a JSON object")
    return payload


def _publishable_paths(manifest: dict[str, Any]) -> tuple[set[str], set[str]]:
    files = {"agent_package.json", "environment.lock.json"}
    dirs: set[str] = set()
    for key in ("assembly_spec_path",):
        _add_manifest_file(files, manifest.get(key))
    contracts = manifest.get("contracts")
    if isinstance(contracts, dict):
        for value in contracts.values():
            _add_manifest_file(files, value)
    for key in ("bindings", "patterns", "prompts", "tools", "policies", "strategies", "formatters"):
        value = manifest.get(key)
        if isinstance(value, list):
            for item in value:
                _add_manifest_file(files, item)
                _add_asset_dir_for_manifest_path(dirs, item)
        elif isinstance(value, dict):
            for item in value.values():
                _add_manifest_file(files, item)
                _add_asset_dir_for_manifest_path(dirs, item)
    return files, dirs | PACKAGE_ASSET_DIRS


def _add_manifest_file(files: set[str], value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        return
    relative = normalize_package_relative(value)
    if relative and not is_transient_package_path(relative):
        files.add(relative)


def _add_asset_dir_for_manifest_path(dirs: set[str], value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        return
    relative = normalize_package_relative(value)
    parts = relative.split("/")
    if parts and parts[0] in PACKAGE_ASSET_DIRS:
        dirs.add(parts[0] if len(parts) == 1 else "/".join(parts[:-1]))


def _is_publishable(relative: str, *, publishable_files: set[str], publishable_dirs: set[str]) -> bool:
    normalized = normalize_package_relative(relative)
    if normalized == normalize_package_relative(PUBLISH_FILE):
        return False
    if is_transient_package_path(normalized):
        return False
    if normalized in publishable_files:
        return True
    return any(normalized == directory or normalized.startswith(f"{directory}/") for directory in publishable_dirs)


def _prune_transient_paths(root: Path) -> None:
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError:
            continue
        if not is_transient_package_path(relative):
            continue
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
