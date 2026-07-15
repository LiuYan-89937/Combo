from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile
from typing import Any, Iterator
from uuid import uuid4
import zipfile

from packaging.utils import InvalidWheelFilename, canonicalize_name, parse_wheel_filename

from agent_factory.paths import factory_artifact_path

from .python_requirements import PythonRequirementError, normalize_python_requirements
from .versions import DEPENDENCY_POOL_VERSION


class DependencyPoolError(RuntimeError):
    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True, slots=True)
class DependencyPoolResolution:
    python_entries: list[dict[str, str]]
    system_entries: list[dict[str, str]]
    npm_profile: dict[str, str] | None

    def to_lock_payload(self) -> dict[str, Any]:
        return {
            "version": DEPENDENCY_POOL_VERSION,
            "python_entries": self.python_entries,
            "system_entries": self.system_entries,
            "npm_profile": self.npm_profile,
        }


class DependencyPool:
    """Content-addressed dependency artifacts shared by all AgentPackages."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or factory_artifact_path("dependency_pool")).resolve()

    def resolve(
        self,
        *,
        docker: str,
        base_image: str,
        architecture: str,
        python_requirements: list[str],
        system_packages: list[str],
        npm_requirements: list[str],
        timeout_seconds: int | None,
    ) -> DependencyPoolResolution:
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            normalized_python_requirements = normalize_python_requirements(python_requirements)
        except PythonRequirementError as exc:
            raise DependencyPoolError("unsupported", str(exc)) from exc
        profile_key = _fingerprint(
            {
                "base_image": base_image,
                "architecture": architecture,
                "python_requirements": normalized_python_requirements,
                "system_packages": _normalized_values(system_packages),
                "npm_requirements": _normalized_values(npm_requirements),
            }
        )
        with self._profile_lock(profile_key):
            existing = self._read_profile(profile_key)
            if existing is not None and self.references_available(existing.to_lock_payload()):
                return existing
            python_entries = self._resolve_python(
                docker=docker,
                base_image=base_image,
                requirements=normalized_python_requirements,
                timeout_seconds=timeout_seconds,
            )
            system_entries = self._resolve_system(
                docker=docker,
                base_image=base_image,
                packages=_normalized_values(system_packages),
                timeout_seconds=timeout_seconds,
            )
            npm_profile = self._resolve_npm(
                docker=docker,
                base_image=base_image,
                requirements=_normalized_values(npm_requirements),
                timeout_seconds=timeout_seconds,
            )
            resolution = DependencyPoolResolution(
                python_entries=python_entries,
                system_entries=system_entries,
                npm_profile=npm_profile,
            )
            with self._exclusive_lock():
                self._write_profile(profile_key, resolution)
            return resolution

    def references_available(self, payload: object) -> bool:
        if not isinstance(payload, dict) or payload.get("version") != DEPENDENCY_POOL_VERSION:
            return False
        for key in ("python_entries", "system_entries"):
            entries = payload.get(key)
            if not isinstance(entries, list):
                return False
            for entry in entries:
                if not isinstance(entry, dict) or not self._entry_exists(entry.get("path")):
                    return False
                if key == "python_entries" and not self._entry_exists(entry.get("artifact_path")):
                    return False
        npm_profile = payload.get("npm_profile")
        return npm_profile is None or (isinstance(npm_profile, dict) and self._entry_exists(npm_profile.get("path")))

    def _resolve_python(
        self,
        *,
        docker: str,
        base_image: str,
        requirements: list[str],
        timeout_seconds: int | None,
    ) -> list[dict[str, str]]:
        if not requirements:
            return []
        try:
            requirements = normalize_python_requirements(requirements)
        except PythonRequirementError as exc:
            raise DependencyPoolError("unsupported", str(exc)) from exc
        download_cache = self.root / "python" / "download_cache"
        download_cache.mkdir(parents=True, exist_ok=True)
        with self._staging_directory() as staging:
            downloads = staging / "downloads"
            downloads.mkdir()
            wheelhouse = staging / "wheelhouse"
            wheelhouse.mkdir()
            self._materialize_python_wheelhouse(wheelhouse)
            self._run(
                [
                    docker,
                    "run",
                    "--rm",
                    "--network",
                    "host",
                    "-v",
                    f"{staging}:/dependency_staging:rw",
                    "-v",
                    f"{download_cache}:/root/.cache/pip:rw",
                    base_image,
                    "python",
                    "-m",
                    "pip",
                    "download",
                    "--disable-pip-version-check",
                    "--only-binary=:all:",
                    "--find-links",
                    "/dependency_staging/wheelhouse",
                    "--dest",
                    "/dependency_staging/downloads",
                    *requirements,
                ],
                timeout_seconds=timeout_seconds,
                action="download Python dependency artifacts",
            )
            wheels = sorted(path for path in downloads.iterdir() if path.is_file() and path.suffix == ".whl")
            unsupported = sorted(path.name for path in downloads.iterdir() if path.is_file() and path.suffix != ".whl")
            if unsupported:
                raise DependencyPoolError(
                    "unsupported",
                    "Python dependency pool only accepts binary wheels; unsupported artifacts: " + ", ".join(unsupported),
                )
            if not wheels:
                raise DependencyPoolError("build_failed", "Python dependency resolution returned no wheel artifacts")
            return [self._store_wheel(wheel) for wheel in wheels]

    def _resolve_system(
        self,
        *,
        docker: str,
        base_image: str,
        packages: list[str],
        timeout_seconds: int | None,
    ) -> list[dict[str, str]]:
        if not packages:
            return []
        _assert_installable_requirements(packages, ecosystem="system")
        with self._cache_lock("system"):
            return self._resolve_system_locked(
                docker=docker,
                base_image=base_image,
                packages=packages,
                timeout_seconds=timeout_seconds,
            )

    def _resolve_system_locked(
        self,
        *,
        docker: str,
        base_image: str,
        packages: list[str],
        timeout_seconds: int | None,
    ) -> list[dict[str, str]]:
        script = (
            "set -eu\n"
            "mkdir -p /var/cache/apt/archives/partial\n"
            "apt-get update\n"
            "apt-get install --download-only -y --no-install-recommends \"$@\"\n"
            "find /var/cache/apt/archives -maxdepth 1 -type f -name '*.deb' -exec cp {} /dependency_staging/ \\;\n"
        )
        archive_cache = self.root / "system" / "archive_cache"
        archive_cache.mkdir(parents=True, exist_ok=True)
        with self._staging_directory() as staging:
            self._run(
                [
                    docker,
                    "run",
                    "--rm",
                    "--network",
                    "host",
                    "-v",
                    f"{staging}:/dependency_staging:rw",
                    "-v",
                    f"{archive_cache}:/var/cache/apt/archives:rw",
                    base_image,
                    "bash",
                    "-c",
                    script,
                    "dependency-pool",
                    *packages,
                ],
                timeout_seconds=timeout_seconds,
                action="download system dependency artifacts",
            )
            archives = sorted(path for path in staging.iterdir() if path.is_file() and path.suffix == ".deb")
            if not archives:
                raise DependencyPoolError("build_failed", "system dependency resolution returned no Debian package artifacts")
            return [self._store_file(archive, directory="system/debs") for archive in archives]

    def _resolve_npm(
        self,
        *,
        docker: str,
        base_image: str,
        requirements: list[str],
        timeout_seconds: int | None,
    ) -> dict[str, str] | None:
        if not requirements:
            return None
        _assert_installable_requirements(requirements, ecosystem="npm")
        npm_root = self.root / "npm"
        cache_root = npm_root / "cache"
        cache_root.mkdir(parents=True, exist_ok=True)
        with self._staging_directory() as staging:
            project = staging / "project"
            project.mkdir()
            (project / "package.json").write_text(
                json.dumps({"private": True}, indent=2) + "\n",
                encoding="utf-8",
            )
            self._run(
                [
                    docker,
                    "run",
                    "--rm",
                    "--network",
                    "host",
                    "-v",
                    f"{staging}:/dependency_staging:rw",
                    "-v",
                    f"{cache_root}:/dependency_pool/npm/cache:rw",
                    base_image,
                    "npm",
                    "install",
                    "--omit=dev",
                    "--ignore-scripts",
                    "--cache",
                    "/dependency_pool/npm/cache",
                    "--prefix",
                    "/dependency_staging/project",
                    *requirements,
                ],
                timeout_seconds=timeout_seconds,
                action="resolve npm dependency artifacts",
            )
            lock_path = project / "package-lock.json"
            node_modules = project / "node_modules"
            if not lock_path.is_file() or not node_modules.is_dir():
                raise DependencyPoolError("build_failed", "npm dependency resolution did not produce a package lock and node_modules")
            profile_hash = _sha256_file(lock_path)
            relative = PurePosixPath("npm") / "profiles" / profile_hash
            target = self.root / relative
            with self._exclusive_lock():
                if not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    project.replace(target)
            return {"path": relative.as_posix(), "sha256": profile_hash}

    def _store_wheel(self, wheel: Path) -> dict[str, str]:
        with self._exclusive_lock():
            return self._store_wheel_locked(wheel)

    def _store_wheel_locked(self, wheel: Path) -> dict[str, str]:
        digest = _sha256_file(wheel)
        wheel_metadata = _wheel_metadata(wheel.name)
        relative = PurePosixPath("python") / "wheels" / digest
        target = self.root / relative
        artifact_relative = PurePosixPath("python") / "artifacts" / digest / wheel.name
        artifact = self.root / artifact_relative
        if not artifact.is_file():
            artifact.parent.mkdir(parents=True, exist_ok=True)
            temporary_artifact = artifact.with_name(f".{artifact.name}.{uuid4().hex}.tmp")
            shutil.copy2(wheel, temporary_artifact)
            temporary_artifact.replace(artifact)
        site_packages = target / "site-packages"
        if not site_packages.is_dir():
            temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
            temporary.mkdir(parents=True, exist_ok=False)
            try:
                extracted = temporary / "site-packages"
                extracted.mkdir()
                _safe_extract_wheel(wheel, extracted)
                metadata = {
                    **wheel_metadata,
                    "filename": wheel.name,
                    "sha256": digest,
                    "artifact_path": artifact_relative.as_posix(),
                }
                (temporary / "metadata.json").write_text(
                    json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    shutil.rmtree(temporary)
                else:
                    temporary.replace(target)
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)
        index = self._read_python_artifact_index()
        index["artifacts"][digest] = {
            **wheel_metadata,
            "filename": wheel.name,
            "sha256": digest,
            "artifact_path": artifact_relative.as_posix(),
        }
        distributions = index["distributions"]
        versions = distributions.setdefault(wheel_metadata["name"], {})
        digests = versions.setdefault(wheel_metadata["version"], [])
        if digest not in digests:
            digests.append(digest)
            digests.sort()
        self._write_python_artifact_index(index)
        return {
            "path": relative.as_posix(),
            "sha256": digest,
            "filename": wheel.name,
            "artifact_path": artifact_relative.as_posix(),
            **wheel_metadata,
        }

    def _store_file(self, source: Path, *, directory: str) -> dict[str, str]:
        with self._exclusive_lock():
            digest = _sha256_file(source)
            suffix = source.suffix
            relative = PurePosixPath(directory) / f"{digest}{suffix}"
            target = self.root / relative
            if not target.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
                shutil.copy2(source, temporary)
                temporary.replace(target)
            return {"path": relative.as_posix(), "sha256": digest, "filename": source.name}

    def _materialize_python_wheelhouse(self, destination: Path) -> None:
        index = self._read_python_artifact_index()
        for record in index["artifacts"].values():
            filename = record.get("filename")
            artifact_path = record.get("artifact_path")
            if not isinstance(filename, str) or Path(filename).name != filename:
                continue
            if not isinstance(artifact_path, str):
                continue
            try:
                source = self.root / _safe_relative_path(artifact_path)
            except ValueError:
                continue
            if not source.is_file():
                continue
            target = destination / filename
            if target.exists():
                if _sha256_file(target) != record.get("sha256"):
                    raise DependencyPoolError("pool_conflict", f"conflicting cached wheel filename: {filename}")
                continue
            try:
                target.hardlink_to(source)
            except OSError:
                shutil.copy2(source, target)

    def _read_python_artifact_index(self) -> dict[str, Any]:
        path = self.root / "python" / "artifact_index.json"
        value: object = None
        if path.is_file():
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                value = None
        artifacts: dict[str, dict[str, Any]] = {}
        if (
            isinstance(value, dict)
            and value.get("version") == "python_artifact_index.v1"
            and isinstance(value.get("artifacts"), dict)
        ):
            artifacts = {
                str(key): dict(record)
                for key, record in value["artifacts"].items()
                if isinstance(record, dict)
            }
        artifacts.update(self._python_artifacts_from_storage())
        return {
            "version": "python_artifact_index.v1",
            "artifacts": artifacts,
            "distributions": _distribution_index(artifacts),
        }

    def _python_artifacts_from_storage(self) -> dict[str, dict[str, str]]:
        root = self.root / "python" / "artifacts"
        if not root.is_dir():
            return {}
        artifacts: dict[str, dict[str, str]] = {}
        for digest_directory in root.iterdir():
            digest = digest_directory.name
            if (
                not digest_directory.is_dir()
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                continue
            for wheel in digest_directory.iterdir():
                if not wheel.is_file() or wheel.suffix != ".whl":
                    continue
                try:
                    metadata = _wheel_metadata(wheel.name)
                except DependencyPoolError:
                    continue
                artifact_path = PurePosixPath("python") / "artifacts" / digest / wheel.name
                artifacts[digest] = {
                    **metadata,
                    "filename": wheel.name,
                    "sha256": digest,
                    "artifact_path": artifact_path.as_posix(),
                }
        return artifacts

    def _write_python_artifact_index(self, index: dict[str, Any]) -> None:
        path = self.root / "python" / "artifact_index.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        temporary.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)

    def _entry_exists(self, value: object) -> bool:
        if not isinstance(value, str) or not value:
            return False
        try:
            relative = _safe_relative_path(value)
        except ValueError:
            return False
        return (self.root / relative).exists()

    def _read_profile(self, key: str) -> DependencyPoolResolution | None:
        path = self.root / "profiles" / f"{key}.json"
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if value.get("version") != DEPENDENCY_POOL_VERSION:
                return None
            python_entries = value.get("python_entries")
            system_entries = value.get("system_entries")
            npm_profile = value.get("npm_profile")
        except (OSError, json.JSONDecodeError, AttributeError):
            return None
        if not isinstance(python_entries, list) or not isinstance(system_entries, list):
            return None
        if npm_profile is not None and not isinstance(npm_profile, dict):
            return None
        if not all(isinstance(item, dict) for item in [*python_entries, *system_entries]):
            return None
        return DependencyPoolResolution(
            python_entries=[dict(item) for item in python_entries],
            system_entries=[dict(item) for item in system_entries],
            npm_profile=dict(npm_profile) if isinstance(npm_profile, dict) else None,
        )

    def _write_profile(self, key: str, resolution: DependencyPoolResolution) -> None:
        path = self.root / "profiles" / f"{key}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(resolution.to_lock_payload(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)

    @contextmanager
    def _exclusive_lock(self) -> Iterator[None]:
        lock_path = self.root / ".pool.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @contextmanager
    def _profile_lock(self, profile_key: str) -> Iterator[None]:
        lock_path = self.root / "profiles" / ".locks" / f"{profile_key}.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @contextmanager
    def _cache_lock(self, ecosystem: str) -> Iterator[None]:
        lock_path = self.root / ".cache_locks" / f"{ecosystem}.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @contextmanager
    def _staging_directory(self) -> Iterator[Path]:
        staging_root = self.root / "staging"
        staging_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="resolve-", dir=staging_root) as value:
            yield Path(value)

    def _run(self, command: list[str], *, timeout_seconds: int | None, action: str) -> None:
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise DependencyPoolError("build_failed", f"{action} timed out after {timeout_seconds}s") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or f"{action} failed").strip()
            raise DependencyPoolError("build_failed", f"{action} failed: {detail[-4000:]}")


def dependency_pool_path() -> Path:
    return factory_artifact_path("dependency_pool")


def _normalized_values(values: list[str]) -> list[str]:
    return sorted({value.strip() for value in values if value and value.strip()})


def _assert_installable_requirements(values: list[str], *, ecosystem: str) -> None:
    invalid = [value for value in values if value.startswith("-")]
    if invalid:
        raise DependencyPoolError(
            "unsupported",
            f"{ecosystem} dependency declarations must be package requirements, not package-manager options: {', '.join(invalid)}",
        )


def _wheel_metadata(filename: str) -> dict[str, str]:
    try:
        name, version, build, tags = parse_wheel_filename(filename)
    except InvalidWheelFilename as exc:
        raise DependencyPoolError("unsupported", f"invalid Python wheel filename {filename!r}: {exc}") from exc
    return {
        "name": canonicalize_name(name),
        "version": str(version),
        "build": ".".join(str(part) for part in build),
        "tags": ",".join(sorted(str(tag) for tag in tags)),
    }


def _empty_python_artifact_index() -> dict[str, Any]:
    return {
        "version": "python_artifact_index.v1",
        "artifacts": {},
        "distributions": {},
    }


def _distribution_index(artifacts: dict[str, dict[str, Any]]) -> dict[str, dict[str, list[str]]]:
    result: dict[str, dict[str, list[str]]] = {}
    for digest, record in artifacts.items():
        name = record.get("name")
        version = record.get("version")
        if not isinstance(name, str) or not isinstance(version, str):
            continue
        result.setdefault(name, {}).setdefault(version, []).append(digest)
    for versions in result.values():
        for digests in versions.values():
            digests.sort()
    return result


def _safe_extract_wheel(wheel: Path, destination: Path) -> None:
    with zipfile.ZipFile(wheel) as archive:
        for member in archive.infolist():
            relative = _safe_relative_path(member.filename)
            target = destination / relative
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)


def _safe_relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"unsafe dependency pool path: {value}")
    return path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprint(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
