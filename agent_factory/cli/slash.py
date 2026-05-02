from __future__ import annotations

import shlex
from collections.abc import Iterator
from pathlib import Path
from typing import Literal

from pydantic import ConfigDict

from agent_factory.core import FactoryEvent
from agent_factory.application import (
    CreateAgentRequest,
    CreateAgentResult,
    CreateAgentService,
    ValidateAgentRequest,
    ValidateAgentService,
)
from agent_factory.cli.session import ShellSession
from agent_factory.core.types import JsonDumpMixin
from agent_factory.specs import ValidationReport

SLASH_COMMANDS = [
    "/help",
    "/exit",
    "/init",
    "/create-agent",
    "/review-agent",
    "/approve-agent",
    "/validate",
    "/test",
    "/register",
    "/run",
    "/upgrade",
    "/plan-upgrade",
    "/review-patch",
    "/approve-patch",
    "/apply-patch-plan",
    "/trace",
    "/diff",
    "/approval",
    "/registry",
]


class SlashCommandResult(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    kind: Literal[
        "empty",
        "requirement",
        "help",
        "exit",
        "create_agent",
        "validate_agent",
        "not_implemented",
        "error",
    ]
    exit_requested: bool = False
    message: str | None = None
    pending_requirement: str | None = None
    create_result: CreateAgentResult | None = None
    validation_report: ValidationReport | None = None
    command: str | None = None


class SlashCommandDispatcher:
    def __init__(
        self,
        *,
        session: ShellSession | None = None,
        create_service: CreateAgentService | None = None,
        validate_service: ValidateAgentService | None = None,
    ) -> None:
        self.session = session or ShellSession()
        self.create_service = create_service or CreateAgentService()
        self.validate_service = validate_service or ValidateAgentService()

    def dispatch(self, line: str) -> SlashCommandResult:
        stripped = line.strip()
        if not stripped:
            return SlashCommandResult(kind="empty")
        if not stripped.startswith("/"):
            self.session.capture_requirement(stripped)
            return SlashCommandResult(
                kind="requirement",
                message="Requirement captured",
                pending_requirement=self.session.pending_requirement,
            )

        try:
            parts = shlex.split(stripped)
        except ValueError as error:
            return SlashCommandResult(kind="error", message=str(error))

        command = parts[0]
        args = parts[1:]
        if command == "/help":
            return SlashCommandResult(
                kind="help",
                command=command,
                message=self._help_text(),
                pending_requirement=self.session.pending_requirement,
            )
        if command == "/exit":
            return SlashCommandResult(
                kind="exit",
                command=command,
                exit_requested=True,
                message="Exiting AgentFactory shell.",
            )
        if command == "/validate":
            return self._validate(args)
        if command == "/create-agent":
            return self._create_agent(args)
        if command in SLASH_COMMANDS:
            return SlashCommandResult(
                kind="not_implemented",
                command=command,
                message=f"{command} is not implemented in phase 01.",
            )
        return SlashCommandResult(kind="error", command=command, message=f"Unknown command: {command}")

    def _validate(self, args: list[str]) -> SlashCommandResult:
        path = self._first_positional(args)
        if not path:
            return SlashCommandResult(
                kind="error",
                command="/validate",
                message="Usage: /validate <agent_package_path>",
            )
        result = self.validate_service.validate_agent(ValidateAgentRequest(path=Path(path)))
        if result.ok:
            self.session.selected_agent_path = Path(path)
        return SlashCommandResult(
            kind="validate_agent",
            command="/validate",
            validation_report=result.report,
        )

    def _create_agent(self, args: list[str]) -> SlashCommandResult:
        request_or_error = self._create_agent_request(args)
        if isinstance(request_or_error, SlashCommandResult):
            return request_or_error
        result = self.create_service.create_agent(request_or_error)
        return SlashCommandResult(
            kind="create_agent",
            command="/create-agent",
            create_result=result,
        )

    def stream_create_agent_events(
        self,
        line: str,
    ) -> tuple[SlashCommandResult | None, Iterator[FactoryEvent] | None]:
        try:
            parts = shlex.split(line.strip())
        except ValueError as error:
            return SlashCommandResult(kind="error", message=str(error)), None
        if not parts or parts[0] != "/create-agent":
            return SlashCommandResult(kind="error", message="Expected /create-agent command."), None
        request_or_error = self._create_agent_request(parts[1:])
        if isinstance(request_or_error, SlashCommandResult):
            return request_or_error, None
        return None, self.create_service.stream_create_agent(request_or_error)

    def _create_agent_request(self, args: list[str]) -> CreateAgentRequest | SlashCommandResult:
        prompt = self._option_value(args, "--prompt") or self._option_value(args, "-p")
        if not prompt:
            prompt = self.session.pending_requirement
        if not prompt:
            return SlashCommandResult(
                kind="error",
                command="/create-agent",
                message="No requirement captured. Type a natural language requirement first.",
            )
        return CreateAgentRequest(
            prompt=prompt,
            draft="--no-draft" not in args,
            stream="--no-stream" not in args,
        )

    def _help_text(self) -> str:
        pending = self.session.pending_requirement or "none"
        commands = "\n".join(f"  {command}" for command in SLASH_COMMANDS)
        return f"Commands:\n{commands}\n\nPending requirement: {pending}"

    @staticmethod
    def _first_positional(args: list[str]) -> str | None:
        for arg in args:
            if not arg.startswith("-"):
                return arg
        return None

    @staticmethod
    def _option_value(args: list[str], option: str) -> str | None:
        if option not in args:
            return None
        index = args.index(option)
        next_index = index + 1
        if next_index >= len(args):
            return None
        return args[next_index]
