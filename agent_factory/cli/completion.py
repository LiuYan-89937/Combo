from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document

from agent_factory.application import DraftsService
from agent_factory.cli.session import ShellSession
from agent_factory.cli.slash import SLASH_COMMANDS


COMMAND_OPTIONS: dict[str, list[str]] = {
    "/create-agent": ["--prompt", "-p", "--draft", "--no-draft", "--stream", "--no-stream"],
    "/drafts": ["list", "show", "use", "run", "delete", "rm", "latest"],
    "/validate": ["latest"],
    "/test": ["latest", "--scenario"],
    "/register": ["latest"],
    "/run": ["latest", "--input", "-i", "--yes", "-yes", "-y", "--session-id", "--version", "--process", "--no-process"],
    "/registry": ["list", "rollback"],
}


@dataclass(frozen=True)
class CompletionCandidate:
    text: str
    display_meta: str = ""


class ContextualSlashCompleter(Completer):
    """Slash command completer with command-aware subcommands and draft ids."""

    def __init__(
        self,
        *,
        session: ShellSession,
        drafts_service: DraftsService | None = None,
    ) -> None:
        self.session = session
        self.drafts_service = drafts_service or DraftsService()

    def get_completions(self, document: Document, complete_event):  # type: ignore[override]
        text = document.text_before_cursor
        if not text.startswith("/"):
            return
        if self.session.in_agent_chat:
            yield from self._yield_matches(text, _agent_chat_command_candidates())
            return

        parts = text.split()
        trailing_space = bool(text and text[-1].isspace())
        if not parts:
            yield from self._yield_matches("/", _command_candidates())
            return

        command = parts[0]
        if len(parts) == 1 and not trailing_space:
            yield from self._yield_matches(command, _command_candidates())
            return

        current = "" if trailing_space else parts[-1]
        options = self._contextual_candidates(command, parts[1:], trailing_space=trailing_space)
        yield from self._yield_matches(current, options)

    def _contextual_candidates(
        self,
        command: str,
        args: list[str],
        *,
        trailing_space: bool,
    ) -> list[CompletionCandidate]:
        if command == "/drafts":
            return self._drafts_candidates(args, trailing_space=trailing_space)
        if command in {"/validate", "/test", "/register"}:
            return [*_draft_candidates(self.drafts_service), *self._selected_candidate(), *_option_candidates(command)]
        if command == "/run":
            if "--input" in args or "-i" in args:
                return []
            return [
                CompletionCandidate("--input", "message"),
                CompletionCandidate("--session-id", "session"),
                *_draft_candidates(self.drafts_service),
                *self._selected_candidate(),
            ]
        return _option_candidates(command)

    def _drafts_candidates(
        self,
        args: list[str],
        *,
        trailing_space: bool,
    ) -> list[CompletionCandidate]:
        action = args[0] if args else ""
        if not action or (len(args) == 1 and not trailing_space):
            return [
                CompletionCandidate("list", "show drafts"),
                CompletionCandidate("show", "inspect draft"),
                CompletionCandidate("use", "select draft"),
                CompletionCandidate("run", "run draft"),
                CompletionCandidate("delete", "delete draft"),
                CompletionCandidate("rm", "delete draft"),
                CompletionCandidate("latest", "latest draft"),
                *_draft_candidates(self.drafts_service),
            ]
        if action in {"show", "use", "run", "delete", "rm", "remove"}:
            candidates = [CompletionCandidate("latest", "latest draft"), *_draft_candidates(self.drafts_service)]
            if action == "run":
                candidates.append(CompletionCandidate("--input", "message"))
            if action in {"delete", "rm", "remove"}:
                candidates.append(CompletionCandidate("--yes", "confirm deletion"))
                candidates.append(CompletionCandidate("-y", "confirm deletion"))
            return candidates
        return []

    def _selected_candidate(self) -> list[CompletionCandidate]:
        if not self.session.selected_agent_path:
            return []
        return [
            CompletionCandidate(
                str(self.session.selected_agent_path),
                "selected",
            )
        ]

    @staticmethod
    def _yield_matches(prefix: str, candidates: list[CompletionCandidate]):
        normalized_prefix = prefix.lstrip("/")
        start_position = -len(prefix) if prefix else 0
        seen: set[str] = set()
        for candidate in candidates:
            if candidate.text in seen:
                continue
            seen.add(candidate.text)
            searchable = candidate.text.lstrip("/")
            if normalized_prefix and not searchable.startswith(normalized_prefix):
                continue
            yield Completion(
                candidate.text,
                start_position=start_position,
                display_meta=candidate.display_meta,
            )


def _command_candidates() -> list[CompletionCandidate]:
    return [CompletionCandidate(command, "command") for command in SLASH_COMMANDS]


def _agent_chat_command_candidates() -> list[CompletionCandidate]:
    return [
        CompletionCandidate("/help", "chat help"),
        CompletionCandidate("/run --yes", "approve tool"),
        CompletionCandidate("/exit", "leave chat"),
        CompletionCandidate("/clear", "clear session"),
    ]


def _option_candidates(command: str) -> list[CompletionCandidate]:
    return [CompletionCandidate(option, "option") for option in COMMAND_OPTIONS.get(command, [])]


def _draft_candidates(drafts_service: DraftsService) -> list[CompletionCandidate]:
    try:
        drafts = drafts_service.list_drafts().drafts
    except Exception:
        return []
    candidates: list[CompletionCandidate] = []
    for draft in drafts:
        candidates.append(CompletionCandidate(draft.display_id, draft.agent_name))
        if draft.agent_id:
            candidates.append(CompletionCandidate(draft.agent_id, "agent id"))
    return candidates
