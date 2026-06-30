from __future__ import annotations

import importlib
import importlib.metadata
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from packaging.requirements import InvalidRequirement, Requirement

from agent_factory.runtime_contracts.schema import DependenciesContract


def load_dependencies_contract(package_root: Path) -> DependenciesContract:
    path = package_root / "contracts" / "dependencies.json"
    if not path.is_file():
        return DependenciesContract()
    return DependenciesContract.model_validate_json(path.read_text(encoding="utf-8"))


def ensure_dependencies(
    package_root: Path,
    artifacts_root: Path,
    *,
    runtime_root: Path | None = None,
) -> dict[str, Any]:
    started_at = time.monotonic()
    contract = load_dependencies_contract(package_root)
    config = contract.config
    package_digest = _file_digest(package_root / "agent_package.json")
    dependencies_digest = _file_digest(package_root / "contracts" / "dependencies.json")
    cache_paths = _dependency_cache_paths(runtime_root)
    _ensure_python_cache_on_path(cache_paths)
    runtime_environment = _runtime_environment()
    report = {
        "status": "skipped",
        "phase": "load_contract",
        "duration_ms": 0,
        "used_cache": False,
        "package_digest": package_digest,
        "dependencies_digest": dependencies_digest,
        "python_requirements": list(config.python_requirements),
        "system_packages": list(config.system_packages),
        "system_binaries": list(config.system_binaries),
        "runtime_environment": runtime_environment,
        "dependency_cache": _cache_report(cache_paths),
        "checks": [],
        "installs": [],
        "errors": [],
    }
    if not contract.enabled or config.install_mode == "none":
        report["phase"] = "skipped"
        report["duration_ms"] = _duration_ms(started_at)
        return _write_report(artifacts_root, report)
    marker_path = _dependency_marker_path(runtime_root)
    marker = _read_marker(marker_path)
    report["phase"] = "validate"
    parsed_python: list[Requirement] = []
    for requirement in config.python_requirements:
        if not requirement:
            continue
        try:
            parsed_python.append(Requirement(requirement))
        except InvalidRequirement as exc:
            report["errors"].append(
                {
                    "where": "dependency.python_requirements",
                    "message": f"invalid Python requirement: {requirement}",
                    "evidence": {"error": str(exc)},
                }
            )
    if report["errors"]:
        report["status"] = "failed"
        report["duration_ms"] = _duration_ms(started_at)
        _write_marker(
            marker_path,
            {
                "package_digest": package_digest,
                "dependencies_digest": dependencies_digest,
                "runtime_environment": runtime_environment,
                "status": report["status"],
            },
        )
        return _write_report(artifacts_root, report)
    check = _dependency_check(
        config=config,
        parsed_python=parsed_python,
        package_digest=package_digest,
        dependencies_digest=dependencies_digest,
        phase="dependency_check",
    )
    report["checks"].append(check)
    marker_matches = _marker_matches(
        marker,
        package_digest=package_digest,
        dependencies_digest=dependencies_digest,
        runtime_environment=runtime_environment,
    )
    if marker_matches and not _has_missing_dependencies(check):
        report["status"] = "complete"
        report["phase"] = "cache_hit"
        report["used_cache"] = True
        report["duration_ms"] = _duration_ms(started_at)
        report["checks"].append(
            {
                "phase": "cache",
                "status": "complete",
                "package_digest": package_digest,
                "dependencies_digest": dependencies_digest,
                "runtime_environment": runtime_environment,
            }
        )
        return _write_report(artifacts_root, report)
    if marker_matches:
        report["phase"] = "cache_stale"
        report["checks"].append(
            {
                "phase": "cache",
                "status": "stale",
                "reason": "cached dependency marker no longer matches current runtime availability",
                "missing": _missing_from_check(check),
                "package_digest": package_digest,
                "dependencies_digest": dependencies_digest,
                "runtime_environment": runtime_environment,
            }
        )
    missing_python = list(check["python_missing"])
    missing_system_packages = list(check["system_packages_missing"])
    if missing_system_packages:
        update = _run("system_update", _apt_command(cache_paths, "update"), timeout_seconds=120)
        report["installs"].append({"kind": "system_update", **update})
        if update["exit_code"] == 0:
            install = _run(
                "system_install",
                _apt_command(cache_paths, "install", "-y", *missing_system_packages),
                timeout_seconds=300,
            )
            report["installs"].append({"kind": "system_install", **install})
            if install["exit_code"] != 0:
                report["errors"].append({"where": "dependency.system_packages", "message": "system dependency installation failed"})
        else:
            report["errors"].append({"where": "dependency.system_packages", "message": "apt-get update failed"})
    if missing_python:
        install = _run("python_install", _pip_install_command(cache_paths, missing_python), timeout_seconds=300)
        report["installs"].append({"kind": "python_install", **install})
        _ensure_python_cache_on_path(cache_paths)
        importlib.invalidate_caches()
        if install["exit_code"] != 0:
            report["errors"].append({"where": "dependency.python_requirements", "message": "python dependency installation failed"})
    post_check = _dependency_check(
        config=config,
        parsed_python=parsed_python,
        package_digest=package_digest,
        dependencies_digest=dependencies_digest,
        phase="post_install_check",
    )
    report["checks"].append(post_check)
    if _has_missing_dependencies(post_check):
        report["errors"].append(
            {
                "where": "dependency.post_install",
                "message": "dependencies remain unavailable after initialization",
                "evidence": _missing_from_check(post_check),
            }
        )
    report["status"] = "failed" if report["errors"] else "complete"
    report["phase"] = report["status"]
    report["duration_ms"] = _duration_ms(started_at)
    _write_marker(
        marker_path,
        {
            "package_digest": package_digest,
            "dependencies_digest": dependencies_digest,
            "runtime_environment": runtime_environment,
            "status": report["status"],
        },
    )
    return _write_report(artifacts_root, report)


