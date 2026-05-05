from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path
from typing import Literal

from pydantic import ConfigDict, Field

from agent_factory.core.types import JsonDumpMixin
from agent_factory.factory_runtime.redaction import redact_secrets


class ShellCommandReview(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    review_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    required: bool = True
    approved: bool = False
    reviewer: str | None = None
    approval_id: str | None = None
    operation: Literal["file_write", "file_delete", "potential_file_write"]
    reason: str
    matched_command: str
    matched_argument: str | None = None


class ShellCommandResult(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    status: Literal["completed", "failed", "rejected", "timeout", "review_required"]
    command: list[str] = Field(default_factory=list)
    cwd: str | None = None
    return_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    error: str | None = None
    review: "ShellCommandReview | None" = None

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

    def run(
        self,
        command: list[str],
        *,
        cwd: str | Path | None = None,
        approved: bool = False,
        reviewer: str | None = None,
        approval_id: str | None = None,
    ) -> ShellCommandResult:
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
        review = _review_for_command(command)
        if review is not None and not approved:
            return ShellCommandResult(
                status="review_required",
                command=command,
                cwd=str(cwd) if cwd else None,
                error=review.reason,
                review=review,
            )
        if review is not None:
            review.approved = True
            review.reviewer = reviewer
            review.approval_id = approval_id
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
                review=review,
            )
        except OSError as error:
            return ShellCommandResult(
                status="failed",
                command=command,
                cwd=str(cwd) if cwd else None,
                error=str(error),
                review=review,
            )
        return ShellCommandResult(
            status="completed" if completed.returncode == 0 else "failed",
            command=command,
            cwd=str(cwd) if cwd else None,
            return_code=completed.returncode,
            stdout=_clean_output(completed.stdout, self.output_limit),
            stderr=_clean_output(completed.stderr, self.output_limit),
            review=review,
        )


def _looks_like_shell_control_token(value: str) -> bool:
    return any(token in value for token in ("&&", "||", ";", "|", "$(", "`", ">", "<"))


def _review_for_command(command: list[str]) -> ShellCommandReview | None:
    executable = Path(command[0]).name
    lowered_args = [str(part).lower() for part in command[1:]]
    if executable in {"rm", "rmdir", "unlink", "shred"}:
        return ShellCommandReview(
            operation="file_delete",
            reason="file deletion commands require review before execution",
            matched_command=executable,
            matched_argument=_first_non_flag(command[1:]),
        )
    if executable in {
        "touch",
        "mkdir",
        "cp",
        "mv",
        "tee",
        "install",
        "truncate",
        "dd",
        "chmod",
        "chown",
        "ln",
    }:
        return ShellCommandReview(
            operation="file_write",
            reason="file write or filesystem mutation commands require review before execution",
            matched_command=executable,
            matched_argument=_first_non_flag(command[1:]),
        )
    if executable in {"python", "python3", "bash", "sh", "zsh", "node", "npm", "uv"}:
        return ShellCommandReview(
            operation="potential_file_write",
            reason="script/runtime commands may write or delete files and require review before execution",
            matched_command=executable,
            matched_argument=_first_non_flag(command[1:]),
        )
    if executable == "sqlite3" and not _sqlite3_readonly_probe(lowered_args):
        return ShellCommandReview(
            operation="potential_file_write",
            reason="sqlite3 may mutate database files unless this is a read-only probe",
            matched_command=executable,
            matched_argument=_first_non_flag(command[1:]),
        )
    if executable in {"curl", "wget"} and _has_output_file_flag(lowered_args):
        return ShellCommandReview(
            operation="file_write",
            reason="download commands that write files require review before execution",
            matched_command=executable,
            matched_argument=_first_output_flag(command[1:]),
        )
    if executable in {"tar", "unzip"} and _looks_like_extract(lowered_args):
        return ShellCommandReview(
            operation="file_write",
            reason="archive extraction writes files and requires review before execution",
            matched_command=executable,
            matched_argument=_first_non_flag(command[1:]),
        )
    if executable == "sed" and any(arg == "-i" or arg.startswith("-i") for arg in lowered_args):
        return ShellCommandReview(
            operation="file_write",
            reason="in-place file edits require review before execution",
            matched_command=executable,
            matched_argument="-i",
        )
    return None


def _sqlite3_readonly_probe(args: list[str]) -> bool:
    return not args or any(arg in {"--version", "-version", "-help", "--help"} for arg in args)


def _has_output_file_flag(args: list[str]) -> bool:
    return any(arg in {"-o", "--output", "-O", "--output-document"} for arg in args)


def _first_output_flag(args: list[str]) -> str | None:
    for arg in args:
        if str(arg) in {"-o", "--output", "-O", "--output-document"}:
            return str(arg)
    return None


def _looks_like_extract(args: list[str]) -> bool:
    if "x" in "".join(arg.lstrip("-") for arg in args if arg.startswith("-")):
        return True
    return any(arg in {"extract", "xf", "xzf", "xjf"} for arg in args)


def _first_non_flag(args: list[str]) -> str | None:
    for arg in args:
        text = str(arg)
        if text and not text.startswith("-"):
            return text
    return None


def _clean_output(value: str, limit: int) -> str:
    redacted = redact_secrets(value)
    if not isinstance(redacted, str):
        redacted = str(redacted)
    if len(redacted) <= limit:
        return redacted
    return redacted[:limit] + "...[truncated]"
