from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from langchain_core.tools import tool


@tool("shell_run", parse_docstring=True)
def run_command(
    command: list[str],
    cwd: str | None = None,
    timeout_seconds: int = 60,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run a command without shell expansion and return stdout, stderr, and exit code.

    Use this for safe command execution when arguments can be passed as a list.

    Args:
        command: Command and arguments as a list, for example ["python", "--version"].
        cwd: Optional working directory for the command.
        timeout_seconds: Maximum runtime before the command is stopped.
        env: Optional environment variables to add or override.
    """

    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=str(Path(cwd).expanduser()) if cwd else None,
            env={**os.environ, **(env or {})},
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        status = "completed"
        exit_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as exc:
        status = "timeout"
        exit_code = None
        stdout = _safe_text(exc.stdout)
        stderr = _safe_text(exc.stderr)
    duration_ms = int((time.monotonic() - started) * 1000)
    return {
        "command": command,
        "cwd": cwd,
        "status": status,
        "exit_code": exit_code,
        "duration_ms": duration_ms,
        "stdout": stdout[:20000],
        "stderr": stderr[:20000],
        "stdout_truncated": len(stdout) > 20000,
        "stderr_truncated": len(stderr) > 20000,
    }


@tool("shell_run_text", parse_docstring=True)
def run_shell_text(
    command: str,
    cwd: str | None = None,
    timeout_seconds: int = 60,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run a shell command string when shell syntax is required.

    Use this only when pipes, redirects, shell operators, or compound shell syntax are necessary.

    Args:
        command: Shell command string to execute.
        cwd: Optional working directory for the command.
        timeout_seconds: Maximum runtime before the command is stopped.
        env: Optional environment variables to add or override.
    """

    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=str(Path(cwd).expanduser()) if cwd else None,
            env={**os.environ, **(env or {})},
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
            shell=True,
        )
        status = "completed"
        exit_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as exc:
        status = "timeout"
        exit_code = None
        stdout = _safe_text(exc.stdout)
        stderr = _safe_text(exc.stderr)
    duration_ms = int((time.monotonic() - started) * 1000)
    return {
        "command": command,
        "cwd": cwd,
        "status": status,
        "exit_code": exit_code,
        "duration_ms": duration_ms,
        "stdout": stdout[:20000],
        "stderr": stderr[:20000],
        "stdout_truncated": len(stdout) > 20000,
        "stderr_truncated": len(stderr) > 20000,
    }


@tool("shell_which", parse_docstring=True)
def which_command(command: str) -> dict[str, Any]:
    """Resolve an executable command on PATH.

    Use this to check whether a command is available before trying to run it.

    Args:
        command: Executable name to resolve.
    """

    resolved = shutil.which(command)
    return {"command": command, "found": resolved is not None, "path": resolved}


@tool("shell_cwd", parse_docstring=True)
def current_working_directory() -> dict[str, str]:
    """Return the current working directory for the running process."""

    return {"cwd": os.getcwd()}


@tool("shell_env", parse_docstring=True)
def read_environment(names: list[str], include_values: bool = False) -> dict[str, Any]:
    """Check environment variables without revealing values unless explicitly requested.

    Use this to verify configuration presence without leaking secrets.

    Args:
        names: Environment variable names to inspect.
        include_values: Include raw values when explicitly needed.
    """

    values: dict[str, Any] = {}
    for name in names:
        exists = name in os.environ
        item: dict[str, Any] = {"exists": exists}
        if include_values and exists:
            item["value"] = os.environ[name]
        values[name] = item
    return {"variables": values}


def _safe_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value


SHELL_TOOLS = [
    run_command,
    run_shell_text,
    which_command,
    current_working_directory,
    read_environment,
]