def _dependency_check(
    *,
    config: Any,
    parsed_python: list[Requirement],
    package_digest: str,
    dependencies_digest: str,
    phase: str,
) -> dict[str, Any]:
    missing_python = [
        str(requirement)
        for requirement in parsed_python
        if not _python_requirement_available(requirement)
    ]
    missing_system_packages = _missing_system_packages(config.system_packages)
    missing_system_binaries = [
        binary
        for binary in config.system_binaries
        if binary and shutil.which(binary) is None
    ]
    return {
        "phase": phase,
        "status": "missing" if missing_python or missing_system_packages or missing_system_binaries else "complete",
        "python_missing": missing_python,
        "system_packages_missing": missing_system_packages,
        "system_binaries_missing": missing_system_binaries,
        "package_digest": package_digest,
        "dependencies_digest": dependencies_digest,
    }


def _has_missing_dependencies(check: dict[str, Any]) -> bool:
    return any(
        bool(check.get(key))
        for key in ("python_missing", "system_packages_missing", "system_binaries_missing")
    )


def _missing_from_check(check: dict[str, Any]) -> dict[str, list[str]]:
    return {
        "python": [str(item) for item in check.get("python_missing") or []],
        "system_packages": [str(item) for item in check.get("system_packages_missing") or []],
        "system_binaries": [str(item) for item in check.get("system_binaries_missing") or []],
    }


def _marker_matches(
    marker: dict[str, Any],
    *,
    package_digest: str,
    dependencies_digest: str,
    runtime_environment: dict[str, str],
) -> bool:
    return (
        marker.get("package_digest") == package_digest
        and marker.get("dependencies_digest") == dependencies_digest
        and marker.get("runtime_environment") == runtime_environment
        and marker.get("status") == "complete"
    )


def _runtime_environment() -> dict[str, str]:
    return {
        "python_executable": sys.executable,
        "python_version": sys.version.split()[0],
        "sys_prefix": sys.prefix,
    }


def _dependency_cache_paths(runtime_root: Path | None) -> dict[str, Path]:
    if runtime_root is None:
        return {}
    root = runtime_root / "dependency_cache"
    return {
        "root": root,
        "python_site": root / "python_site",
        "pip_cache": root / "pip",
        "apt_archives": root / "apt" / "archives",
        "apt_lists": root / "apt" / "lists",
    }


