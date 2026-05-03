from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Literal

from pydantic import ConfigDict, Field

from agent_factory.core.types import JsonDumpMixin
from agent_factory.factory_runtime.redaction import redact_secrets


class ShellCommandResult(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    status: Literal["completed", "failed", "rejected", "timeout"]
    command: list[str] = Field(default_factory=list)
    cwd: str | None = None
    return_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "completed" and self.return_code == 0


class ControlledShellRunner:
    """Small allowlisted subprocess wrapper for probes and future shell capabilities."""

    def __init__(
        self,
        *,
        allowed_commands: set[str] | None = None,
        timeout_seconds: int = 10,
        output_limit: int = 4000,
        env_allowlist: set[str] | None = None,
    ) -> None:
        self.allowed_commands = allowed_commands or {"sqlite3", "python", "python3"}
        self.timeout_seconds = timeout_seconds
        self.output_limit = output_limit
        self.env_allowlist = env_allowlist or {"PATH", "HOME", "LANG", "LC_ALL"}

    def run(self, command: list[str], *, cwd: str | Path | None = None) -> ShellCommandResult:
        if not command or not isinstance(command[0], str):
            return ShellCommandResult(status="rejected", command=command, error="command is empty")
        executable = Path(command[0]).name
        if executable not in self.allowed_commands:
            return ShellCommandResult(
                status="rejected",
                command=command,
                cwd=str(cwd) if cwd else None,
                error=f"command is not allowlisted: {executable}",
            )
        if any(_looks_like_shell_control_token(part) for part in command):
            return ShellCommandResult(
                status="rejected",
                command=command,
                cwd=str(cwd) if cwd else None,
                error="shell control tokens are not allowed",
            )
        try:
            completed = subprocess.run(
                command,
                cwd=str(cwd) if cwd else None,
                env={key: value for key, value in os.environ.items() if key in self.env_allowlist},
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            return ShellCommandResult(
                status="timeout",
                command=command,
                cwd=str(cwd) if cwd else None,
                stdout=_clean_output(error.stdout or "", self.output_limit),
                stderr=_clean_output(error.stderr or "", self.output_limit),
                error=f"command timed out after {self.timeout_seconds} seconds",
            )
        except OSError as error:
            return ShellCommandResult(
                status="failed",
                command=command,
                cwd=str(cwd) if cwd else None,
                error=str(error),
            )
        return ShellCommandResult(
            status="completed" if completed.returncode == 0 else "failed",
            command=command,
            cwd=str(cwd) if cwd else None,
            return_code=completed.returncode,
            stdout=_clean_output(completed.stdout, self.output_limit),
            stderr=_clean_output(completed.stderr, self.output_limit),
        )


def _looks_like_shell_control_token(value: str) -> bool:
    return any(token in value for token in ("&&", "||", ";", "|", "$(", "`", ">", "<"))


def _clean_output(value: str, limit: int) -> str:
    redacted = redact_secrets(value)
    if not isinstance(redacted, str):
        redacted = str(redacted)
    if len(redacted) <= limit:
        return redacted
    return redacted[:limit] + "...[truncated]"
