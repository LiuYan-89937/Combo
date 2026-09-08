#!/usr/bin/env python3
"""Install the bundled runtime dependencies exactly as recorded in uv.lock."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile

BUNDLE_MANIFEST_NAME = ".combo-python-bundle.json"
BUNDLE_SCHEMA_VERSION = 1
REUSABLE_CHECK_FAILED = 3


def _required_executable(name: str) -> str:
    executable = shutil.which(name)
    if executable is None:
        raise RuntimeError(f"required build command is unavailable: {name}")
    return executable


def _runtime_root(python_runtime: Path) -> Path:
    if python_runtime.name.lower() == "python.exe":
        return python_runtime.parent
    if python_runtime.parent.name == "bin":
        return python_runtime.parent.parent
    raise RuntimeError(f"unsupported bundled Python layout: {python_runtime}")


def _bundle_manifest(
    *, project_root: Path, runtime_id: str
) -> dict[str, object]:
    lockfile = project_root / "uv.lock"
    if not lockfile.is_file():
        raise RuntimeError(f"Python lockfile is unavailable: {lockfile}")
    return {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "lock_sha256": hashlib.sha256(lockfile.read_bytes()).hexdigest(),
        "runtime_id": runtime_id,
        "platform_system": platform.system(),
        "platform_machine": platform.machine(),
        "extras": ["web"],
    }


def _playwright_installation_is_complete(runtime_root: Path) -> bool:
    manifests = list(
        runtime_root.glob("lib/python*/site-packages/playwright/driver/package/browsers.json")
    )
    manifests.extend(
        runtime_root.glob("Lib/site-packages/playwright/driver/package/browsers.json")
    )
    if len(manifests) != 1:
        return False
    try:
        browsers = json.loads(manifests[0].read_text(encoding="utf-8"))["browsers"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return False
    expected = {
        f"{item['name'].replace('-', '_')}-{item['revision']}"
        for item in browsers
        if item.get("name") in {"chromium-headless-shell", "ffmpeg"}
        and item.get("revision") is not None
    }
    browser_directory = runtime_root / "playwright-browsers"
    return bool(expected) and all((browser_directory / name).is_dir() for name in expected)


def is_reusable_runtime(
    *, project_root: Path, python_runtime: Path, runtime_id: str
) -> bool:
    project_root = project_root.resolve()
    python_runtime = python_runtime.resolve()
    if not python_runtime.is_file():
        return False
    runtime_root = _runtime_root(python_runtime)
    manifest_path = runtime_root / BUNDLE_MANIFEST_NAME
    try:
        actual = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, json.JSONDecodeError):
        return False
    expected = _bundle_manifest(
        project_root=project_root,
        runtime_id=runtime_id,
    )
    return actual == expected and _playwright_installation_is_complete(runtime_root)


def install_locked_dependencies(
    *, project_root: Path, python_runtime: Path, runtime_id: str
) -> None:
    project_root = project_root.resolve()
    python_runtime = python_runtime.resolve()
    lockfile = project_root / "uv.lock"
    if not lockfile.is_file():
        raise RuntimeError(f"Python lockfile is unavailable: {lockfile}")
    if not python_runtime.is_file():
        raise RuntimeError(f"bundled Python executable is unavailable: {python_runtime}")

    uv = _required_executable("uv")
    with tempfile.TemporaryDirectory(prefix="combo-python-lock-") as temporary_directory:
        requirements = Path(temporary_directory) / "requirements.txt"
        subprocess.run(
            [
                uv,
                "export",
                "--locked",
                "--no-dev",
                "--extra",
                "web",
                "--no-emit-project",
                "--format",
                "requirements.txt",
                "--output-file",
                str(requirements),
            ],
            cwd=project_root,
            check=True,
        )
        subprocess.run(
            [
                str(python_runtime),
                "-m",
                "pip",
                "install",
                "--require-hashes",
                "--requirement",
                str(requirements),
            ],
            cwd=project_root,
            check=True,
        )

    runtime_root = _runtime_root(python_runtime)
    browser_directory = runtime_root / "playwright-browsers"
    browser_environment = {
        **os.environ,
        "PLAYWRIGHT_BROWSERS_PATH": str(browser_directory),
    }
    subprocess.run(
        [
            str(python_runtime),
            "-m",
            "playwright",
            "install",
            "--only-shell",
            "chromium",
        ],
        check=True,
        env=browser_environment,
    )
    manifest_path = runtime_root / BUNDLE_MANIFEST_NAME
    manifest_path.write_text(
        json.dumps(
            _bundle_manifest(
                project_root=project_root,
                runtime_id=runtime_id,
            ),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("check", "install"))
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--python-runtime", required=True, type=Path)
    parser.add_argument("--runtime-id", required=True)
    arguments = parser.parse_args()
    if arguments.action == "check":
        reusable = is_reusable_runtime(
            project_root=arguments.project_root,
            python_runtime=arguments.python_runtime,
            runtime_id=arguments.runtime_id,
        )
        raise SystemExit(0 if reusable else REUSABLE_CHECK_FAILED)
    install_locked_dependencies(
        project_root=arguments.project_root,
        python_runtime=arguments.python_runtime,
        runtime_id=arguments.runtime_id,
    )


if __name__ == "__main__":
    main()
