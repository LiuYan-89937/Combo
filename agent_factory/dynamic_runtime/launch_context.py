from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from agent_factory.dynamic_runtime.runtime_service import (
    RuntimeLaunchContext,
    RuntimeLaunchContextResolver,
)
from agent_factory.runtime_protocol import (
    AttachmentPart,
    AttachmentRevisionRef,
    CapabilitySnapshot,
    ConversationMessage,
    RuntimeInstance,
)
from agent_factory.dynamic_runtime.delegation_store import DelegationStore
from agent_factory.dynamic_runtime.prompt_policies import EVIDENCE_FIRST_POLICY


@dataclass(frozen=True, slots=True)
class ClockSnapshot:
    local_date: str
    local_datetime: str
    timezone: str

    def __post_init__(self) -> None:
        for field_name in ("local_date", "local_datetime", "timezone"):
            if not str(getattr(self, field_name) or "").strip():
                raise ValueError(f"clock snapshot {field_name} must not be empty")


@dataclass(frozen=True, slots=True)
class WorkspaceLaunchProjection:
    workspace_id: str
    root_alias: str
    root_path: str
    allow_external_paths: bool
    mounts: tuple[dict[str, Any], ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("workspace_id", "root_alias", "root_path"):
            if not str(getattr(self, field_name) or "").strip():
                raise ValueError(f"workspace projection {field_name} must not be empty")


class RuntimeClock(Protocol):
    def snapshot(
        self,
        *,
        principal_id: str,
        timezone: str,
        instant_utc: str,
    ) -> ClockSnapshot:
        ...


class PolicyRuntimeClock:
    """Project one persisted UTC turn instant into its frozen policy timezone."""

    def snapshot(
        self,
        *,
        principal_id: str,
        timezone: str,
        instant_utc: str,
    ) -> ClockSnapshot:
        if not str(principal_id or "").strip():
            raise ValueError("runtime clock principal_id must not be empty")
        timezone_name = str(timezone or "").strip()
        if not timezone_name:
            raise ValueError("runtime clock timezone must not be empty")
        try:
            zone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown runtime timezone: {timezone_name}") from exc
        instant = _parse_utc_instant(instant_utc)
        local = instant.astimezone(zone)
        return ClockSnapshot(
            local_date=local.date().isoformat(),
            local_datetime=local.isoformat(),
            timezone=timezone_name,
        )


class WorkspaceLaunchResolver(Protocol):
    def resolve(
        self,
        *,
        principal_id: str,
        workspace_id: str,
    ) -> WorkspaceLaunchProjection:
        ...


class AttachmentLaunchResolver(Protocol):
    def resolve(
        self,
        *,
        principal_id: str,
        reference: AttachmentRevisionRef,
    ) -> dict[str, Any]:
        ...


class CapabilityInstructionRenderer(Protocol):
    def render(self, snapshot: CapabilitySnapshot) -> str:
        ...


class SnapshotCapabilityInstructionRenderer:
    """Render only the frozen short catalog; Skill bodies are tool-loaded."""

    def render(self, snapshot: CapabilitySnapshot) -> str:
        entries: list[str] = []
        for projection in snapshot.projections:
            fragments = [
                fragment.strip()
                for fragment in projection.model_prompt_fragments
                if fragment.strip()
            ]
            entries.extend(f"- {fragment}" for fragment in fragments)
        if not entries:
            return ""
        return "Selected capability catalog (bodies are not injected):\n" + "\n".join(entries)


class FileSystemPromptProvider:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path).expanduser().resolve()

    def load(self) -> str:
        prompt = self._path.read_text(encoding="utf-8").strip()
        if not prompt:
            raise ValueError(f"system prompt is empty: {self._path}")
        return prompt