def _ensure_python_cache_on_path(cache_paths: dict[str, Path]) -> None:
    python_site = cache_paths.get("python_site")
    if python_site is None:
        return
    python_site.mkdir(parents=True, exist_ok=True)
    site = str(python_site)
    if site not in sys.path:
        sys.path.insert(0, site)
    pythonpath = [item for item in os.environ.get("PYTHONPATH", "").split(os.pathsep) if item]
    if site not in pythonpath:
        os.environ["PYTHONPATH"] = os.pathsep.join([site, *pythonpath])


def _cache_report(cache_paths: dict[str, Path]) -> dict[str, str]:
    return {key: str(path) for key, path in cache_paths.items()}


def _pip_install_command(cache_paths: dict[str, Path], requirements: list[str]) -> list[str]:
    command = [sys.executable, "-m", "pip", "install", "--upgrade"]
    pip_cache = cache_paths.get("pip_cache")
    python_site = cache_paths.get("python_site")
    if pip_cache is not None:
        pip_cache.mkdir(parents=True, exist_ok=True)
        command.extend(["--cache-dir", str(pip_cache)])
    if python_site is not None:
        python_site.mkdir(parents=True, exist_ok=True)
        command.extend(["--target", str(python_site)])
    command.extend(requirements)
    return command


def _apt_command(cache_paths: dict[str, Path], *args: str) -> list[str]:
    command = ["apt-get"]
    apt_archives = cache_paths.get("apt_archives")
    apt_lists = cache_paths.get("apt_lists")
    if apt_archives is not None:
        (apt_archives / "partial").mkdir(parents=True, exist_ok=True)
        command.extend(["-o", f"Dir::Cache::archives={apt_archives}"])
    if apt_lists is not None:
        (apt_lists / "partial").mkdir(parents=True, exist_ok=True)
        command.extend(["-o", f"Dir::State::lists={apt_lists}"])
    command.extend(args)
    return command


def _python_requirement_available(requirement: Requirement) -> bool:
    if not requirement.name:
        return True
    try:
        installed = importlib.metadata.version(requirement.name)
    except importlib.metadata.PackageNotFoundError:
        return False
    if not requirement.specifier:
        return True
    return requirement.specifier.contains(installed, prereleases=True)


def _missing_system_packages(packages: list[str]) -> list[str]:
    requested = [package for package in packages if package]
    if not requested:
        return []
    if shutil.which("dpkg-query") is None:
        return requested
    missing: list[str] = []
    for package in requested:
        result = _run("system_package_check", ["dpkg-query", "-W", "-f=${Status}", package], timeout_seconds=30)
        if result["exit_code"] != 0 or "install ok installed" not in str(result.get("stdout") or ""):
            missing.append(package)
    return missing


def _run(phase: str, command: list[str], *, timeout_seconds: int) -> dict[str, Any]:
    started_at = time.monotonic()
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout_seconds, check=False)
    except subprocess.TimeoutExpired as exc:
        return {
            "phase": phase,
            "status": "timeout",
            "duration_ms": _duration_ms(started_at),
            "command": command,
            "exit_code": None,
            "stdout": _safe_text(exc.stdout),
            "stderr": _safe_text(exc.stderr),
            "timeout": True,
        }
    return {
        "phase": phase,
        "status": "complete" if completed.returncode == 0 else "failed",
        "duration_ms": _duration_ms(started_at),
        "command": command,
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "timeout": False,
    }


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return str(value)


def _write_report(artifacts_root: Path, report: dict[str, Any]) -> dict[str, Any]:
    artifacts_root.mkdir(parents=True, exist_ok=True)
    (artifacts_root / "dependency_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report


def _file_digest(path: Path) -> str:
    if not path.is_file():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _duration_ms(started_at: float) -> int:
    return int((time.monotonic() - started_at) * 1000)


def _dependency_marker_path(runtime_root: Path | None) -> Path | None:
    if runtime_root is None:
        return None
    return runtime_root / "dependency_init.json"


def _read_marker(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _write_marker(path: Path | None, payload: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
