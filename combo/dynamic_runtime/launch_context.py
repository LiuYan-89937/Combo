from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from combo.dynamic_runtime.runtime_service import (
    RuntimeLaunchContext,
    RuntimeLaunchContextResolver,
)
from combo.runtime_attachments import (
    import_runtime_attachments,
    workspace_attachment_root,
    workspace_attachment_runtime_root,
)
from combo.runtime_protocol import (
    AttachmentPart,
    AttachmentRevisionRef,
    CapabilitySnapshot,
    ConversationMessage,
    RuntimeInstance,
)
from combo.dynamic_runtime.delegation_store import DelegationStore
from combo.runtime_i18n import RuntimeLocale, normalize_runtime_locale


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
    def render(self, snapshot: CapabilitySnapshot, *, locale: RuntimeLocale) -> str:
        ...


class SnapshotCapabilityInstructionRenderer:
    """Render only the frozen short catalog; Skill bodies are tool-loaded."""

    def render(self, snapshot: CapabilitySnapshot, *, locale: RuntimeLocale) -> str:
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
        heading = (
            "已选择的能力目录（正文不会自动注入）："
            if locale == "zh-CN"
            else "Selected capability catalog (bodies are not injected):"
        )
        return heading + "\n" + "\n".join(entries)


class FileSystemPromptProvider:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path).expanduser().resolve()

    def load(self, *, locale: RuntimeLocale) -> str:
        localized_path = self._path.with_name(f"{self._path.stem}.{locale}{self._path.suffix}")
        path = localized_path if localized_path.is_file() else self._path
        prompt = path.read_text(encoding="utf-8").strip()
        if not prompt:
            raise ValueError(f"system prompt is empty: {path}")
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
        locale = normalize_runtime_locale(request.policy_snapshot.locale)
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
        resolved_attachments = _resolve_runtime_attachments(
            resolver=self._attachments,
            principal_id=request.principal_id,
            references=attachment_refs,
            workspace=workspace,
            runtime_instance_id=instance.runtime_instance_id,
        )
        if request.runtime_role == "temporary":
            delegated_prompt = self._delegations.for_runtime(instance.runtime_instance_id).envelope.system_prompt
            if delegated_prompt is None:
                raise RuntimeError("temporary runtime task has no delegated system prompt")
            base_prompt = self._child_prompt_provider.load(locale=locale)
            delegated_directives = (delegated_prompt,)
        else:
            base_prompt = self._prompt_provider.load(locale=locale)
            delegated_directives = ()
            notification_event_ids = _notification_event_ids(messages, turn_id=request.turn_id)
            self._delegations.claim_completion_notifications(
                instance,
                event_ids=notification_event_ids,
            )
        capability_instructions = self._capability_instructions.render(capability_snapshot, locale=locale)
        system_prompt = base_prompt
        turn_directives = _turn_directives(
            delegated=delegated_directives,
            force_collaboration=request.runtime_role == "main" and request.force_collaboration,
            scheduled_run=request.scheduler_run_id is not None,
            locale=locale,
        )
        return RuntimeLaunchContext(
            system_prompt=system_prompt,
            temporal_context=_temporal_context(clock, locale=locale),
            locale=locale,
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


def _resolve_runtime_attachments(
    *,
    resolver: AttachmentLaunchResolver,
    principal_id: str,
    references: tuple[AttachmentRevisionRef, ...],
    workspace: WorkspaceLaunchProjection,
    runtime_instance_id: str,
) -> tuple[dict[str, Any], ...]:
    if not references:
        return ()
    attachment_inputs = [
        resolver.resolve(principal_id=principal_id, reference=reference)
        for reference in references
    ]
    scope = str(runtime_instance_id or "").strip()
    if not scope:
        raise ValueError("runtime attachment scope requires runtime_instance_id")
    imported = import_runtime_attachments(
        "",
        attachment_inputs,
        storage_root=workspace_attachment_root(Path(workspace.root_path)) / scope,
        runtime_path_root=workspace_attachment_runtime_root(workspace.root_alias, scope),
        scope=scope,
    )
    return tuple(dict(item) for item in imported.attachments)


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


def _temporal_context(clock: ClockSnapshot, *, locale: RuntimeLocale) -> str:
    if locale == "zh-CN":
        return (
            "运行时日期上下文：\n"
            f"- 当前日期：{clock.local_date}\n"
            f"- 时区：{clock.timezone}\n"
            "相对日期应以本轮冻结日期为准；当精确当前时间会实质影响任务时，应查询权威时间来源。"
        )
    return (
        "Runtime calendar context:\n"
        f"- Current date: {clock.local_date}\n"
        f"- Timezone: {clock.timezone}\n"
        "Resolve relative dates against this frozen turn date. Retrieve an authoritative time source when the exact "
        "current time materially affects the task."
    )


def _turn_directives(
    *,
    delegated: tuple[str, ...] = (),
    force_collaboration: bool = False,
    scheduled_run: bool = False,
    locale: RuntimeLocale,
) -> tuple[str, ...]:
    sections = [item.strip() for item in delegated if item.strip()]
    if force_collaboration:
        sections.append((
            "本轮已显式开启合奏模式。请把任务拆成有价值且相互独立的工作流，并在本轮结束前至少委派一个实质性任务。"
            "不要委派礼节性、空洞或重复工作；若信息不足以形成实质性子任务，应先询问必要信息。"
        ) if locale == "zh-CN" else (
            "Collaboration mode is explicitly enabled for this turn. Decompose the user task into useful "
            "independent workstreams and delegate at least one substantive workstream to a child Agent before "
            "finishing the turn. Do not delegate ceremonial, empty, or duplicate work. If the request lacks "
            "enough information to define a substantive child objective, ask the necessary clarification instead."
        ))
    if scheduled_run:
        sections.append((
            "这是一次自动定时任务执行。只处理绑定工作区中的定时目标，不要委派子 Agent；最终交付应自包含，并说明已核验结果、"
            "生成文件和仍未解决的阻塞。"
        ) if locale == "zh-CN" else (
            "This is an autonomous scheduled task execution. Work only on the scheduled objective in the bound "
            "workspace, do not delegate to child Agents, and finish with a self-contained delivery that reports "
            "verified results, produced files, and any unresolved blockers."
        ))
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