class ComposedRuntimeLaunchContextResolver(RuntimeLaunchContextResolver):
    def __init__(
        self,
        *,
        prompt_provider: FileSystemPromptProvider,
        clock: RuntimeClock,
        workspaces: WorkspaceLaunchResolver,
        attachments: AttachmentLaunchResolver,
        capability_instructions: CapabilityInstructionRenderer,
        delegations: DelegationStore,
    ) -> None:
        self._prompt_provider = prompt_provider
        self._clock = clock
        self._workspaces = workspaces
        self._attachments = attachments
        self._capability_instructions = capability_instructions
        self._delegations = delegations

    def resolve(
        self,
        *,
        instance: RuntimeInstance,
        messages: list[ConversationMessage],
        capability_snapshot: CapabilitySnapshot,
    ) -> RuntimeLaunchContext:
        request = instance.request
        clock = self._clock.snapshot(
            principal_id=request.principal_id,
            timezone=request.policy_snapshot.timezone,
            instant_utc=request.created_at,
        )
        workspace = self._workspaces.resolve(
            principal_id=request.principal_id,
            workspace_id=request.workspace_id,
        )
        if workspace.workspace_id != request.workspace_id:
            raise ValueError("workspace launch projection identity differs from runtime request")
        attachment_refs = _turn_attachment_refs(messages, turn_id=request.turn_id)
        resolved_attachments = tuple(
            self._attachments.resolve(
                principal_id=request.principal_id,
                reference=reference,
            )
            for reference in attachment_refs
        )
        if request.runtime_role == "temporary":
            base_prompt = self._delegations.for_runtime(instance.runtime_instance_id).envelope.system_prompt
            if base_prompt is None:
                raise RuntimeError("temporary runtime task has no delegated system prompt")
            delegation_notifications = ""
        else:
            base_prompt = self._prompt_provider.load()
            notification_event_ids = _notification_event_ids(messages, turn_id=request.turn_id)
            delegation_notifications = render_delegation_notifications(
                self._delegations.claim_completion_notifications(
                    instance,
                    event_ids=notification_event_ids,
                )
            )
        capability_instructions = self._capability_instructions.render(capability_snapshot)
        system_prompt = _render_system_prompt(
            base=base_prompt,
            clock=clock,
            capability_instructions=capability_instructions,
            delegation_notifications=delegation_notifications,
            force_collaboration=request.runtime_role == "main" and request.force_collaboration,
        )
        return RuntimeLaunchContext(
            system_prompt=system_prompt,
            workspace_root_alias=workspace.root_alias,
            allow_external_paths=workspace.allow_external_paths,
            workspace_mounts=workspace.mounts,
            attachments=resolved_attachments,
        )


def _turn_attachment_refs(
    messages: list[ConversationMessage],
    *,
    turn_id: str,
) -> tuple[AttachmentRevisionRef, ...]:
    references: list[AttachmentRevisionRef] = []
    seen: set[tuple[str, int, str]] = set()
    for message in messages:
        if message.turn_id != turn_id or message.role != "user" or message.status != "committed":
            continue
        for part in message.parts:
            if not isinstance(part, AttachmentPart):
                continue
            key = (
                part.attachment.attachment_id,
                part.attachment.revision,
                part.attachment.content_digest,
            )
            if key in seen:
                continue
            seen.add(key)
            references.append(part.attachment)
    return tuple(references)


def _notification_event_ids(
    messages: list[ConversationMessage],
    *,
    turn_id: str,
) -> tuple[str, ...]:
    return tuple(
        event_id
        for message in messages
        if message.turn_id == turn_id and message.role == "user" and message.status == "committed"
        for event_id in message.notification_event_ids
    )


def _render_system_prompt(
    *,
    base: str,
    clock: ClockSnapshot,
    capability_instructions: str,
    delegation_notifications: str,
    force_collaboration: bool = False,
) -> str:
    sections = [
        base.strip(),
        EVIDENCE_FIRST_POLICY,
        (
            "Runtime time context:\n"
            f"- Current date: {clock.local_date}\n"
            f"- Current local datetime: {clock.local_datetime}\n"
            f"- Timezone: {clock.timezone}"
        ),
    ]
    instructions = str(capability_instructions or "").strip()
    if instructions:
        sections.append(instructions)
    notifications = str(delegation_notifications or "").strip()
    if notifications:
        sections.append(notifications)
    if force_collaboration:
        sections.append(
            "Collaboration mode is explicitly enabled for this turn. Decompose the user task into useful "
            "independent workstreams and delegate at least one substantive workstream to a child Agent before "
            "finishing the turn. Do not delegate ceremonial, empty, or duplicate work. If the request lacks "
            "enough information to define a substantive child objective, ask the necessary clarification instead."
        )
    return "\n\n".join(sections)


def render_delegation_notifications(events: tuple[Any, ...]) -> str:
    if not events:
        return ""
    entries = []
    for index, event in enumerate(events, start=1):
        payload = event.payload if isinstance(event.payload, dict) else {}
        task_name = str(payload.get("agent_name") or f"Delegated task {index}").strip()
        objective = str(payload.get("objective") or "").strip()
        error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
        details = error.get("details") if isinstance(error.get("details"), dict) else {}
        reason = str(
            details.get("reason")
            or details.get("message")
            or error.get("message")
            or ""
        ).strip()
        suffix = f" Reason: {reason}." if reason else ""
        if event.event_type == "cancelled" and payload.get("cancel_source") == "user":
            entries.append(
                f"- The user cancelled child Agent '{task_name}' while it was working on: {objective}. "
                "Summarize the authoritative progress and evidence already available, state what remains incomplete, "
                f"and report the cancellation to the user without restarting the task.{suffix}"
            )
        else:
            entries.append(
                f"- Child Agent '{task_name}' finished with status {event.event_type}. "
                f"Objective: {objective}.{suffix}"
            )
    return (
        "Delegated task completion notifications received since the previous main runtime. "
        "Treat these as authoritative child results, inspect details with delegation_status without supplying "
        "an internal identifier when needed, "
        "and continue or report the parent task accordingly:\n"
        + "\n".join(entries)
    )


def _parse_utc_instant(value: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError("runtime clock instant_utc must not be empty")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("runtime clock instant_utc must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("runtime clock instant_utc must include an offset")
    return parsed.astimezone(UTC)
