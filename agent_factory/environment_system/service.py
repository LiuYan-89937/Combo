"""Content-addressed dependency environment preparation service."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import sysconfig
import threading
from typing import Any

from agent_factory.runtime_protocol import CapabilityRevisionRef, DependencyEnvironmentRef

from .pool import (
    DependencyPool,
    DependencyPoolError,
    DependencyPoolResolution,
    _sha256_file,
    _normalized_values,
)
from .python_requirements import (
    PythonRequirementError,
    normalize_python_requirements,
)
from agent_factory.observed_process import (
    ObservedProcessCancelled,
    ObservedProcessInactivityTimeout,
    run_observed_process,
)


DependencyProgress = Callable[[str, dict[str, Any]], None]


@dataclass(frozen=True, slots=True)
class DependencyRequest:
    capability_refs: tuple[CapabilityRevisionRef, ...]
    python_requirements: tuple[str, ...] = ()
    npm_requirements: tuple[str, ...] = ()
    required_executables: tuple[str, ...] = ()
    timeout_seconds: int | None = None

    def __post_init__(self) -> None:
        if not self.capability_refs:
            raise ValueError("dependency request requires capability revision references")
        if any(item.kind != "dependency" for item in self.capability_refs):
            raise ValueError("dependency request may only contain dependency capabilities")
        identities = {(item.capability_id, item.revision, item.content_digest) for item in self.capability_refs}
        if len(identities) != len(self.capability_refs):
            raise ValueError("dependency request capability references must be unique")
        if self.timeout_seconds is not None and self.timeout_seconds < 1:
            raise ValueError("dependency request timeout_seconds must be positive")


@dataclass(frozen=True, slots=True)
class PreparedDependencyEnvironment:
    reference: DependencyEnvironmentRef
    pool: dict[str, Any]
    required_executables: tuple[str, ...]
    runtime_compatibility: dict[str, str]


class DependencyPoolService(DependencyPool):
    """Prepare immutable environments from normalized capability dependencies."""

    def resolve_profile(
        self,
        *,
        python_requirements: tuple[str, ...] = (),
        npm_requirements: tuple[str, ...] = (),
        timeout_seconds: int | None = None,
        on_progress: DependencyProgress | None = None,
        cancel_event: threading.Event | None = None,
    ) -> DependencyPoolResolution:
        """Resolve a reusable dependency profile without inventing capability identities."""
        return self._resolve(
            python_requirements=list(python_requirements),
            npm_requirements=list(npm_requirements),
            timeout_seconds=timeout_seconds,
            on_progress=on_progress,
            cancel_event=cancel_event,
        )

    def ensure(
        self,
        request: DependencyRequest,
        *,
        on_progress: DependencyProgress | None = None,
        cancel_event: threading.Event | None = None,
    ) -> PreparedDependencyEnvironment:
        compatibility = self._native_runtime_compatibility()
        normalized_request = {
            "capability_refs": [
                item.model_dump(mode="json")
                for item in sorted(request.capability_refs, key=lambda item: (item.capability_id, item.revision))
            ],
            "python_requirements": normalize_python_requirements(list(request.python_requirements)),
            "npm_requirements": _normalized_values(list(request.npm_requirements)),
            "required_executables": _normalized_values(list(request.required_executables)),
            "runtime_compatibility": compatibility,
        }
        resolution = self.resolve_profile(
            python_requirements=tuple(normalized_request["python_requirements"]),
            npm_requirements=tuple(normalized_request["npm_requirements"]),
            timeout_seconds=request.timeout_seconds,
            on_progress=on_progress,
            cancel_event=cancel_event,
        )
        digest = _fingerprint({"request": normalized_request, "pool": resolution.to_lock_payload()})
        return PreparedDependencyEnvironment(
            reference=DependencyEnvironmentRef(
                environment_id=f"dependency-environment-{digest}",
                revision=1,
                content_digest=digest,
                capability_refs=tuple(normalized_request_ref for normalized_request_ref in sorted(
                    request.capability_refs,
                    key=lambda item: (item.capability_id, item.revision, item.content_digest),
                )),
            ),
            pool=resolution.to_lock_payload(),
            required_executables=tuple(normalized_request["required_executables"]),
            runtime_compatibility=compatibility,
        )

    def _resolve(
        self,
        *,
        python_requirements: list[str],
        npm_requirements: list[str],
        timeout_seconds: int | None,
        on_progress: DependencyProgress | None = None,
        cancel_event: threading.Event | None = None,
    ) -> DependencyPoolResolution:
        """Resolve Python and npm dependencies into the local shared pool."""
        self.root.mkdir(parents=True, exist_ok=True)

        try:
            normalized_python_requirements = normalize_python_requirements(python_requirements)
        except PythonRequirementError as exc:
            raise DependencyPoolError("unsupported", str(exc)) from exc

        # Local profile request.
        profile_request = {
            "runtime_compatibility": self._native_runtime_compatibility(),
            "python_requirements": normalized_python_requirements,
            "npm_requirements": _normalized_values(npm_requirements),
        }

        profile_key = _fingerprint(profile_request)

        _notify(on_progress, "waiting_for_dependency_profile", profile_key=profile_key)
        with self._profile_lock(profile_key):
            _notify(on_progress, "checking_dependency_profile", profile_key=profile_key)
            existing = self._read_profile(profile_key)
            if existing is not None and self.references_available(existing.to_lock_payload()):
                _notify(on_progress, "dependency_profile_cache_hit", profile_key=profile_key)
                return DependencyPoolResolution(
                    python_entries=existing.python_entries,
                    system_entries=existing.system_entries,
                    npm_profile=existing.npm_profile,
                    profile_key=profile_key,
                    cache_status="profile_hit",
                )

            # Resolve Python dependencies using local venv
            python_entries = self._resolve_python_native(
                requirements=normalized_python_requirements,
                timeout_seconds=timeout_seconds,
                on_progress=on_progress,
                cancel_event=cancel_event,
            )

            system_entries: list[dict[str, str]] = []

            # NPM resolution using local npm (if available)
            npm_profile = self._resolve_npm_native(
                requirements=_normalized_values(npm_requirements),
                timeout_seconds=timeout_seconds,
                on_progress=on_progress,
                cancel_event=cancel_event,
            )

            resolution = DependencyPoolResolution(
                python_entries=python_entries,
                system_entries=system_entries,
                npm_profile=npm_profile,
                profile_key=profile_key,
                cache_status="resolved",
            )

            with self._exclusive_lock():
                self._write_profile(profile_key, resolution, request=profile_request)

            _notify(
                on_progress,
                "dependency_profile_stored",
                profile_key=profile_key,
                python_artifact_count=len(python_entries),
                npm_profile_ready=npm_profile is not None,
            )
            return resolution

    def _native_runtime_compatibility(self) -> dict[str, str]:
        """Get runtime compatibility info from current Python environment."""
        # Try to read OS info
        os_release: dict[str, str] = {}
        os_release_path = Path("/etc/os-release")
        if os_release_path.is_file():
            try:
                for line in os_release_path.read_text(encoding="utf-8").splitlines():
                    if "=" in line:
                        key, value = line.split("=", 1)
                        os_release[key] = value.strip('"')
            except Exception:
                pass

        return {
            "architecture": platform.machine().lower(),
            "implementation": platform.python_implementation().lower(),
            "python_version": platform.python_version(),
            "python_cache_tag": str(sys.implementation.cache_tag or ""),
            "python_platform": sysconfig.get_platform(),
            "libc": ":".join(platform.libc_ver()),
            "os_id": os_release.get("ID", "").strip('"'),
            "os_version_id": os_release.get("VERSION_ID", "").strip('"'),
        }

    def _resolve_python_native(
        self,
        *,
        requirements: list[str],
        timeout_seconds: int | None,
        on_progress: DependencyProgress | None,
        cancel_event: threading.Event | None,
    ) -> list[dict[str, str]]:
        """Build Python wheels using a local virtual environment."""
        if not requirements:
            return []

        try:
            requirements = normalize_python_requirements(requirements)
        except PythonRequirementError as exc:
            raise DependencyPoolError("unsupported", str(exc)) from exc

        pip_cache = self.root / "python" / "download_cache"
        pip_cache.mkdir(parents=True, exist_ok=True)

        with self._staging_directory() as staging:
            wheel_output = staging / "wheels"
            wheel_output.mkdir()
            wheelhouse = staging / "wheelhouse"
            wheelhouse.mkdir()

            # Materialize existing wheels as find-links source
            self._materialize_python_wheelhouse(wheelhouse)

            # Create temporary venv for isolation
            venv_dir = staging / "venv"
            _notify(on_progress, "creating_python_build_environment")
            self._create_venv(
                venv_dir,
                timeout_seconds=timeout_seconds,
                on_progress=on_progress,
                cancel_event=cancel_event,
            )

            # Use venv pip to build wheels
            venv_pip = venv_dir / "bin" / "pip"
            if not venv_pip.exists():
                # Windows path
                venv_pip = venv_dir / "Scripts" / "pip.exe"

            command = [
                str(venv_pip),
                "wheel",
                "--disable-pip-version-check",
                "--prefer-binary",
                "--find-links",
                str(wheelhouse),
                "--wheel-dir",
                str(wheel_output),
                "--cache-dir",
                str(pip_cache),
                *requirements,
            ]

            _notify(
                on_progress,
                "building_python_wheels",
                requirement_count=len(requirements),
            )
            try:
                completed = run_observed_process(
                    command,
                    inactivity_timeout_seconds=timeout_seconds,
                    cancel_event=cancel_event,
                    on_output=_output_notifier(on_progress, stage="building_python_wheels"),
                )
            except ObservedProcessCancelled as exc:
                raise DependencyPoolError("cancelled", "Python wheel build was cancelled") from exc
            except ObservedProcessInactivityTimeout as exc:
                raise DependencyPoolError(
                    "build_failed",
                    f"Python wheel build produced no observable progress for {timeout_seconds}s",
                ) from exc
            except subprocess.TimeoutExpired as exc:
                raise DependencyPoolError(
                    "build_failed",
                    f"Python wheel build timed out after {timeout_seconds}s",
                ) from exc

            if completed.returncode != 0:
                detail = (
                    completed.stderr or completed.stdout or "wheel build failed"
                ).strip()
                raise DependencyPoolError("build_failed", f"wheel build failed: {detail[-4000:]}")

            # Collect wheels
            wheels = sorted(
                path for path in wheel_output.iterdir() if path.is_file() and path.suffix == ".whl"
            )
            unsupported = sorted(
                path.name
                for path in wheel_output.iterdir()
                if path.is_file() and path.suffix != ".whl"
            )

            if unsupported:
                raise DependencyPoolError(
                    "build_failed",
                    "Python dependency build returned non-wheel artifacts: " + ", ".join(unsupported),
                )

            if not wheels:
                raise DependencyPoolError(
                    "build_failed", "Python dependency resolution returned no wheel artifacts"
                )

            _notify(on_progress, "storing_python_wheels", wheel_count=len(wheels))
            return [self._store_wheel(wheel) for wheel in wheels]

    def _resolve_npm_native(
        self,
        *,
        requirements: list[str],
        timeout_seconds: int | None,
        on_progress: DependencyProgress | None,
        cancel_event: threading.Event | None,
    ) -> dict[str, str] | None:
        """Resolve npm dependencies using the local npm executable."""
        if not requirements:
            return None

        from .pool import _assert_installable_requirements
        _assert_installable_requirements(requirements, ecosystem="npm")

        # Check if npm is available
        import shutil as sh
        npm = sh.which("npm")
        if not npm:
            raise DependencyPoolError(
                "build_failed",
                "npm is not available on this system. Install Node.js to use npm dependencies.",
            )

        npm_root = self.root / "npm"
        cache_root = npm_root / "cache"
        cache_root.mkdir(parents=True, exist_ok=True)

        with self._staging_directory() as staging:
            project = staging / "project"
            project.mkdir()

            import json
            (project / "package.json").write_text(
                json.dumps({"private": True}, indent=2) + "\n",
                encoding="utf-8",
            )

            command = [
                npm,
                "install",
                "--omit=dev",
                "--ignore-scripts",
                "--cache",
                str(cache_root),
                "--prefix",
                str(project),
                *requirements,
            ]

            _notify(
                on_progress,
                "installing_npm_dependencies",
                requirement_count=len(requirements),
            )
            try:
                completed = run_observed_process(
                    command,
                    inactivity_timeout_seconds=timeout_seconds,
                    cancel_event=cancel_event,
                    on_output=_output_notifier(on_progress, stage="installing_npm_dependencies"),
                )
            except ObservedProcessCancelled as exc:
                raise DependencyPoolError("cancelled", "npm dependency installation was cancelled") from exc
            except ObservedProcessInactivityTimeout as exc:
                raise DependencyPoolError(
                    "build_failed",
                    f"npm install produced no observable progress for {timeout_seconds}s",
                ) from exc
            except subprocess.TimeoutExpired as exc:
                raise DependencyPoolError(
                    "build_failed", f"npm install timed out after {timeout_seconds}s"
                ) from exc

            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or "npm install failed").strip()
                raise DependencyPoolError("build_failed", f"npm install failed: {detail[-4000:]}")

            lock_path = project / "package-lock.json"
            node_modules = project / "node_modules"

            if not lock_path.is_file() or not node_modules.is_dir():
                raise DependencyPoolError(
                    "build_failed",
                    "npm dependency resolution did not produce a package lock and node_modules",
                )

            from pathlib import PurePosixPath
            profile_hash = _sha256_file(lock_path)
            relative = PurePosixPath("npm") / "profiles" / profile_hash
            target = self.root / relative

            with self._exclusive_lock():
                if not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    import shutil as sh
                    sh.move(str(project), str(target))

            return {"path": relative.as_posix(), "sha256": profile_hash}

    def _create_venv(
        self,
        venv_dir: Path,
        *,
        timeout_seconds: int | None,
        on_progress: DependencyProgress | None,
        cancel_event: threading.Event | None,
    ) -> None:
        """Create a temporary virtual environment for isolated pip operations."""
        command = [sys.executable, "-m", "venv", str(venv_dir)]

        try:
            completed = run_observed_process(
                command,
                inactivity_timeout_seconds=timeout_seconds,
                cancel_event=cancel_event,
                on_output=_output_notifier(
                    on_progress,
                    stage="creating_python_build_environment",
                ),
            )
        except ObservedProcessCancelled as exc:
            raise DependencyPoolError("cancelled", "venv creation was cancelled") from exc
        except ObservedProcessInactivityTimeout as exc:
            raise DependencyPoolError(
                "build_failed",
                f"venv creation produced no observable progress for {timeout_seconds}s",
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise DependencyPoolError(
                "build_failed", f"venv creation timed out after {timeout_seconds}s"
            ) from exc

        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "venv creation failed").strip()
            raise DependencyPoolError("build_failed", f"venv creation failed: {detail[-4000:]}")


def _notify(
    callback: DependencyProgress | None,
    stage: str,
    **detail: Any,
) -> None:
    if callback is not None:
        callback(stage, detail)


def _output_notifier(
    callback: DependencyProgress | None,
    *,
    stage: str,
) -> Callable[[str, str], None] | None:
    if callback is None:
        return None

    def notify_output(stream: str, line: str) -> None:
        message = line.strip()
        if message:
            callback(
                "dependency_process_output",
                {
                    "stage": stage,
                    "stream": stream,
                    "message": message,
                },
            )

    return notify_output


def _fingerprint(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
