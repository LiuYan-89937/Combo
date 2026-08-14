from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
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
        child_prompt_provider: FileSystemPromptProvider,
        clock: RuntimeClock,
        workspaces: WorkspaceLaunchResolver,
        attachments: AttachmentLaunchResolver,
        capability_instructions: CapabilityInstructionRenderer,
        delegations: DelegationStore,
    ) -> None:
        self._prompt_provider = prompt_provider
        self._child_prompt_provider = child_prompt_provider
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
            delegated_prompt = self._delegations.for_runtime(instance.runtime_instance_id).envelope.system_prompt
            if delegated_prompt is None:
                raise RuntimeError("temporary runtime task has no delegated system prompt")
            base_prompt = self._child_prompt_provider.load()
            delegated_directives = (delegated_prompt,)
        else:
            base_prompt = self._prompt_provider.load()
            delegated_directives = ()
            notification_event_ids = _notification_event_ids(messages, turn_id=request.turn_id)
            self._delegations.claim_completion_notifications(
                instance,
                event_ids=notification_event_ids,
            )
        capability_instructions = self._capability_instructions.render(capability_snapshot)
        system_prompt = _render_system_prompt(base=base_prompt)
        turn_directives = _turn_directives(
            delegated=delegated_directives,
            force_collaboration=request.runtime_role == "main" and request.force_collaboration,
            scheduled_run=request.scheduler_run_id is not None,
        )
        return RuntimeLaunchContext(
            system_prompt=system_prompt,
            temporal_context=_temporal_context(clock),
            capability_instructions=capability_instructions,
            turn_directives=turn_directives,
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
) -> str:
    return "\n\n".join((base.strip(), EVIDENCE_FIRST_POLICY))


def _temporal_context(clock: ClockSnapshot) -> str:
    return (
        "Runtime calendar context:\n"
        f"- Current date: {clock.local_date}\n"
        f"- Timezone: {clock.timezone}\n"
        "Resolve relative calendar dates against this frozen turn date. Retrieve an authoritative time source "
        "when the exact current time materially affects the task."
    )


def _turn_directives(
    *,
    delegated: tuple[str, ...] = (),
    force_collaboration: bool = False,
    scheduled_run: bool = False,
) -> tuple[str, ...]:
    sections = [item.strip() for item in delegated if item.strip()]
    if force_collaboration:
        sections.append(
            "Collaboration mode is explicitly enabled for this turn. Decompose the user task into useful "
            "independent workstreams and delegate at least one substantive workstream to a child Agent before "
            "finishing the turn. Do not delegate ceremonial, empty, or duplicate work. If the request lacks "
            "enough information to define a substantive child objective, ask the necessary clarification instead."
        )
    if scheduled_run:
        sections.append(
            "This is an autonomous scheduled task execution. Work only on the scheduled objective in the bound "
            "workspace, do not delegate to child Agents, and finish with a self-contained delivery that reports "
            "verified results, produced files, and any unresolved blockers."
        )
    return tuple(sections)


def render_delegation_notification_message(event: Any) -> str:
    """Render one durable child terminal event as an internal user-channel message."""
    payload = event.payload if isinstance(event.payload, dict) else {}
    task_name = str(payload.get("agent_name") or "Delegated task").strip()
    objective = str(payload.get("objective") or "").strip()
    error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    details = error.get("details") if isinstance(error.get("details"), dict) else {}
    reason = str(
        details.get("reason")
        or details.get("message")
        or error.get("message")
        or ""
    ).strip()
    result = payload.get("result")
    result_text = (
        json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        if isinstance(result, (dict, list))
        else str(result or "").strip()
    )
    lines = [
        "Internal child Agent terminal notification.",
        f"Agent: {task_name}",
        f"Objective: {objective}",
        f"Status: {event.event_type}",
    ]
    if result_text:
        lines.append(f"Result: {result_text}")
    if reason:
        lines.append(f"Reason: {reason}")
    if event.event_type == "cancelled" and payload.get("cancel_source") == "user":
        lines.append(
            "This child task was explicitly cancelled by the user; it was not a runtime failure. "
            "Report available progress and incomplete items, "
            "and do not restart, retry, or delegate a replacement task unless the user asks."
        )
    else:
        lines.append(
            "Process this exactly like a user-channel update: report or continue from this terminal result "
            "without inventing missing evidence."
        )
    return "\n".join(lines)


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
