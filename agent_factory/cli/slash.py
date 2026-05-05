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
    DraftAgentDetail,
    DraftsListResult,
    DraftsService,
    RegisterAgentRequest,
    RegistryService,
    RepairAgentRequest,
    RepairAgentResult,
    RepairAgentService,
    RunAgentService,
    RunAgentServiceRequest,
    RunAgentServiceResult,
    TestAgentRequest,
    TestAgentResult,
    TestAgentService,
    ValidateAgentRequest,
    ValidateAgentService,
)
from agent_factory.cli.session import ShellSession
from agent_factory.core.types import JsonDumpMixin
from agent_factory.specs import ValidationReport

SLASH_COMMANDS = [
    "/help",
    "/exit",
    "/create-agent",
    "/drafts",
    "/validate",
    "/test",
    "/register",
    "/run",
    "/repair-agent",
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
        "drafts",
        "validate_agent",
        "test_agent",
        "run_agent",
        "agent_chat",
        "repair_agent",
        "registry",
        "not_implemented",
        "error",
    ]
    exit_requested: bool = False
    message: str | None = None
    pending_requirement: str | None = None
    create_result: CreateAgentResult | None = None
    drafts_result: DraftsListResult | None = None
    draft_detail: DraftAgentDetail | None = None
    validation_report: ValidationReport | None = None
    test_result: TestAgentResult | None = None
    run_result: RunAgentServiceResult | None = None
    repair_result: RepairAgentResult | None = None
    command: str | None = None


