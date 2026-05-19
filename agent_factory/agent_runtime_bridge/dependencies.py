from __future__ import annotations

import importlib.metadata
import hashlib
import json
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
    if (
        marker.get("package_digest") == package_digest
        and marker.get("dependencies_digest") == dependencies_digest
        and marker.get("status") == "complete"
    ):
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
            }
        )
        return _write_report(artifacts_root, report)
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
                "status": report["status"],
            },
        )
        return _write_report(artifacts_root, report)
    missing_python = [str(requirement) for requirement in parsed_python if not _python_requirement_available(requirement)]
    missing_system_packages = _missing_system_packages(config.system_packages)
    missing_system_binaries = [
        binary
        for binary in config.system_binaries
        if binary and shutil.which(binary) is None
    ]
    report["checks"].append(
        {
            "phase": "dependency_check",
            "status": "complete",
            "python_missing": missing_python,
            "system_packages_missing": missing_system_packages,
            "system_binaries_missing": missing_system_binaries,
            "package_digest": package_digest,
            "dependencies_digest": dependencies_digest,
        }
    )
    if missing_system_packages:
        update = _run("system_update", ["apt-get", "update"], timeout_seconds=120)
        report["installs"].append({"kind": "system_update", **update})
        if update["exit_code"] == 0:
            install = _run("system_install", ["apt-get", "install", "-y", *missing_system_packages], timeout_seconds=300)
            report["installs"].append({"kind": "system_install", **install})
            if install["exit_code"] != 0:
                report["errors"].append({"where": "dependency.system_packages", "message": "system dependency installation failed"})
        else:
            report["errors"].append({"where": "dependency.system_packages", "message": "apt-get update failed"})
    if missing_system_binaries:
        report["errors"].append(
            {
                "where": "dependency.system_binaries",
                "message": "required system binaries are missing",
                "binaries": missing_system_binaries,
            }
        )
    if missing_python:
        install = _run("python_install", [sys.executable, "-m", "pip", "install", *missing_python], timeout_seconds=300)
        report["installs"].append({"kind": "python_install", **install})
        if install["exit_code"] != 0:
            report["errors"].append({"where": "dependency.python_requirements", "message": "python dependency installation failed"})
    report["status"] = "failed" if report["errors"] else "complete"
    report["phase"] = report["status"]
    report["duration_ms"] = _duration_ms(started_at)
    _write_marker(
        marker_path,
        {
            "package_digest": package_digest,
            "dependencies_digest": dependencies_digest,
            "status": report["status"],
        },
    )
    return _write_report(artifacts_root, report)


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
