from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from threading import RLock
from typing import Any, Callable, Mapping

from combo.dynamic_runtime.capability_blob_store import CapabilityBlobStore
from combo.dynamic_runtime.capability_definitions import ToolDefinition
from combo.dynamic_runtime.repositories import ConversationStore
from combo.dynamic_runtime.snapshot_tool_execution import ToolEntrypointLease
from combo.environment_system import DependencyPoolService
from combo.resource_system import ResourceDescriptor, ResourceIdentity, ResourceStore
from combo.runtime_protocol import (
    CapabilityProjectionSnapshot,
    CapabilitySnapshot,
    RuntimeInstance,
)
from combo.tooling.execution_context import register_runtime_tool_cancellation


class ToolPackageRuntime:
    """Materialize immutable ToolPackages and execute them in cancellable child processes."""

    def __init__(
        self,
        *,
        blobs: CapabilityBlobStore,
        runtime_root: Path,
        dependency_pool: DependencyPoolService,
        conversations: ConversationStore,
        resource_store: ResourceStore,
        base_environment: Mapping[str, str],
    ) -> None:
        self._blobs = blobs
        self._runtime_root = Path(runtime_root).expanduser().resolve()
        self._dependency_pool = dependency_pool
        self._conversations = conversations
        self._resource_store = resource_store
        self._base_environment = dict(base_environment)
        self._lock = RLock()

    def acquire(
        self,
        *,
        definition: ToolDefinition,
        projection: CapabilityProjectionSnapshot,
        capability_snapshot: CapabilitySnapshot,
        runtime_instance: RuntimeInstance,
    ) -> ToolEntrypointLease:
        del capability_snapshot
        implementation = definition.implementation
        if implementation.kind != "python_package" or implementation.package_digest is None:
            raise ValueError("ToolPackage runtime requires a python_package implementation")
        package_root, python_paths = self.prepare(definition)
        if implementation.package_runtime == "trusted_in_process":
            entrypoint = self._trusted_entrypoint(
                package_root=package_root,
                package_digest=implementation.package_digest,
                target=implementation.entrypoint,
            )
            risk_evaluator = (
                None
                if implementation.hard_risk_evaluator_entrypoint is None
                else self._trusted_entrypoint(
                    package_root=package_root,
                    package_digest=implementation.package_digest,
                    target=implementation.hard_risk_evaluator_entrypoint,
                )
            )
            return ToolEntrypointLease(
                entrypoint=entrypoint,
                hard_risk_evaluator=risk_evaluator,
                release_callback=lambda: None,
            )
        workspace_root = self._workspace_root(runtime_instance)
        context = {
            "principal_id": runtime_instance.request.principal_id,
            "session_id": runtime_instance.request.session_id,
            "turn_id": runtime_instance.request.turn_id,
            "workspace_id": runtime_instance.request.workspace_id,
            "runtime_instance_id": runtime_instance.runtime_instance_id,
            "runtime_role": runtime_instance.request.runtime_role,
            "workspace_path": str(workspace_root),
            "package_path": str(package_root),
            "resources_path": str(package_root / "resources"),
            "capability_id": projection.capability_id,
            "capability_revision": projection.revision,
        }
        context_properties = definition.context_schema.get("properties")
        required_context = {"package_path", "resources_path", "workspace_path"}
        declared_context = (
            {str(key) for key in context_properties}
            if isinstance(context_properties, dict)
            else set()
        )
        allowed_context = required_context | declared_context
        context = {key: value for key, value in context.items() if key in allowed_context}
        context.update(
            self._configured_context(
                capability_id=projection.capability_id,
                capability_revision=projection.revision,
                context_properties=context_properties,
                reserved_keys=set(context),
            )
        )

        def invoke(*, arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
            if resources:
                raise RuntimeError("local ToolPackages cannot receive in-process platform resources")
            return self._invoke(
                definition=definition,
                package_root=package_root,
                python_paths=python_paths,
                workspace_root=workspace_root,
                arguments=arguments,
                context=context,
            )

        return ToolEntrypointLease(
            entrypoint=invoke,
            hard_risk_evaluator=None,
            release_callback=lambda: None,
        )

    def _configured_context(
        self,
        *,
        capability_id: str,
        capability_revision: int,
        context_properties: object,
        reserved_keys: set[str],
    ) -> dict[str, Any]:
        """Load user-configured ToolPackage context values without exposing them in snapshots."""
        if not isinstance(context_properties, dict):
            return {}
        descriptors = {
            str(name): ResourceDescriptor(
                identity=ResourceIdentity(
                    owner_kind="tool",
                    owner_id=capability_id,
                    owner_revision=capability_revision,
                    resource_id=str(name),
                    resource_revision=1,
                ),
                purpose="tool_context",
                required=False,
                value_schema={"type": str(schema.get("type", "string"))}
                if isinstance(schema, dict)
                else {"type": "string"},
            )
            for name, schema in context_properties.items()
            if str(name) not in reserved_keys
        }
        if not descriptors:
            return {}
        statuses = self._resource_store.status(list(descriptors.values()))
        configured: dict[str, Any] = {}
        for status in statuses:
            if not bool(status.get("configured")):
                continue
            name = str(status["identity"]["resource_id"])
            configured[name] = self._resource_store.resolve(descriptors[name])
        return configured

    @staticmethod
    def _trusted_entrypoint(*, package_root: Path, package_digest: str, target: str):
        module_name, function_name = target.split(":", 1)
        module_path = package_root.joinpath(*module_name.split(".")).with_suffix(".py").resolve()
        if package_root not in module_path.parents or not module_path.is_file():
            raise ValueError("trusted ToolPackage entrypoint resolves outside the package")
        spec = importlib.util.spec_from_file_location(
            f"combo_trusted_tool_{package_digest}_{module_name.replace('.', '_')}",
            module_path,
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load trusted ToolPackage entrypoint: {module_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        function = getattr(module, function_name, None)
        if not callable(function):
            raise TypeError(f"trusted ToolPackage entrypoint is not callable: {target}")
        return function

    def prepare(
        self,
        definition: ToolDefinition,
        *,
        on_progress: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> tuple[Path, tuple[Path, ...]]:
        implementation = definition.implementation
        if implementation.kind != "python_package" or implementation.package_digest is None:
            raise ValueError("ToolPackage preparation requires a python_package implementation")
        with self._lock:
            package_root = self._materialize_package(definition)
            resolution = self._dependency_pool.resolve_profile(
                python_requirements=implementation.python_requirements,
                timeout_seconds=max(1, int(definition.runtime_policy.timeout_seconds)),
                on_progress=on_progress,
            )
            python_paths = tuple(
                self._dependency_pool.python_import_path(entry)
                for entry in resolution.python_entries
            )
            if any(not path.is_dir() for path in python_paths):
                raise RuntimeError("ToolPackage dependency profile contains unavailable Python paths")
            self._validate_import(definition, package_root, python_paths)
            return package_root, python_paths

    def _validate_import(
        self,
        definition: ToolDefinition,
        package_root: Path,
        python_paths: tuple[Path, ...],
    ) -> None:
        implementation = definition.implementation
        marker = package_root / ".import-validated"
        if marker.is_file() and marker.read_text(encoding="utf-8").strip() == implementation.package_digest:
            return
        request = {
            "operation": "validate_import",
            "package_root": str(package_root),
            "package_digest": implementation.package_digest,
            "entrypoint": implementation.entrypoint,
        }
        completed = subprocess.run(
            [sys.executable, "-m", "combo.tooling.package_worker"],
            cwd=package_root,
            env=self._worker_environment(
                python_paths=python_paths,
                package_root=package_root,
                workspace_root=package_root,
            ),
            input=json.dumps(request, ensure_ascii=False),
            capture_output=True,
            text=True,
            timeout=definition.runtime_policy.timeout_seconds,
            check=False,
        )
        try:
            response = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"ToolPackage import validation returned invalid JSON: {(completed.stderr or completed.stdout)[-4000:]}"
            ) from exc
        if completed.returncode != 0 or not isinstance(response, dict) or response.get("validated") is not True:
            error = response.get("worker_error") if isinstance(response, dict) else None
            detail = error.get("message") if isinstance(error, dict) else (completed.stderr or completed.stdout)[-4000:]
            raise RuntimeError(f"ToolPackage import validation failed: {detail}")
        marker.write_text(str(implementation.package_digest) + "\n", encoding="utf-8")

    def _materialize_package(self, definition: ToolDefinition) -> Path:
        implementation = definition.implementation
        assert implementation.package_digest is not None
        root = self._runtime_root / "packages" / implementation.package_digest
        marker = root / ".complete.json"
        if marker.is_file():
            document = json.loads(marker.read_text(encoding="utf-8"))
            if document.get("package_digest") == implementation.package_digest:
                return root
        root.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".tool-package-", dir=root.parent))
        try:
            for reference in implementation.package_files:
                destination = staging / reference.logical_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(self._blobs.read(reference))
            (staging / ".complete.json").write_text(
                json.dumps({"package_digest": implementation.package_digest}, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            if root.exists():
                shutil.rmtree(root)
            os.replace(staging, root)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        return root

    def _workspace_root(self, runtime_instance: RuntimeInstance) -> Path:
        request = runtime_instance.request
        return Path(self._conversations.require_workspace_root(
            request.workspace_id,
            request.principal_id,
        ))

    def _invoke(
        self,
        *,
        definition: ToolDefinition,
        package_root: Path,
        python_paths: tuple[Path, ...],
        workspace_root: Path,
        arguments: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        implementation = definition.implementation
        environment = self._worker_environment(
            python_paths=python_paths,
            package_root=package_root,
            workspace_root=workspace_root,
        )
        request = {
            "package_root": str(package_root),
            "package_digest": implementation.package_digest,
            "entrypoint": implementation.entrypoint,
            "arguments": arguments,
            "context": context,
        }
        process = subprocess.Popen(
            [sys.executable, "-m", "combo.tooling.package_worker"],
            cwd=workspace_root,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        unregister = register_runtime_tool_cancellation(lambda: _terminate(process))
        try:
            try:
                stdout, stderr = process.communicate(
                    json.dumps(request, ensure_ascii=False),
                    timeout=definition.runtime_policy.timeout_seconds,
                )
            except subprocess.TimeoutExpired as exc:
                _terminate(process)
                process.communicate()
                raise TimeoutError(
                    f"ToolPackage execution timed out after {definition.runtime_policy.timeout_seconds:g}s"
                ) from exc
        finally:
            unregister()
        try:
            response = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"ToolPackage worker returned invalid JSON: {(stderr or stdout)[-4000:]}") from exc
        if process.returncode != 0:
            error = response.get("worker_error") if isinstance(response, dict) else None
            detail = error.get("message") if isinstance(error, dict) else (stderr or stdout)[-4000:]
            raise RuntimeError(f"ToolPackage worker failed: {detail}")
        if not isinstance(response, dict):
            raise RuntimeError("ToolPackage worker result must be a JSON object")
        return response

    def _worker_environment(
        self,
        *,
        python_paths: tuple[Path, ...],
        package_root: Path,
        workspace_root: Path,
    ) -> dict[str, str]:
        environment = dict(self._base_environment)
        inherited_python_path = environment.get("PYTHONPATH", "")
        application_root = str(Path(__file__).resolve().parents[2])
        environment["PYTHONPATH"] = os.pathsep.join(
            [str(path) for path in python_paths] + [application_root]
            + ([inherited_python_path] if inherited_python_path else [])
        )
        environment["COMBO_WORKSPACE"] = str(workspace_root)
        environment["COMBO_TOOL_PACKAGE"] = str(package_root)
        return environment


def _terminate(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