class SlashCommandDispatcher:
    def __init__(
        self,
        *,
        session: ShellSession | None = None,
        create_service: CreateAgentService | None = None,
        validate_service: ValidateAgentService | None = None,
        test_service: TestAgentService | None = None,
        run_service: RunAgentService | None = None,
        repair_service: RepairAgentService | None = None,
        registry_service: RegistryService | None = None,
        drafts_service: DraftsService | None = None,
    ) -> None:
        self.session = session or ShellSession()
        self.create_service = create_service or CreateAgentService()
        self.validate_service = validate_service or ValidateAgentService()
        self.test_service = test_service or TestAgentService()
        self.run_service = run_service or RunAgentService()
        self.repair_service = repair_service or RepairAgentService()
        self.registry_service = registry_service
        self.drafts_service = drafts_service or DraftsService()

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

        if self._is_create_agent_line(stripped):
            return self._dispatch_create_agent_line(stripped)

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
        if command == "/test":
            return self._test(args)
        if command == "/run":
            return self._run(args)
        if command == "/repair-agent":
            return self._repair_agent(args)
        if command == "/register":
            return self._register(args)
        if command == "/registry":
            return self._registry(args)
        if command == "/drafts":
            return self._drafts(args)
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

    def _test(self, args: list[str]) -> SlashCommandResult:
        path = self._first_positional(args)
        if not path:
            path = str(self.session.selected_agent_path) if self.session.selected_agent_path else None
        if not path:
            return SlashCommandResult(
                kind="error",
                command="/test",
                message="Usage: /test <agent_package_path>",
            )
        scenario = self._option_value(args, "--scenario")
        result = self.test_service.test_agent(
            TestAgentRequest(path=Path(path), scenario=scenario)
        )
        if result.ok:
            self.session.selected_agent_path = Path(path)
        return SlashCommandResult(
            kind="test_agent",
            command="/test",
            test_result=result,
        )

    def _create_agent(self, args: list[str]) -> SlashCommandResult:
        request_or_error = self._create_agent_request(args)
        if isinstance(request_or_error, SlashCommandResult):
            return request_or_error
        result = self.create_service.create_agent(request_or_error)
        self._record_create_result(result)
        return SlashCommandResult(
            kind="create_agent",
            command="/create-agent",
            create_result=result,
        )

    def _run(self, args: list[str]) -> SlashCommandResult:
        if "--yes" in args or "-y" in args:
            return self._approve_pending_run(args)
        path = self._first_positional(args)
        if not path:
            path = str(self.session.selected_agent_path) if self.session.selected_agent_path else None
        if not path:
            latest = self.drafts_service.resolve_draft("latest")
            if latest is not None:
                path = str(latest)
                self.session.selected_agent_path = latest
        elif path == "latest":
            latest = self.drafts_service.resolve_draft("latest")
            if latest is not None:
                path = str(latest)
                self.session.selected_agent_path = latest
        user_input = self._option_value(args, "--input") or self._option_value(args, "-i")
        session_id = self._option_value(args, "--session-id") or "default"
        if not path:
            return SlashCommandResult(
                kind="error",
                command="/run",
                message="Usage: /run [agent_package_path|agent_name] [--input \"...\"]",
            )
        self.session.enter_agent_chat(
            target=path,
            path=Path(path) if Path(path).exists() else None,
            session_id=session_id,
        )
        if not user_input:
            return SlashCommandResult(
                kind="agent_chat",
                command="/run",
                message=(
                    f"Agent chat started. Session: {session_id}. "
                    "Type messages directly; use /exit to leave chat, /clear to clear this session."
                ),
            )
        result = self.run_service.run_agent(
            RunAgentServiceRequest(
                target=path,
                user_input=user_input,
                session_id=session_id,
                auto_repair="--auto-repair" in args,
            )
        )
        self._record_pending_tool_approval(result, user_input)
        return SlashCommandResult(
            kind="run_agent",
            command="/run",
            run_result=result,
            message=_agent_chat_message(session_id, result),
        )

    def _approve_pending_run(self, args: list[str]) -> SlashCommandResult:
        pending = self.session.pending_tool_approval
        target = self.session.active_agent_target
        path = self._first_positional(args)
        if path:
            target = path
        if not pending:
            return SlashCommandResult(
                kind="error",
                command="/run",
                message="No interrupted tool call is waiting for confirmation.",
            )
        if not target:
            return SlashCommandResult(
                kind="error",
                command="/run",
                message="No active Agent is available for tool confirmation.",
            )
        user_input = str(pending.get("user_input") or "").strip()
        tool_id = str(pending.get("tool_id") or "").strip()
        if not user_input or not tool_id:
            self.session.clear_tool_approval()
            return SlashCommandResult(
                kind="error",
                command="/run",
                message="Pending tool confirmation is incomplete. Please run the request again.",
            )
        session_id = self._option_value(args, "--session-id") or self.session.active_session_id
        self.session.enter_agent_chat(
            target=target,
            path=Path(target) if Path(target).exists() else self.session.active_agent_path,
            session_id=session_id,
        )
        result = self.run_service.run_agent(
            RunAgentServiceRequest(
                target=target,
                user_input=user_input,
                session_id=session_id,
                auto_repair="--auto-repair" in args,
                approved_tool_call_id=tool_id,
            )
        )
        self._record_pending_tool_approval(result, user_input)
        return SlashCommandResult(
            kind="run_agent",
            command="/run",
            run_result=result,
            message=_agent_chat_message(session_id, result),
        )

    def _record_pending_tool_approval(
        self,
        result: RunAgentServiceResult,
        user_input: str | None,
    ) -> None:
        if not user_input or not result.result or result.result.status != "interrupted":
            self.session.clear_tool_approval()
            return
        interrupted = [item for item in result.result.tool_results if item.status == "interrupted"]
        if not interrupted:
            self.session.clear_tool_approval()
            return
        item = interrupted[0]
        self.session.capture_tool_approval(
            user_input=user_input,
            tool_call_id=item.invocation_id,
            tool_id=item.tool_id,
        )

    def _repair_agent(self, args: list[str]) -> SlashCommandResult:
        path = self._first_positional(args)
        if not path:
            path = str(self.session.selected_agent_path) if self.session.selected_agent_path else None
        if not path:
            latest = self.drafts_service.resolve_draft("latest")
            if latest is not None:
                path = str(latest)
                self.session.selected_agent_path = latest
        user_input = self._option_value(args, "--input") or self._option_value(args, "-i")
        session_id = self._option_value(args, "--session-id") or "default"
        if not path:
            return SlashCommandResult(
                kind="error",
                command="/repair-agent",
                message="Usage: /repair-agent [agent_package_path|latest] --input \"...\"",
            )
        result = self.repair_service.repair_agent(
            RepairAgentRequest(
                target=path,
                user_input=user_input,
                session_id=session_id,
            )
        )
        if result.ok and result.candidate_path is not None:
            self.session.selected_agent_path = result.candidate_path
        return SlashCommandResult(kind="repair_agent", command="/repair-agent", repair_result=result)

    def _register(self, args: list[str]) -> SlashCommandResult:
        path = self._first_positional(args)
        if not path:
            path = str(self.session.selected_agent_path) if self.session.selected_agent_path else None
        if not path:
            return SlashCommandResult(
                kind="error",
                command="/register",
                message="Usage: /register <agent_package_path>",
            )
        service = self.registry_service or RegistryService()
        record = service.register(RegisterAgentRequest(package_path=Path(path)))
        return SlashCommandResult(
            kind="registry",
            command="/register",
            message=f"Registered {record.agent_name}@{record.version} as {record.status}",
        )

    def _registry(self, args: list[str]) -> SlashCommandResult:
        service = self.registry_service or RegistryService()
        records = service.list().records
        message = "\n".join(f"{record.agent_name}@{record.version} {record.status}" for record in records)
        return SlashCommandResult(kind="registry", command="/registry", message=message or "Registry is empty.")

    def _drafts(self, args: list[str]) -> SlashCommandResult:
        action = args[0] if args else "list"
        if action == "list":
            result = self.drafts_service.list_drafts()
            return SlashCommandResult(kind="drafts", command="/drafts", drafts_result=result)

        if action == "show":
            identifier = args[1] if len(args) > 1 else "latest"
            detail = self.drafts_service.show_draft(identifier)
            if detail is None:
                return SlashCommandResult(kind="error", command="/drafts", message=f"Draft not found: {identifier}")
            return SlashCommandResult(kind="drafts", command="/drafts", draft_detail=detail)

        if action == "use":
            identifier = args[1] if len(args) > 1 else "latest"
            detail = self.drafts_service.show_draft(identifier)
            if detail is None:
                return SlashCommandResult(kind="error", command="/drafts", message=f"Draft not found: {identifier}")
            self.session.selected_agent_path = detail.summary.path
            return SlashCommandResult(
                kind="drafts",
                command="/drafts",
                draft_detail=detail,
                message=f"Selected draft: {detail.summary.agent_name}",
            )

        if action == "run":
            identifier = args[1] if len(args) > 1 and not args[1].startswith("-") else "latest"
            user_input = self._option_value(args, "--input") or self._option_value(args, "-i")
            session_id = self._option_value(args, "--session-id") or "default"
            if not user_input:
                return SlashCommandResult(
                    kind="error",
                    command="/drafts",
                    message="Usage: /drafts run [draft] --input \"...\"",
                )
            path = self.drafts_service.resolve_draft(identifier)
            if path is None:
                return SlashCommandResult(kind="error", command="/drafts", message=f"Draft not found: {identifier}")
            result = self.run_service.run_agent(
                RunAgentServiceRequest(target=str(path), user_input=user_input, session_id=session_id)
            )
            return SlashCommandResult(kind="run_agent", command="/drafts", run_result=result)

        if action in {"delete", "rm", "remove"}:
            identifier = args[1] if len(args) > 1 and not args[1].startswith("-") else "latest"
            try:
                result = self.drafts_service.delete_draft(identifier, confirmed="--yes" in args or "-y" in args)
            except ValueError as error:
                return SlashCommandResult(kind="error", command="/drafts", message=str(error))
            if result is None:
                return SlashCommandResult(kind="error", command="/drafts", message=f"Draft not found: {identifier}")
            if self.session.selected_agent_path and self.session.selected_agent_path.resolve() == result.path.resolve():
                self.session.selected_agent_path = None
            return SlashCommandResult(
                kind="registry",
                command="/drafts",
                message=(
                    f"Deleted draft: {result.id}"
                    if result.deleted
                    else f"{result.message} Run /drafts delete {identifier} --yes"
                ),
            )

        detail = self.drafts_service.show_draft(action)
        if detail is None:
            return SlashCommandResult(kind="error", command="/drafts", message=f"Draft not found: {action}")
        return SlashCommandResult(kind="drafts", command="/drafts", draft_detail=detail)

    def stream_create_agent_events(
        self,
        line: str,
    ) -> tuple[SlashCommandResult | None, Iterator[FactoryEvent] | None]:
        stripped = line.strip()
        if not self._is_create_agent_line(stripped):
            return SlashCommandResult(kind="error", message="Expected /create-agent command."), None
        request_or_error = self._create_agent_request_from_line(stripped)
        if isinstance(request_or_error, SlashCommandResult):
            return request_or_error, None
        return None, self.create_service.stream_create_agent(request_or_error)

    def stream_natural_language_create_events(
        self,
        line: str,
    ) -> tuple[SlashCommandResult | None, Iterator[FactoryEvent] | None]:
        self.session.capture_requirement(line)
        if not self.session.pending_requirement:
            return SlashCommandResult(kind="empty"), None
        return self.stream_pending_create_events()

    def stream_pending_create_events(
        self,
    ) -> tuple[SlashCommandResult | None, Iterator[FactoryEvent] | None]:
        if not self.session.pending_requirement:
            return SlashCommandResult(kind="empty"), None
        request = CreateAgentRequest(
            prompt=self.session.pending_requirement,
            draft=True,
            stream=True,
            show_thinking=False,
        )
        return None, self.create_service.stream_create_agent(request)

    def _create_agent_request(self, args: list[str]) -> CreateAgentRequest | SlashCommandResult:
        prompt = self._create_agent_prompt_from_args(args)
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
            stream="--stream" in args,
            show_thinking="--show-thinking" in args and "--hide-thinking" not in args,
        )

    def _dispatch_create_agent_line(self, stripped: str) -> SlashCommandResult:
        request_or_error = self._create_agent_request_from_line(stripped)
        if isinstance(request_or_error, SlashCommandResult):
            return request_or_error
        result = self.create_service.create_agent(request_or_error)
        self._record_create_result(result)
        return SlashCommandResult(
            kind="create_agent",
            command="/create-agent",
            create_result=result,
        )

    def _record_create_result(self, result: CreateAgentResult) -> None:
        if result.status == "needs_clarification":
            self.session.capture_clarification(
                questions=result.clarification_questions,
                options=result.clarification_options,
            )
            return
        if result.status in {"completed", "completed_with_warnings"}:
            self.session.clear_pending_clarification()
            if result.output_path is not None:
                self.session.selected_agent_path = result.output_path
            return
        if result.status == "not_agent_request":
            self.session.clear_pending_requirement()

    def _create_agent_request_from_line(self, stripped: str) -> CreateAgentRequest | SlashCommandResult:
        raw_args = stripped[len("/create-agent") :].strip()
        prompt, flags = self._parse_create_agent_raw_args(raw_args)
        if not prompt:
            prompt = self.session.pending_requirement
        if not prompt:
            return SlashCommandResult(
                kind="error",
                command="/create-agent",
                message="No requirement captured. Type /create-agent and fill the requirement box.",
            )
        return CreateAgentRequest(
            prompt=prompt,
            draft="--no-draft" not in flags,
            stream="--stream" in flags,
            show_thinking="--show-thinking" in flags and "--hide-thinking" not in flags,
        )

    @classmethod
    def _parse_create_agent_raw_args(cls, raw_args: str) -> tuple[str | None, set[str]]:
        known_flags = {
            "--draft",
            "--no-draft",
            "--stream",
            "--no-stream",
            "--show-thinking",
            "--hide-thinking",
        }
        flags = {flag for flag in known_flags if cls._contains_flag(raw_args, flag)}
        prompt_start = cls._find_prompt_value_start(raw_args)
        if prompt_start is None:
            return None, flags
        tail = raw_args[prompt_start:].lstrip()
        prompt, trailing_flags = cls._strip_trailing_create_flags(tail)
        flags.update(trailing_flags)
        prompt = prompt.strip()
        if prompt[:1] in {'"', "'"}:
            prompt = prompt[1:]
        if prompt[-1:] in {'"', "'"}:
            prompt = prompt[:-1]
        return prompt.strip() or None, flags

    @staticmethod
    def _is_create_agent_line(stripped: str) -> bool:
        return stripped == "/create-agent" or stripped.startswith("/create-agent ")

    @staticmethod
    def _contains_flag(raw_args: str, flag: str) -> bool:
        padded = f" {raw_args.strip()} "
        return f" {flag} " in padded

    @staticmethod
    def _strip_trailing_create_flags(value: str) -> tuple[str, set[str]]:
        flags: set[str] = set()
        prompt = value.rstrip()
        known_flags = {
            "--draft",
            "--no-draft",
            "--stream",
            "--no-stream",
            "--show-thinking",
            "--hide-thinking",
        }
        changed = True
        while changed:
            changed = False
            for flag in known_flags:
                suffix = f" {flag}"
                if prompt == flag:
                    flags.add(flag)
                    prompt = ""
                    changed = True
                    break
                if prompt.endswith(suffix):
                    flags.add(flag)
                    prompt = prompt[: -len(suffix)].rstrip()
                    changed = True
                    break
        return prompt, flags

    @staticmethod
    def _find_prompt_value_start(raw_args: str) -> int | None:
        for option in ("--prompt", "-p"):
            search_from = 0
            while True:
                index = raw_args.find(option, search_from)
                if index < 0:
                    break
                before_ok = index == 0 or raw_args[index - 1].isspace()
                after_index = index + len(option)
                after = raw_args[after_index : after_index + 1]
                after_ok = not after or after.isspace() or after == "="
                if before_ok and after_ok:
                    return after_index + 1 if after == "=" else after_index
                search_from = after_index
        return None

    @staticmethod
    def _create_agent_prompt_from_args(args: list[str]) -> str | None:
        prompt_options = {"--prompt", "-p"}
        boolean_options = {
            "--draft",
            "--no-draft",
            "--stream",
            "--no-stream",
            "--show-thinking",
            "--hide-thinking",
        }
        for index, arg in enumerate(args):
            if arg.startswith("--prompt=") or arg.startswith("-p="):
                return arg.split("=", 1)[1].strip() or None
            if arg not in prompt_options:
                continue
            prompt_parts: list[str] = []
            for value in args[index + 1 :]:
                if value in boolean_options or value in prompt_options:
                    break
                prompt_parts.append(value)
            prompt = " ".join(prompt_parts).strip()
            return prompt or None
        return None

    def _help_text(self) -> str:
        pending = self.session.pending_requirement or "none"
        commands = "\n".join(f"  {command}" for command in SLASH_COMMANDS)
        return f"Commands:\n{commands}\n\nPending requirement: {pending}"

    @staticmethod
    def _first_positional(args: list[str]) -> str | None:
        options_with_values = {"--input", "-i", "--scenario", "--prompt", "-p", "--session-id"}
        skip_next = False
        for arg in args:
            if skip_next:
                skip_next = False
                continue
            if arg in options_with_values:
                skip_next = True
                continue
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


def _agent_chat_message(session_id: str, result: RunAgentServiceResult) -> str:
    base = (
        f"Agent chat active. Session: {session_id}. "
        "Type the next message directly; /exit leaves chat, /clear clears memory."
    )
    if result.result and result.result.status == "interrupted":
        return f"{base} Use /run --yes to approve the pending tool call."
    return base
