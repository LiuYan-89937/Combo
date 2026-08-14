from __future__ import annotations

from collections import defaultdict
import base64
from ipaddress import ip_address
import json
import mimetypes
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from combo.dynamic_runtime.repositories import utc_now_text
from combo.dynamic_runtime.knowledge_search import KnowledgeRetrievalSettings
from combo.native_directory_picker import NativeDirectoryPicker, NativeDirectoryPickerUnavailableError
from combo.runtime_protocol import (
    CommandEnvelope,
    CommandReceipt,
    RuntimeProtocolDescriptor,
    ToolCallRecord,
    UserRuntimePolicy,
)
from combo.runtime_protocol.chat_parts import build_chat_turn_messages
from combo.workspace_directories import WorkspaceDirectoryBrowser
from web_frontend.backend.frontend_event_bridge import project_runtime_event
from web_frontend.backend.attachment_upload_store import AttachmentUploadError, attachment_upload_store


SYSTEM_CHAT_PACKAGE_ID = "main_chat"


class FrontendCommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command: dict[str, Any]


class BackgroundTaskSettingsWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_parallel_sub_agents: int
    revision: int | None = None


class BackgroundTaskCancelWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str | None = None


class BackgroundTaskInteractionWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["approve", "deny", "trust_tool", "revise", "answer", "continue"]
    payload: dict[str, Any] = Field(default_factory=dict)


class RuntimePreferencesWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int | None = None
    execution_preference: str | None = None
    model_profile_id: str | None = None
    reasoning_intensity: int | None = None
    approval_mode: str | None = None
    request_timeout_seconds: int | None = None
    browser_operation_timeout_ms: int | None = Field(default=None, ge=1_000, le=600_000)
    browser_navigation_timeout_ms: int | None = Field(default=None, ge=1_000, le=600_000)
    max_retries: int | None = None
    max_parallel_sub_agents: int | None = None
    memory_auto_write_enabled: bool | None = None
    memory_write_interval_turns: int | None = Field(default=None, ge=1, le=1000)
    memory_agent_write_enabled: bool | None = None
    memory_max_injected_items: int | None = Field(default=None, ge=1, le=64)
    memory_max_injected_tokens: int | None = Field(default=None, ge=100, le=32000)


class MemoryDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    memory_id: str
    workspace_id: str | None = None


class KnowledgeRetrievalSettingsWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)
    lexical_limit: int = Field(ge=1, le=200)
    vector_limit: int = Field(ge=1, le=200)
    result_limit: int = Field(ge=1, le=50)
    rrf_k: int = Field(ge=1, le=1000)
    vector_minimum_similarity: float = Field(ge=-1, le=1)
    lexical_weight: float = Field(gt=0, le=10)
    vector_weight: float = Field(gt=0, le=10)


class KnowledgeChunkingWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_size: int = Field(ge=100, le=8000)
    chunk_overlap: int = Field(ge=0, le=2000)

    @model_validator(mode="after")
    def validate_overlap(self) -> "KnowledgeChunkingWrite":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        return self


class KnowledgeSourceWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["folder", "file", "url", "note"]
    display_name: str
    uri: str
    content: str | None = None
    mount_mode: Literal["index_only", "rag"]
    chunking: KnowledgeChunkingWrite | None = None


class WorkspaceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = None
    mode: Literal["isolated", "project"] = "isolated"
    root_kind: Literal["managed", "linked"] = "managed"
    workdir_root: str | None = None
    owner_package_id: str | None = None


class WorkspaceUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = None
    mode: Literal["isolated", "project"] | None = None
    archived: bool | None = None


class DirectorySelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    initial_path: str | None = None


def create_frontend_interaction_router(backend: Any) -> APIRouter:
    router = APIRouter()

    @router.post("/api/commands")
    async def submit_frontend_command(
        body: FrontendCommandRequest,
        x_combo_principal: str = Header(alias="X-Combo-Principal"),
        x_combo_client: str = Header(alias="X-Combo-Client"),
        x_combo_timezone: str = Header(alias="X-Combo-Timezone"),
    ) -> dict[str, Any]:
        command = body.command
        command_type = _required_text(command.get("type"), "command.type")
        principal_id = _required_text(x_combo_principal, "principal header")
        client_id = _required_text(x_combo_client, "client header")
        timezone = _required_text(x_combo_timezone, "timezone header")
        backend.application.stores.conversations.create_principal(principal_id)

        if command_type in {"send_message", "run_agent_package", "send_agent_package_message"}:
            payload = dict(command.get("payload") or {})
            session_id = _ensure_conversation(
                backend,
                principal_id=principal_id,
                requested_session_id=command.get("session_id"),
                requested_workspace_id=payload.get("workspace_id"),
            )
            content = str(command.get("message") or payload.get("message") or "").strip()
            if not content:
                raise HTTPException(status_code=422, detail="message must not be empty")
            turn_policy = _synchronize_policy(
                backend,
                principal_id=principal_id,
                timezone=timezone,
                command_payload=payload,
            )
            envelope = CommandEnvelope(
                protocol_version=RuntimeProtocolDescriptor(
                    build_revision=backend.config.build_revision
                ).protocol_version,
                command_id=_command_id(command),
                client_instance_id=client_id,
                principal_id=principal_id,
                session_id=session_id,
                payload={
                    "kind": "send_message",
                    "message_id": uuid4().hex,
                    "content": content,
                    "attachments": _attachment_references(principal_id, payload.get("attachments")),
                    "execution_preference": turn_policy.execution_preference,
                    "approval_mode": turn_policy.approval_mode,
                    "force_collaboration": bool(payload.get("force_collaboration", False)),
                },
            )
        elif command_type == "steer_runtime_request":
            source = dict(command.get("payload") or {})
            queued_command_id = _required_text(
                source.get("queued_request_id"),
                "payload.queued_request_id",
            )
            queued = backend.application.stores.commands.get_receipt(queued_command_id)
            if queued.principal_id != principal_id:
                raise HTTPException(status_code=404, detail="queued message command not found")
            envelope = CommandEnvelope(
                protocol_version=RuntimeProtocolDescriptor(
                    build_revision=backend.config.build_revision
                ).protocol_version,
                command_id=_command_id(command),
                client_instance_id=client_id,
                principal_id=principal_id,
                session_id=queued.session_id,
                payload={
                    "kind": "steer_runtime_request",
                    "queued_command_id": queued.command_id,
                },
            )
        elif command_type == "cancel_runtime_request":
            source = dict(command.get("payload") or {})
            reason = str(source.get("reason") or "user_cancelled")
            current = _runtime_cancel_target_or_none(backend, principal_id, command)
            if current is not None:
                session_id = current.request.session_id
                payload = {
                    "kind": "cancel_runtime_request",
                    "runtime_instance_id": current.runtime_instance_id,
                    "request_id": current.request.request_id,
                    "reason": reason,
                }
            else:
                target = _active_pre_runtime_command(backend, principal_id, command)
                session_id = target.session_id
                payload = {
                    "kind": "cancel_command_request",
                    "target_command_id": target.command_id,
                    "reason": reason,
                }
            envelope = CommandEnvelope(
                protocol_version=RuntimeProtocolDescriptor(
                    build_revision=backend.config.build_revision
                ).protocol_version,
                command_id=_command_id(command),
                client_instance_id=client_id,
                principal_id=principal_id,
                session_id=session_id,
                payload=payload,
            )
        elif command_type == "resume_interrupt":
            current = _active_runtime(backend, principal_id, command)
            source = dict(command.get("payload") or {})
            action = str(source.get("action") or "").strip()
            if action not in {"approve", "deny", "trust_tool", "revise", "answer"}:
                raise HTTPException(status_code=422, detail="unsupported interrupt action")
            decision = action
            response = str(source.get("answer") or source.get("input_text") or source.get("revision_guidance") or "").strip()
            envelope = CommandEnvelope(
                protocol_version=RuntimeProtocolDescriptor(
                    build_revision=backend.config.build_revision
                ).protocol_version,
                command_id=_command_id(command),
                client_instance_id=client_id,
                principal_id=principal_id,
                session_id=current.request.session_id,
                payload={
                    "kind": "resume_interrupt",
                    "runtime_instance_id": current.runtime_instance_id,
                    "request_id": current.request.request_id,
                    "interrupt_id": _interrupt_id(
                        backend,
                        current.runtime_instance_id,
                        requested_interrupt_id=_required_text(
                            source.get("interrupt_id"),
                            "interrupt_id",
                        ),
                    ),
                    "decision": decision,
                    **({"response": response} if decision in {"answer", "revise"} else {}),
                },
            )
        else:
            raise HTTPException(status_code=410, detail=f"frontend command was removed: {command_type}")

        receipt = backend.application.stores.commands.accept(
            envelope,
            CommandReceipt(
                command_id=envelope.command_id,
                client_instance_id=envelope.client_instance_id,
                principal_id=envelope.principal_id,
                session_id=envelope.session_id,
                status="received",
            ),
        )
        backend.supervisor.notify_commands()
        backend.supervisor.notify_outbox()
        return {
            "accepted": receipt.status in {"received", "queued"},
            "command": command,
            "receipt": receipt.model_dump(mode="json"),
            "event_stream_id": backend.frontend_events.stream_id,
        }

    @router.get("/api/agent-packages")
    async def agent_packages(request: Request) -> dict[str, Any]:
        principal_id = _principal(request)
        sessions = _session_views(backend, principal_id)
        return {"event": _event("agent_packages_listed", {"packages": [_system_package(len(sessions))]})}

    @router.post("/api/agent-packages/select")
    async def select_agent_package(request: Request) -> dict[str, Any]:
        principal_id = _principal(request)
        payload = await request.json()
        _require_system_package(payload.get("package_id"))
        sessions = _session_views(backend, principal_id)
        return {
            "event": _event(
                "agent_package_selected",
                {"package": _system_package(len(sessions)), "sessions": sessions},
            )
        }

    @router.get("/api/agent-packages/{package_id}/sessions")
    async def agent_package_sessions(request: Request, package_id: str) -> dict[str, Any]:
        _require_system_package(package_id)
        return {"event": _event("agent_package_sessions_listed", {"sessions": _session_views(backend, _principal(request))})}

    @router.get("/api/agent-packages/{package_id}/sessions/{session_id}")
    async def agent_package_session(request: Request, package_id: str, session_id: str) -> dict[str, Any]:
        _require_system_package(package_id)
        principal_id = _principal(request)
        return {
            "event": _event(
                "agent_package_session_loaded",
                {
                    "package_id": SYSTEM_CHAT_PACKAGE_ID,
                    "session": _session_snapshot(backend, principal_id, session_id),
                },
                session_id=session_id,
            )
        }

    @router.delete("/api/agent-packages/{package_id}/sessions/{session_id}")
    async def delete_agent_package_session(request: Request, package_id: str, session_id: str) -> dict[str, Any]:
        _require_system_package(package_id)
        principal_id = _principal(request)
        try:
            result = await backend.conversation_lifecycle.delete_one(
                session_id=session_id,
                principal_id=principal_id,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="conversation not found") from exc
        except TimeoutError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "event": _event(
                "agent_package_session_deleted",
                {
                    "package_id": SYSTEM_CHAT_PACKAGE_ID,
                    "session_id": session_id,
                    "deleted_session_ids": list(result.session_ids),
                    "sessions": _session_views(backend, principal_id),
                },
                session_id=session_id,
            )
        }

    @router.get("/api/agent-packages/recent-sessions")
    async def recent_agent_sessions(request: Request, limit: int = 5) -> dict[str, Any]:
        return {"sessions": _session_views(backend, _principal(request))[: max(1, limit)]}

    @router.get("/api/agent-packages/instances")
    async def agent_package_instances(request: Request) -> dict[str, Any]:
        _principal(request)
        return {"event": _event("agent_package_instances_listed", {"instances": []})}

    @router.get("/api/background-tasks/settings")
    async def background_task_settings(request: Request) -> dict[str, Any]:
        principal_id = _principal(request)
        policy = _policy_or_none(backend, principal_id)
        return {
            "settings": {
                "max_parallel_sub_agents": policy.max_parallel_temporary_agents if policy else 5,
                "revision": policy.revision if policy else 0,
                "updated_at": policy.updated_at if policy else utc_now_text(),
            }
        }

    @router.get("/api/runtime/preferences")
    async def runtime_preferences(request: Request) -> dict[str, Any]:
        principal_id = _principal(request)
        return _runtime_preferences_view(_policy_or_none(backend, principal_id))

    @router.patch("/api/runtime/preferences")
    async def update_runtime_preferences(
        request: Request,
        payload: RuntimePreferencesWrite,
    ) -> dict[str, Any]:
        principal_id = _principal(request)
        backend.application.stores.conversations.create_principal(principal_id)
        timezone = _required_text(request.headers.get("X-Combo-Timezone"), "timezone header")
        current = _policy_or_none(backend, principal_id)
        if current is not None and payload.expected_revision != current.revision:
            raise HTTPException(status_code=409, detail="runtime policy revision conflict")
        if current is None and payload.expected_revision not in {None, 0}:
            raise HTTPException(status_code=409, detail="runtime policy revision conflict")
        approval_mode = payload.approval_mode or (current.approval_mode if current else "ask")
        if approval_mode not in {"auto", "ask", "always_approval"}:
            raise HTTPException(status_code=422, detail="unsupported approval_mode")
        execution_preference = payload.execution_preference or (current.execution_preference if current else "react")
        if execution_preference not in {"react", "plan_and_execute"}:
            raise HTTPException(status_code=422, detail="unsupported execution_preference")
        now = utc_now_text()
        policy = UserRuntimePolicy(
            principal_id=principal_id,
            policy_id=current.policy_id if current else uuid4().hex,
            revision=current.revision + 1 if current else 1,
            execution_preference=execution_preference,
            approval_mode=approval_mode,
            model_profile_id=payload.model_profile_id if "model_profile_id" in payload.model_fields_set else current.model_profile_id if current else None,
            reasoning_intensity=payload.reasoning_intensity if "reasoning_intensity" in payload.model_fields_set else current.reasoning_intensity if current else None,
            request_timeout_seconds=payload.request_timeout_seconds if payload.request_timeout_seconds is not None else current.request_timeout_seconds if current else 300,
            browser_operation_timeout_ms=payload.browser_operation_timeout_ms if payload.browser_operation_timeout_ms is not None else current.browser_operation_timeout_ms if current else 30_000,
            browser_navigation_timeout_ms=payload.browser_navigation_timeout_ms if payload.browser_navigation_timeout_ms is not None else current.browser_navigation_timeout_ms if current else 45_000,
            max_model_attempts=(payload.max_retries + 1) if payload.max_retries is not None else current.max_model_attempts if current else 6,
            max_parallel_temporary_agents=payload.max_parallel_sub_agents if payload.max_parallel_sub_agents is not None else current.max_parallel_temporary_agents if current else 5,
            memory_auto_write_enabled=payload.memory_auto_write_enabled if payload.memory_auto_write_enabled is not None else current.memory_auto_write_enabled if current else True,
            memory_write_interval_turns=payload.memory_write_interval_turns if payload.memory_write_interval_turns is not None else current.memory_write_interval_turns if current else 3,
            memory_agent_write_enabled=payload.memory_agent_write_enabled if payload.memory_agent_write_enabled is not None else current.memory_agent_write_enabled if current else True,
            memory_max_injected_items=payload.memory_max_injected_items if payload.memory_max_injected_items is not None else current.memory_max_injected_items if current else 8,
            memory_max_injected_tokens=payload.memory_max_injected_tokens if payload.memory_max_injected_tokens is not None else current.memory_max_injected_tokens if current else 1200,
            max_temporary_delegation_depth=current.max_temporary_delegation_depth if current else 0,
            delegation_grant_ttl_seconds=current.delegation_grant_ttl_seconds if current else 900,
            timezone=timezone,
            updated_at=now,
        )
        saved = (
            backend.application.stores.runtime_policies.create(policy, created_at=now)
            if current is None
            else backend.application.stores.runtime_policies.replace(policy, expected_revision=current.revision)
        )
        return _runtime_preferences_view(saved)

    @router.patch("/api/background-tasks/settings")
    async def update_background_task_settings(
        request: Request,
        payload: BackgroundTaskSettingsWrite,
    ) -> dict[str, Any]:
        principal_id = _principal(request)
        timezone = _required_text(request.headers.get("X-Combo-Timezone"), "timezone header")
        current = _policy_or_none(backend, principal_id)
        if current is None:
            policy = UserRuntimePolicy(
                principal_id=principal_id,
                policy_id=uuid4().hex,
                model_profile_id=None,
                max_parallel_temporary_agents=max(1, payload.max_parallel_sub_agents),
                timezone=timezone,
            )
            saved = backend.application.stores.runtime_policies.create(policy, created_at=policy.updated_at)
        else:
            if payload.revision is not None and payload.revision != current.revision:
                raise HTTPException(status_code=409, detail="runtime policy revision conflict")
            saved = backend.application.stores.runtime_policies.replace(
                current.model_copy(update={
                    "revision": current.revision + 1,
                    "max_parallel_temporary_agents": max(1, payload.max_parallel_sub_agents),
                    "updated_at": utc_now_text(),
                }),
                expected_revision=current.revision,
            )
        return {
            "settings": {
                "max_parallel_sub_agents": saved.max_parallel_temporary_agents,
                "revision": saved.revision,
                "updated_at": saved.updated_at,
            }
        }

    @router.get("/api/background-tasks")
    async def background_tasks(request: Request, session_id: str | None = None) -> dict[str, Any]:
        principal_id = _principal(request)
        return {"tasks": _delegated_task_views(backend, principal_id, session_id)}

    @router.get("/api/background-tasks/{task_id}")
    async def background_task(request: Request, task_id: str) -> dict[str, Any]:
        principal_id = _principal(request)
        return {"task": _delegated_task_view(backend, principal_id, task_id)}

    @router.get("/api/background-tasks/{task_id}/events")
    async def background_task_events(
        request: Request,
        task_id: str,
        after: int = 0,
    ) -> dict[str, Any]:
        principal_id = _principal(request)
        task = _delegated_task_view(backend, principal_id, task_id)
        events = _delegated_task_event_views(backend, principal_id, task_id)
        return {"events": [event for event in events if int(event["seq"]) > max(0, after)]}

    @router.post("/api/background-tasks/{task_id}/cancel")
    async def cancel_background_task(
        request: Request,
        task_id: str,
        payload: BackgroundTaskCancelWrite,
    ) -> dict[str, Any]:
        principal_id = _principal(request)
        task = _delegated_task_view(backend, principal_id, task_id)
        if task["status"] not in {"succeeded", "failed", "cancelled"}:
            _enqueue_runtime_control(
                backend,
                principal_id=principal_id,
                session_id=str(task["session_id"]),
                payload={
                    "kind": "cancel_runtime_request",
                    "runtime_instance_id": str(task["child_runtime_instance_id"]),
                    "request_id": str(task["request_id"]),
                    "reason": str(payload.reason or "user_cancelled"),
                },
            )
        return {"task": _delegated_task_view(backend, principal_id, task_id)}

    @router.delete("/api/background-tasks/{task_id}")
    async def delete_background_task(request: Request, task_id: str) -> dict[str, Any]:
        principal_id = _principal(request)
        task = _delegated_task_view(backend, principal_id, task_id)
        if task["status"] not in {"succeeded", "failed", "cancelled"}:
            raise HTTPException(status_code=409, detail="active background task cannot be deleted")
        with backend.application.database.transaction() as connection:
            connection.execute(
                "delete from delegated_task_notifications where task_id = ? and principal_id = ?",
                (task_id, principal_id),
            )
            connection.execute(
                "delete from delegated_task_events where task_id = ?",
                (task_id,),
            )
            connection.execute(
                "delete from delegated_task_revisions where task_id = ? and principal_id = ?",
                (task_id, principal_id),
            )
            connection.execute(
                "delete from delegation_grants where task_id = ? and principal_id = ?",
                (task_id, principal_id),
            )
        return {"task": task, "deleted": True}

    @router.post("/api/background-tasks/{task_id}/interactions/{interaction_id}/resolve")
    async def resolve_background_task_interaction(
        request: Request,
        task_id: str,
        interaction_id: str,
        body: BackgroundTaskInteractionWrite,
    ) -> dict[str, Any]:
        principal_id = _principal(request)
        task = _delegated_task_view(backend, principal_id, task_id)
        interaction = task.get("pending_interaction")
        if not isinstance(interaction, dict) or interaction.get("interaction_id") != interaction_id:
            raise HTTPException(status_code=409, detail="background task interaction is no longer pending")
        response = str(
            body.payload.get("answer")
            or body.payload.get("input_text")
            or body.payload.get("revision_guidance")
            or ""
        ).strip()
        decision = "answer" if body.action == "continue" else body.action
        _enqueue_runtime_control(
            backend,
            principal_id=principal_id,
            session_id=str(task["session_id"]),
            payload={
                "kind": "resume_interrupt",
                "runtime_instance_id": str(task["child_runtime_instance_id"]),
                "request_id": str(task["request_id"]),
                "interrupt_id": interaction_id,
                "decision": decision,
                **({"response": response} if decision in {"answer", "revise"} else {}),
            },
        )
        return {"task": task}

    @router.get("/api/storage/conversations")
    async def conversation_storage(request: Request) -> dict[str, int]:
        principal_id = _principal(request)
        sessions = _session_views(backend, principal_id)
        roots = {
            backend.application.stores.conversations.require_workspace(item["workspace_id"]).managed_path
            for item in sessions
            if item.get("workspace_id")
        }
        bytes_used = sum(_directory_size(Path(root)) for root in roots if root)
        return {
            "bytes_used": bytes_used,
            "file_count": sum(_directory_file_count(Path(root)) for root in roots if root),
            "agent_session_count": len(sessions),
            "background_task_session_count": 0,
            "session_count": len(sessions),
        }

    @router.post("/api/storage/conversations/clear")
    async def clear_conversation_storage(request: Request) -> dict[str, Any]:
        principal_id = _principal(request)
        payload = await request.json()
        if payload.get("confirmed") is not True:
            raise HTTPException(status_code=422, detail="conversation clear requires confirmation")
        before = await conversation_storage(request)
        try:
            result = await backend.conversation_lifecycle.delete_all(principal_id=principal_id)
        except TimeoutError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        after = await conversation_storage(request)
        return {
            "cleared": True,
            "before": before,
            "after": after,
            "released_bytes": result.released_bytes,
            "deleted_file_count": result.deleted_file_count,
            "deleted_session_ids": list(result.session_ids),
        }

    @router.get("/api/workspace/projects")
    async def workspace_projects(request: Request) -> dict[str, Any]:
        principal_id = _principal(request)
        return {"workspaces": _workspace_projects(backend, principal_id)}

    @router.post("/api/workspace/projects")
    async def create_workspace_project(
        request: Request,
        payload: WorkspaceCreateRequest,
    ) -> dict[str, Any]:
        principal_id = _principal(request)
        workspace_id = uuid4().hex
        title = str(payload.title or "新工作区").strip() or "新工作区"
        if payload.root_kind == "linked":
            source_path = Path(str(payload.workdir_root or "")).expanduser().resolve()
            if not source_path.is_dir():
                raise HTTPException(status_code=422, detail="linked workspace directory does not exist")
            backend.application.stores.conversations.create_linked_workspace(
                workspace_id=workspace_id,
                principal_id=principal_id,
                source_path=str(source_path),
                title=title,
                mode=payload.mode,
            )
            workspace = backend.application.stores.conversations.require_workspace(workspace_id)
            return {"workspace": _workspace_project_view(backend, workspace)}
        workspace_path = Path(backend.config.workspace_root) / workspace_id
        workspace_path.mkdir(parents=True, exist_ok=False)
        try:
            backend.application.stores.conversations.create_managed_workspace(
                workspace_id=workspace_id,
                principal_id=principal_id,
                managed_path=str(workspace_path),
                title=title,
                mode=payload.mode,
            )
        except Exception:
            workspace_path.rmdir()
            raise
        workspace = backend.application.stores.conversations.require_workspace(workspace_id)
        return {"workspace": _workspace_project_view(backend, workspace)}

    @router.patch("/api/workspace/projects/{workspace_id}")
    async def update_workspace_project(
        workspace_id: str,
        request: Request,
        payload: WorkspaceUpdateRequest,
    ) -> dict[str, Any]:
        if not payload.model_fields_set:
            raise HTTPException(status_code=422, detail="workspace update must include a field")
        try:
            workspace = backend.application.stores.conversations.update_workspace(
                workspace_id=workspace_id,
                principal_id=_principal(request),
                title=payload.title if "title" in payload.model_fields_set else None,
                mode=payload.mode if "mode" in payload.model_fields_set else None,
                archived=payload.archived if "archived" in payload.model_fields_set else None,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"workspace": _workspace_project_view(backend, workspace)}

    @router.get("/api/workspace/directory-roots")
    async def workspace_directory_roots(request: Request) -> dict[str, Any]:
        _principal(request)
        try:
            return {"roots": WorkspaceDirectoryBrowser().root_views()}
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.get("/api/workspace/directories")
    async def workspace_directories(request: Request, path: str) -> dict[str, Any]:
        _principal(request)
        try:
            return WorkspaceDirectoryBrowser().list_directories(path)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/api/workspace/select-directory")
    async def select_workspace_directory(
        request: Request,
        payload: DirectorySelectionRequest,
    ) -> dict[str, str | None]:
        client_host = request.client.host if request.client else ""
        try:
            is_loopback = ip_address(client_host).is_loopback
        except ValueError:
            is_loopback = False
        if not is_loopback:
            raise HTTPException(status_code=403, detail="native directory selection is available only from the local host")
        try:
            selected = NativeDirectoryPicker().select(payload.initial_path)
        except NativeDirectoryPickerUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"path": str(selected) if selected else None}

    @router.get("/api/workspace/roots")
    async def workspace_roots(
        request: Request,
        package_session_id: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        root = _workspace_root(
            backend,
            principal_id=_principal(request),
            session_id=package_session_id,
            workspace_id=workspace_id,
        )
        return {"event": _event("workspace_roots_listed", {"roots": [{
            "scope": "workdir",
            "name": root.name or "工作区",
            "path": str(root),
            "exists": root.is_dir(),
        }]})}

    @router.get("/api/workspace/entries")
    async def workspace_entries(
        request: Request,
        path: str = "",
        package_session_id: str | None = None,
        workspace_id: str | None = None,
        scope: str = "workdir",
    ) -> dict[str, Any]:
        root = _workspace_root(
            backend,
            principal_id=_principal(request),
            session_id=package_session_id,
            workspace_id=workspace_id,
        )
        directory = _workspace_path(root, path)
        if not directory.is_dir():
            raise HTTPException(status_code=404, detail="workspace directory not found")
        entries = [_workspace_entry(root, child, scope) for child in directory.iterdir()]
        entries.sort(key=lambda item: (item["kind"] != "directory", item["name"].casefold()))
        return {"event": _event("workspace_entries_listed", {"entries": entries})}

    @router.get("/api/workspace/file")
    async def workspace_file(
        request: Request,
        path: str,
        package_session_id: str | None = None,
        workspace_id: str | None = None,
        scope: str = "workdir",
        max_chars: int = 1_000_000,
    ) -> dict[str, Any]:
        root = _workspace_root(
            backend,
            principal_id=_principal(request),
            session_id=package_session_id,
            workspace_id=workspace_id,
        )
        target = _workspace_path(root, path)
        if not target.is_file():
            raise HTTPException(status_code=404, detail="workspace file not found")
        raw = target.read_bytes()
        mime_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            payload = {
                "name": target.name,
                "scope": scope,
                "path": path,
                "kind": "binary",
                "mime_type": mime_type,
                "encoding": "base64",
                "size_bytes": len(raw),
                "content_base64": base64.b64encode(raw).decode("ascii"),
                "truncated": False,
            }
        else:
            payload = {
                "name": target.name,
                "scope": scope,
                "path": path,
                "kind": "text",
                "mime_type": mime_type,
                "encoding": "utf-8",
                "size_bytes": len(raw),
                "content": content[:max_chars],
                "truncated": len(content) > max_chars,
            }
        return {"event": _event("workspace_file_read", payload)}

    @router.get("/api/workspace/raw")
    async def workspace_raw(
        request: Request,
        path: str,
        package_session_id: str | None = None,
        workspace_id: str | None = None,
    ) -> FileResponse:
        root = _workspace_root(
            backend,
            principal_id=_principal(request),
            session_id=package_session_id,
            workspace_id=workspace_id,
        )
        target = _workspace_path(root, path)
        if not target.is_file():
            raise HTTPException(status_code=404, detail="workspace file not found")
        return FileResponse(target)

    @router.get("/api/workspace/native-path")
    async def workspace_native_path(
        request: Request,
        path: str = "",
        package_session_id: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, str]:
        root = _workspace_root(
            backend,
            principal_id=_principal(request),
            session_id=package_session_id,
            workspace_id=workspace_id,
        )
        target = _workspace_path(root, path)
        if not target.exists():
            raise HTTPException(status_code=404, detail="workspace entry not found")
        return {
            "native_path": str(target),
            "kind": "directory" if target.is_dir() else "file",
        }

    @router.delete("/api/workspace/file")
    async def delete_workspace_file(
        request: Request,
        path: str,
        package_session_id: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        root = _workspace_root(
            backend,
            principal_id=_principal(request),
            session_id=package_session_id,
            workspace_id=workspace_id,
        )
        target = _workspace_path(root, path)
        if not target.is_file():
            raise HTTPException(status_code=404, detail="workspace file not found")
        target.unlink()
        return {"deleted": True, "path": target.relative_to(root).as_posix()}

    @router.get("/api/memory/query")
    async def memory_query(
        request: Request,
        query: str = "",
        workspace_id: str | None = None,
        limit: int = 8,
    ) -> dict[str, Any]:
        principal_id = _principal(request)
        resolved_workspace_id = _memory_workspace_id(backend, principal_id, workspace_id)
        store = backend.application.stores.memories
        if query.strip():
            results = store.search(
                principal_id=principal_id,
                workspace_id=resolved_workspace_id,
                query=query,
                limit=max(1, limit),
            )
        else:
            from combo.dynamic_runtime.memory_store import MemorySearchResult
            results = tuple(
                MemorySearchResult(revision=item, score=1.0)
                for item in store.list_active(
                    principal_id=principal_id,
                    workspace_id=resolved_workspace_id,
                    limit=max(1, limit),
                )
            )
        items = [
            {
                "memory_id": item.revision.memory_id,
                "source_scope": item.revision.scope,
                "memory_type": item.revision.kind,
                "kind": item.revision.kind,
                "content": item.revision.content,
                "score": item.score,
                "metadata": {"confidence": item.revision.confidence},
                "namespace": [item.revision.scope, item.revision.workspace_id or principal_id],
                "updated_at": item.revision.created_at,
            }
            for item in results
        ]
        return {
            "package_id": None,
            "namespace": ["combined", resolved_workspace_id],
            "namespaces": [],
            "query": query,
            "items": items,
            "token_estimate": sum(max(1, len(item["content"]) // 4) for item in items),
            "report": {},
        }

    @router.delete("/api/memory/items")
    async def delete_memory(request: Request, payload: MemoryDeleteRequest) -> dict[str, Any]:
        principal_id = _principal(request)
        deleted = backend.application.stores.memories.delete_as_owner(
            memory_id=payload.memory_id,
            principal_id=principal_id,
        )
        return {
            "deleted": True,
            "memory_id": deleted.memory_id,
            "package_id": None,
            "namespace": [deleted.scope, deleted.workspace_id or principal_id],
        }

    @router.get("/api/knowledge/sources")
    async def knowledge_sources(request: Request) -> dict[str, Any]:
        _principal(request)
        return {"event": _event("knowledge_sources_listed", {"sources": backend.application.stores.knowledge.sources()})}

    @router.get("/api/knowledge/settings")
    async def knowledge_retrieval_settings(request: Request) -> dict[str, Any]:
        _principal(request)
        return backend.application.stores.knowledge.retrieval_settings().model_dump(mode="json")

    @router.patch("/api/knowledge/settings")
    async def update_knowledge_retrieval_settings(
        request: Request,
        payload: KnowledgeRetrievalSettingsWrite,
    ) -> dict[str, Any]:
        _principal(request)
        settings = KnowledgeRetrievalSettings.model_validate(
            payload.model_dump(exclude={"expected_revision"})
        )
        try:
            saved = backend.application.stores.knowledge.save_retrieval_settings(
                settings,
                expected_revision=payload.expected_revision,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail="knowledge retrieval settings revision conflict") from exc
        return saved.model_dump(mode="json")

    @router.get("/api/knowledge/search")
    async def search_knowledge(
        request: Request,
        query: str,
        source_id: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        _principal(request)
        results = backend.application.stores.knowledge.search(
            query=query,
            source_id=source_id,
            limit=limit,
        )
        return {"event": _event("knowledge_search_completed", {"query": query, "results": results})}

    @router.post("/api/knowledge/sources")
    async def create_knowledge_source(request: Request) -> dict[str, Any]:
        _principal(request)
        payload = await request.json()
        source = _knowledge_source_payload(payload.get("source"))
        content = str(source.get("content") or "")
        documents = [{
            "title": str(source.get("display_name") or "知识文档"),
            "mime_type": "text/plain",
            "content": content,
        }] if content else []
        created = backend.application.stores.knowledge.create_source(source, documents)
        return {"event": _event("knowledge_source_registered", {"source": created, "sources": backend.application.stores.knowledge.sources()})}

    @router.post("/api/knowledge/sources/upload")
    async def upload_knowledge_source(request: Request) -> dict[str, Any]:
        _principal(request)
        form = await request.form()
        try:
            source = _knowledge_source_payload(json.loads(str(form.get("source") or "{}")))
        except (TypeError, ValueError, ValidationError) as exc:
            raise HTTPException(status_code=422, detail="invalid knowledge source metadata") from exc
        documents: list[dict[str, str]] = []
        for upload in form.getlist("files"):
            raw = await upload.read()
            try:
                content = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise HTTPException(
                    status_code=422,
                    detail=f"knowledge parser is unavailable for binary file: {upload.filename}",
                ) from exc
            documents.append({
                "title": str(upload.filename or source.get("display_name") or "document"),
                "mime_type": str(upload.content_type or "text/plain"),
                "content": content,
            })
        if not documents:
            raise HTTPException(status_code=422, detail="knowledge upload requires at least one file")
        created = backend.application.stores.knowledge.create_source(source, documents)
        return {"event": _event("knowledge_source_registered", {"source": created, "sources": backend.application.stores.knowledge.sources()})}

    @router.get("/api/knowledge/documents")
    async def knowledge_documents(request: Request, source_id: str) -> dict[str, Any]:
        _principal(request)
        documents = backend.application.stores.knowledge.documents(source_id)
        return {"event": _event("knowledge_documents_listed", {"documents": [
            {
                "document_id": item.document_id,
                "source_id": item.source_id,
                "title": item.title,
                "document_type": item.mime_type,
            }
            for item in documents
        ]})}

    @router.get("/api/knowledge/document")
    async def knowledge_document(request: Request, document_id: str) -> dict[str, Any]:
        _principal(request)
        try:
            item = backend.application.stores.knowledge.require_document(document_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="knowledge document not found") from exc
        return {"event": _event("knowledge_document_read", {"document": {
            "document_id": item.document_id,
            "source_id": item.source_id,
            "title": item.title,
            "mime_type": item.mime_type,
            "content": item.content,
            "truncated": False,
        }})}

    @router.delete("/api/knowledge/sources/{source_id}")
    async def delete_knowledge_source(request: Request, source_id: str) -> dict[str, Any]:
        _principal(request)
        try:
            backend.application.stores.knowledge.delete_source(source_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="knowledge source not found") from exc
        return {"event": _event("knowledge_source_removed", {"source_id": source_id, "sources": backend.application.stores.knowledge.sources()})}

    @router.post("/api/knowledge/sources/{source_id}/reindex")
    async def reindex_knowledge_source(request: Request, source_id: str) -> dict[str, Any]:
        _principal(request)
        if not any(item.get("source_id") == source_id for item in backend.application.stores.knowledge.sources()):
            raise HTTPException(status_code=404, detail="knowledge source not found")
        backend.application.stores.knowledge.refresh_index(force=True)
        return {"event": _event("knowledge_source_reindex_requested", {"source_id": source_id, "sources": backend.application.stores.knowledge.sources()})}

    @router.get("/api/scheduler/options")
    async def scheduler_options(request: Request) -> dict[str, Any]:
        _principal(request)
        tools = [
            {
                "id": item["capability_id"],
                "name": item["display_name"],
                "description": item["description"],
                "risk_level": item["details"].get("risk_level"),
            }
            for item in backend.capability_pool_snapshot()["capabilities"]
            if item["kind"] in {"tool", "mcp_tool"}
        ]
        return {"event": _event("scheduler_options_listed", {"tools": tools})}

    @router.get("/api/scheduler/jobs")
    async def scheduler_jobs(request: Request) -> dict[str, Any]:
        principal_id = _principal(request)
        workspace_ids = tuple(item["workspace_id"] for item in _workspace_projects(backend, principal_id))
        return {"event": _event("scheduler_jobs_listed", {"jobs": backend.application.stores.scheduler.jobs(workspace_ids)})}

    @router.post("/api/scheduler/jobs")
    async def create_scheduler_job(request: Request) -> dict[str, Any]:
        principal_id = _principal(request)
        payload = await request.json()
        job = dict(payload.get("job") or {})
        workspaces = _workspace_projects(backend, principal_id)
        workspace_id = str(job.get("workspace_id") or "").strip()
        if not workspace_id and len(workspaces) == 1:
            workspace_id = str(workspaces[0]["workspace_id"])
        if not any(item["workspace_id"] == workspace_id for item in workspaces):
            raise HTTPException(status_code=422, detail="scheduler job requires an owned workspace")
        target = job.get("target") if isinstance(job.get("target"), dict) else None
        if not target or target.get("target_type") not in {"graph_run", "script_run"}:
            raise HTTPException(status_code=422, detail="scheduler target must be an agent or script task")
        created = backend.application.stores.scheduler.create_job({
            **job,
            "workspace_id": workspace_id,
            "timezone": str(job.get("timezone") or request.headers.get("X-Combo-Timezone") or "UTC"),
        })
        return {"event": _event("scheduler_job_created", {"job": created})}

    @router.post("/api/scheduler/jobs/{job_id}/pause")
    async def pause_scheduler_job(request: Request, job_id: str) -> dict[str, Any]:
        principal_id = _principal(request)
        _owned_scheduler_job(backend, principal_id, job_id)
        backend.application.stores.scheduler.set_status(job_id, "paused")
        return await scheduler_jobs(request)

    @router.post("/api/scheduler/jobs/{job_id}/resume")
    async def resume_scheduler_job(request: Request, job_id: str) -> dict[str, Any]:
        principal_id = _principal(request)
        _owned_scheduler_job(backend, principal_id, job_id)
        backend.application.stores.scheduler.set_status(job_id, "enabled")
        return await scheduler_jobs(request)

    @router.delete("/api/scheduler/jobs/{job_id}")
    async def delete_scheduler_job(request: Request, job_id: str) -> dict[str, Any]:
        principal_id = _principal(request)
        _owned_scheduler_job(backend, principal_id, job_id)
        backend.application.stores.scheduler.set_status(job_id, "deleted")
        return {"event": _event("scheduler_job_deleted", {"job_id": job_id})}

    @router.get("/api/scheduler/runs")
    async def scheduler_runs(
        request: Request,
        job_id: str | None = None,
        workspace_id: str | None = None,
        source_session_id: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        principal_id = _principal(request)
        return {"event": _event("scheduler_runs_listed", {
            "runs": backend.application.stores.scheduler.runs_for_principal(
                principal_id,
                job_id=job_id,
                workspace_id=workspace_id,
                source_session_id=source_session_id,
                limit=limit,
            ),
            "job_id": job_id,
            "workspace_id": workspace_id,
            "source_session_id": source_session_id,
            "limit": limit,
        })}

    @router.get("/api/scheduler/runs/{run_id}/events")
    async def scheduler_run_events(request: Request, run_id: str, after: int = 0) -> dict[str, Any]:
        principal_id = _principal(request)
        run = backend.application.stores.scheduler.require_run(run_id)
        job = backend.application.stores.scheduler.require_job(str(run["job_id"]))
        if str(job.get("principal_id") or "") != principal_id:
            raise HTTPException(status_code=404, detail="scheduler run not found")
        return {"events": backend.application.stores.scheduler.run_events(run_id, after=after)}

    @router.post("/api/scheduler/runs/{run_id}/cancel")
    async def cancel_scheduler_run(request: Request, run_id: str) -> dict[str, Any]:
        principal_id = _principal(request)
        run = backend.application.stores.scheduler.require_run(run_id)
        job = backend.application.stores.scheduler.require_job(str(run["job_id"]))
        if str(job.get("principal_id") or "") != principal_id:
            raise HTTPException(status_code=404, detail="scheduler run not found")
        return {"run": await backend.scheduler_service.cancel(run_id)}

    @router.post("/api/scheduler/runs/{run_id}/interactions/{interaction_id}")
    async def resolve_scheduler_run_interaction(
        request: Request,
        run_id: str,
        interaction_id: str,
    ) -> dict[str, Any]:
        principal_id = _principal(request)
        body = await request.json()
        run = backend.application.stores.scheduler.require_run(run_id)
        job = backend.application.stores.scheduler.require_job(str(run["job_id"]))
        if str(job.get("principal_id") or "") != principal_id:
            raise HTTPException(status_code=404, detail="scheduler run not found")
        runtime_instance_id = str(run.get("runtime_instance_id") or "").strip()
        request_id = str(run.get("request_id") or "").strip()
        session_id = str(run.get("session_id") or "").strip()
        if not runtime_instance_id or not request_id or not session_id:
            raise HTTPException(status_code=409, detail="scheduler interaction identity is unavailable")
        decision = str(body.get("decision") or "").strip()
        if decision not in {"approve", "reject", "trust", "answer", "revise"}:
            raise HTTPException(status_code=422, detail="unsupported scheduler interaction decision")
        response = str(body.get("response") or "").strip()
        _enqueue_runtime_control(
            backend,
            principal_id=principal_id,
            session_id=session_id,
            payload={
                "kind": "resume_interrupt",
                "runtime_instance_id": runtime_instance_id,
                "request_id": request_id,
                "interrupt_id": interaction_id,
                "decision": decision,
                **({"response": response} if decision in {"answer", "revise"} else {}),
            },
        )
        updated = backend.application.stores.scheduler.update_run(run_id, status="running")
        return {"run": updated}

    @router.post("/api/scheduler/jobs/{job_id}/run")
    async def run_scheduler_job(
        request: Request,
        job_id: str,
        x_combo_client: str = Header(alias="X-Combo-Client"),
        x_combo_timezone: str = Header(alias="X-Combo-Timezone"),
    ) -> dict[str, Any]:
        principal_id = _principal(request)
        try:
            job = _owned_scheduler_job(backend, principal_id, job_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="scheduler job not found") from exc
        if job["status"] != "enabled":
            raise HTTPException(status_code=409, detail="scheduler job is paused")
        workspace_id = str(job.get("workspace_id") or "")
        workspace = backend.application.stores.conversations.require_workspace(workspace_id)
        if workspace.principal_id != principal_id:
            raise HTTPException(status_code=404, detail="scheduler workspace not found")
        del x_combo_client, x_combo_timezone
        run = backend.scheduler_service.launch(job_id, trigger_source="manual")
        return {"accepted": True, "command": {"type": "scheduler_run", "request_id": run["run_id"]}}

    return router


def _ensure_conversation(
    backend: Any,
    *,
    principal_id: str,
    requested_session_id: Any,
    requested_workspace_id: Any,
) -> str:
    session_id = str(requested_session_id or "").strip()
    if session_id:
        identity = backend.application.stores.conversations.require_identity(session_id)
        if identity.principal_id != principal_id:
            raise HTTPException(status_code=404, detail="conversation not found")
        return session_id
    session_id = uuid4().hex
    workspace_id = str(requested_workspace_id or "").strip()
    if workspace_id:
        workspace = backend.application.stores.conversations.require_workspace(workspace_id)
        if workspace.principal_id != principal_id or workspace.status != "active":
            raise HTTPException(status_code=404, detail="workspace not found")
        backend.application.stores.conversations.create_conversation(
            session_id=session_id,
            workspace_id=workspace_id,
            principal_id=principal_id,
            title="新对话",
        )
        return session_id
    workspace_id = uuid4().hex
    workspace_path = Path(backend.config.workspace_root) / workspace_id
    workspace_path.mkdir(parents=True, exist_ok=False)
    backend.application.stores.conversations.create_managed_conversation(
        session_id=session_id,
        workspace_id=workspace_id,
        principal_id=principal_id,
        managed_path=str(workspace_path),
        title="新对话",
    )
    return session_id


def _synchronize_policy(
    backend: Any,
    *,
    principal_id: str,
    timezone: str,
    command_payload: dict[str, Any],
) -> UserRuntimePolicy:
    user_config = command_payload.get("user_config")
    config = dict(user_config) if isinstance(user_config, dict) else {}
    overrides = config.get("model_profile_overrides")
    profiles = dict(overrides) if isinstance(overrides, dict) else {}
    profile_id = str(profiles.get("main") or "").strip()
    store = backend.application.stores.runtime_policies
    try:
        current = store.require_for_principal(principal_id)
    except LookupError:
        current = None
    if not profile_id and current is None:
        raise HTTPException(status_code=409, detail="runtime main model is not configured")
    request_config = command_payload.get("runtime_request")
    runtime_request = dict(request_config) if isinstance(request_config, dict) else {}
    requested_approval_mode = str(config.get("approval_mode") or "").strip()
    if requested_approval_mode and requested_approval_mode not in {"auto", "ask", "always_approval"}:
        raise HTTPException(status_code=422, detail="unsupported approval_mode")
    now = utc_now_text()
    requested_execution_preference = str(command_payload.get("execution_preference") or "").strip()
    if requested_execution_preference and requested_execution_preference not in {"react", "plan_and_execute"}:
        raise HTTPException(status_code=422, detail="unsupported execution_preference")
    policy = UserRuntimePolicy(
        principal_id=principal_id,
        policy_id=current.policy_id if current is not None else uuid4().hex,
        revision=current.revision + 1 if current is not None else 1,
        execution_preference=(requested_execution_preference or (current.execution_preference if current is not None else "react")),
        approval_mode=(
            requested_approval_mode
            or (current.approval_mode if current is not None else "ask")
        ),
        model_profile_id=profile_id or current.model_profile_id,
        reasoning_intensity=(
            int(config["reasoning_intensity"])
            if config.get("reasoning_intensity") is not None
            else current.reasoning_intensity if current is not None else None
        ),
        request_timeout_seconds=int(runtime_request.get("timeout_seconds") or (current.request_timeout_seconds if current else 300)),
        browser_operation_timeout_ms=current.browser_operation_timeout_ms if current else 30_000,
        browser_navigation_timeout_ms=current.browser_navigation_timeout_ms if current else 45_000,
        max_model_attempts=(
            int(runtime_request["max_retries"]) + 1
            if runtime_request.get("max_retries") is not None
            else current.max_model_attempts if current else 2
        ),
        max_parallel_temporary_agents=int(config.get("max_parallel_sub_agents") or (current.max_parallel_temporary_agents if current else 4)),
        memory_auto_write_enabled=current.memory_auto_write_enabled if current else True,
        memory_write_interval_turns=current.memory_write_interval_turns if current else 3,
        memory_agent_write_enabled=current.memory_agent_write_enabled if current else True,
        memory_max_injected_items=current.memory_max_injected_items if current else 8,
        memory_max_injected_tokens=current.memory_max_injected_tokens if current else 1200,
        max_temporary_delegation_depth=current.max_temporary_delegation_depth if current else 0,
        delegation_grant_ttl_seconds=current.delegation_grant_ttl_seconds if current else 900,
        timezone=timezone,
        updated_at=now,
    )
    if current is None:
        store.create(policy, created_at=now)
    elif policy.model_dump(exclude={"revision", "updated_at"}) != current.model_dump(exclude={"revision", "updated_at"}):
        store.replace(policy, expected_revision=current.revision)
    else:
        policy = current
    return policy


def _active_runtime_or_none(backend: Any, principal_id: str, command: dict[str, Any]):
    session_id = str(command.get("session_id") or "").strip()
    payload = dict(command.get("payload") or {})
    runtime_instance_id = str(payload.get("runtime_instance_id") or "").strip()
    target_request_id = str(payload.get("target_request_id") or "").strip()
    with backend.application.database.connection(query_only=True) as connection:
        row = connection.execute(
            """
            select payload_json from runtime_instances
            where json_extract(payload_json, '$.request.principal_id') = ?
              and (? = '' or json_extract(payload_json, '$.request.session_id') = ?)
              and (? = '' or runtime_instance_id = ?)
              and (? = '' or runtime_instance_id in (
                select json_extract(receipt_json, '$.runtime_instance_id') from command_inbox where command_id = ?
              ))
              and status in ('running','waiting_approval','waiting_external')
            order by updated_at desc limit 1
            """,
            (
                principal_id,
                session_id,
                session_id,
                runtime_instance_id,
                runtime_instance_id,
                target_request_id,
                target_request_id,
            ),
        ).fetchone()
    if row is None:
        return None
    from combo.runtime_protocol import RuntimeInstance
    return RuntimeInstance.model_validate_json(str(row["payload_json"]))


def _runtime_cancel_target_or_none(backend: Any, principal_id: str, command: dict[str, Any]):
    current = _active_runtime_or_none(backend, principal_id, command)
    if current is not None:
        return current
    session_id = str(command.get("session_id") or "").strip()
    payload = dict(command.get("payload") or {})
    runtime_instance_id = str(payload.get("runtime_instance_id") or "").strip()
    target_request_id = str(payload.get("target_request_id") or "").strip()
    if not runtime_instance_id and not target_request_id:
        return None
    with backend.application.database.connection(query_only=True) as connection:
        row = connection.execute(
            """
            select payload_json from runtime_instances
            where json_extract(payload_json, '$.request.principal_id') = ?
              and (? = '' or json_extract(payload_json, '$.request.session_id') = ?)
              and (? = '' or runtime_instance_id = ?)
              and (? = '' or runtime_instance_id in (
                select json_extract(receipt_json, '$.runtime_instance_id') from command_inbox where command_id = ?
              ))
            order by updated_at desc limit 1
            """,
            (
                principal_id,
                session_id,
                session_id,
                runtime_instance_id,
                runtime_instance_id,
                target_request_id,
                target_request_id,
            ),
        ).fetchone()
    if row is None:
        return None
    from combo.runtime_protocol import RuntimeInstance
    return RuntimeInstance.model_validate_json(str(row["payload_json"]))


def _active_runtime(backend: Any, principal_id: str, command: dict[str, Any]):
    current = _active_runtime_or_none(backend, principal_id, command)
    if current is None:
        raise HTTPException(status_code=409, detail="no active runtime request")
    return current


def _active_pre_runtime_command(backend: Any, principal_id: str, command: dict[str, Any]):
    session_id = str(command.get("session_id") or "").strip()
    source = dict(command.get("payload") or {})
    target_command_id = str(source.get("target_request_id") or "").strip()
    with backend.application.database.connection(query_only=True) as connection:
        row = connection.execute(
            """
            select receipt_json from command_inbox
            where principal_id = ? and command_kind = 'send_message' and status in ('queued', 'running')
              and json_extract(receipt_json, '$.runtime_instance_id') is null
              and (? = '' or session_id = ?)
              and (? = '' or command_id = ?)
            order by updated_at desc limit 1
            """,
            (
                principal_id,
                session_id,
                session_id,
                target_command_id,
                target_command_id,
            ),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=409, detail="no active runtime request")
    return CommandReceipt.model_validate_json(str(row["receipt_json"]))


def _interrupt_id(
    backend: Any,
    runtime_instance_id: str,
    *,
    requested_interrupt_id: str,
) -> str:
    interrupts = backend.application.runtime_service.pending_interrupts(runtime_instance_id)
    if not interrupts:
        raise HTTPException(status_code=409, detail="runtime interrupt payload is unavailable")
    available_ids = {
        interrupt_id
        for item in interrupts
        if (
            interrupt_id := str(
                item.get("interrupt_id") or item.get("id") or ""
            ).strip()
        )
    }
    if not available_ids:
        raise HTTPException(status_code=409, detail="runtime interrupt identity is unavailable")
    if requested_interrupt_id not in available_ids:
        raise HTTPException(status_code=409, detail="runtime interrupt identity no longer matches")
    return requested_interrupt_id


def _session_views(backend: Any, principal_id: str) -> list[dict[str, Any]]:
    summaries = backend.application.stores.conversations.list_for_principal(principal_id)
    views = []
    for item in summaries:
        if item.status != "active":
            continue
        workspace = backend.application.stores.conversations.require_workspace(item.workspace_id)
        first_user_input = _first_user_text(backend, item.session_id)
        display_title = first_user_input if item.title in {"新对话", "新会话"} and first_user_input else item.title
        views.append({
            "session_id": item.session_id,
            "workspace_id": item.workspace_id,
            "workspace": _workspace_project_view(backend, workspace),
            "package_id": SYSTEM_CHAT_PACKAGE_ID,
            "session_kind": "agent_package",
            "visible_in_agent_session_list": True,
            "display_title": display_title,
            "first_user_input": first_user_input,
            "turn_count": _turn_count(backend, item.session_id),
            "created_at": item.created_at,
            "updated_at": item.updated_at,
        })
    return views


def _session_snapshot(backend: Any, principal_id: str, session_id: str) -> dict[str, Any]:
    identity = backend.application.stores.conversations.require_identity(session_id)
    if identity.principal_id != principal_id:
        raise HTTPException(status_code=404, detail="conversation not found")
    messages = backend.application.stores.conversations.messages(session_id)
    grouped: dict[str, list[Any]] = defaultdict(list)
    for message in messages:
        grouped[message.turn_id].append(message)
    with backend.application.database.connection(query_only=True) as connection:
        rows = connection.execute(
            "select payload_json from conversation_turns where session_id = ? order by created_at, rowid",
            (session_id,),
        ).fetchall()
        tool_rows = connection.execute(
            """
            select tool.payload_json
            from tool_calls as tool
            join conversation_turns as turn on turn.turn_id = tool.turn_id
            where turn.session_id = ?
              and tool.runtime_instance_id = turn.active_runtime_instance_id
            order by
              case when json_extract(tool.payload_json, '$.completed_at') is null then 1 else 0 end,
              json_extract(tool.payload_json, '$.completed_at'),
              tool.created_at,
              tool.rowid
            """,
            (session_id,),
        ).fetchall()
    tool_calls_by_turn: dict[str, list[ToolCallRecord]] = defaultdict(list)
    for row in tool_rows:
        record = ToolCallRecord.model_validate_json(str(row["payload_json"]))
        tool_calls_by_turn[record.turn_id].append(record)
    turns = []
    for row in rows:
        from combo.runtime_protocol import ConversationTurn
        turn = ConversationTurn.model_validate_json(str(row["payload_json"]))
        frontend_request_id = turn.source_command_id or _frontend_request_for_runtime(
            backend,
            turn.active_runtime_instance_id,
        )
        tool_activities = [
            _tool_activity_view(backend, record)
            for record in tool_calls_by_turn.get(turn.turn_id, [])
        ]
        persisted_tool_call_ids = {
            tool_call_id
            for message in grouped.get(turn.turn_id, [])
            for part in message.parts
            if (tool_call_id := str(getattr(part, "tool_call_id", "") or "").strip())
        }
        message_views = [
            view
            for message in grouped.get(turn.turn_id, [])
            if (
                view := _message_view(
                    backend,
                    message,
                    request_id=frontend_request_id,
                    turn_status=turn.status,
                )
            ) is not None
        ]
        message_views.extend(
            build_chat_turn_messages(
                index=turn.turn_id,
                created_at=turn.created_at,
                updated_at=turn.updated_at,
                tool_activities=[
                    activity
                    for activity in tool_activities
                    if str(activity.get("toolCallId") or "").strip() not in persisted_tool_call_ids
                ],
            )
        )
        message_views.sort(key=lambda item: str(item.get("timestamp") or ""))
        turns.append(
            {
                "index": turn.task_revision,
                "request_id": frontend_request_id,
                "status": "interrupted" if turn.status in {"waiting_approval", "waiting_external"} else turn.status,
                "created_at": turn.created_at,
                "updated_at": turn.updated_at,
                "messages": message_views,
                "tool_activities": tool_activities,
            }
        )
    workspace = backend.application.stores.conversations.require_workspace(identity.workspace_id)
    workspace_view = _workspace_project_view(backend, workspace)
    current_plan = _session_current_plan(backend, session_id)
    context_window = _session_context_window(backend, session_id)
    return {
        "session_id": session_id,
        "package_id": SYSTEM_CHAT_PACKAGE_ID,
        "workspace_id": identity.workspace_id,
        "workspace": workspace_view,
        "turns": turns,
        "process_events": _process_events(backend, session_id),
        "current_plan": current_plan,
        "context_window": context_window,
        "created_at": turns[0]["created_at"] if turns else utc_now_text(),
        "updated_at": turns[-1]["updated_at"] if turns else utc_now_text(),
    }


def _session_context_window(backend: Any, session_id: str) -> dict[str, Any] | None:
    with backend.application.database.connection(query_only=True) as connection:
        row = connection.execute(
            """
            select payload_json, created_at from runtime_events
            where session_id = ?
              and event_kind = 'runtime_completed'
              and json_type(payload_json, '$.payload.context_window') = 'object'
            order by session_sequence desc limit 1
            """,
            (session_id,),
        ).fetchone()
    if row is not None:
        event = json.loads(str(row["payload_json"]))
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        context_window = payload.get("context_window")
        if isinstance(context_window, dict):
            return {**context_window, "updated_at": str(row["created_at"])}
    return None


def _session_current_plan(backend: Any, session_id: str) -> dict[str, Any] | None:
    with backend.application.database.connection(query_only=True) as connection:
        row = connection.execute(
            """
            select runtime_instance_id, payload_json from runtime_instances
            where session_id = ?
              and json_extract(payload_json, '$.request.runtime_role') = 'main'
            order by created_at desc, rowid desc limit 1
            """,
            (session_id,),
        ).fetchone()
    if row is None:
        return None
    from combo.runtime_protocol import RuntimeInstance
    instance = RuntimeInstance.model_validate_json(str(row["payload_json"]))
    if instance.request.strategy != "plan_and_execute":
        return None
    try:
        plan = backend.application.runtime_service.current_plan(str(row["runtime_instance_id"]))
    except (LookupError, RuntimeError, ValueError):
        return None
    if plan is None:
        return None
    if instance.status == "cancelled" and plan.get("status") == "active":
        plan = {**plan, "status": "cancelled", "current_step_id": None}
    return {
        **plan,
        "runtime_instance_id": instance.runtime_instance_id,
        "request_id": _frontend_request_for_runtime(backend, instance.runtime_instance_id),
    }


def _message_view(
    backend: Any,
    message: Any,
    *,
    request_id: str | None,
    turn_status: str,
) -> dict[str, Any] | None:
    if message.visibility == "internal":
        return _delegated_delivery_message_view(backend, message, request_id=request_id)
    parts = []
    for part in message.parts:
        value = part.model_dump(mode="json")
        kind = str(value.pop("kind", ""))
        parts.append(
            _frontend_message_part(
                part_id=f"{message.message_id}:{len(parts)}",
                kind=kind,
                value=value,
            )
        )
    if not parts:
        return None
    return {
        "id": message.message_id,
        "role": "assistant" if message.role == "tool" else message.role,
        "parts": parts,
        "timestamp": message.created_at,
        "status": "stopped" if message.completion_reason == "user_interrupted" else message.status,
        "metadata": {
            "request_id": request_id,
            "dispatch_state": _turn_dispatch_state(turn_status),
            "visibility": message.visibility,
            "completion_reason": message.completion_reason,
        },
    }


def _delegated_delivery_message_view(
    backend: Any,
    message: Any,
    *,
    request_id: str | None,
) -> dict[str, Any] | None:
    event_ids = tuple(str(item or "").strip() for item in message.notification_event_ids)
    if len(event_ids) != 1 or not event_ids[0]:
        return None
    with backend.application.database.connection(query_only=True) as connection:
        row = connection.execute(
            "select payload_json from delegated_task_events where event_id = ?",
            (event_ids[0],),
        ).fetchone()
    if row is None:
        return None
    from combo.runtime_protocol import DelegatedTaskEvent
    event = DelegatedTaskEvent.model_validate_json(str(row["payload_json"]))
    if event.event_type not in {"result", "failed", "cancelled"}:
        return None
    payload = event.payload if isinstance(event.payload, dict) else {}
    task_name = str(payload.get("agent_name") or "").strip()
    return {
        "id": message.message_id,
        "role": "system",
        "parts": [{
            "id": f"{message.message_id}:delivery",
            "type": "delegated_delivery",
            "taskId": event.task_id,
            "taskName": task_name,
            "terminalStatus": event.event_type,
        }],
        "timestamp": message.created_at,
        "status": "completed",
        "metadata": {
            "request_id": request_id,
            "visibility": message.visibility,
            "delegated_delivery": True,
            "task_id": event.task_id,
            "task_name": task_name,
            "terminal_status": event.event_type,
        },
    }


def _turn_dispatch_state(turn_status: str) -> str:
    return {
        "queued": "queued",
        "running": "running",
        "waiting_approval": "running",
        "waiting_external": "running",
        "cancelling": "stopping",
        "cancelled": "cancelled",
        "failed": "failed",
        "completed": "completed",
    }.get(str(turn_status or ""), "completed")


def _frontend_message_part(
    *,
    part_id: str,
    kind: str,
    value: dict[str, Any],
) -> dict[str, Any]:
    if kind == "text":
        return {
            "id": part_id,
            "type": "text",
            "format": "markdown",
            "text": value.get("text") or "",
            "status": "completed",
        }
    if kind == "tool_call":
        return {
            "id": part_id,
            "type": kind,
            "toolName": value.get("model_alias") or value.get("capability_id") or "tool_call",
            "callId": value.get("tool_call_id"),
            "arguments": value.get("arguments") or {},
            "status": "completed",
        }
    if kind == "tool_result":
        return {
            "id": part_id,
            "type": kind,
            "toolName": value.get("model_alias") or value.get("capability_id") or "tool_call",
            "callId": value.get("tool_call_id"),
            "output": value.get("output"),
            "error": value.get("error_code"),
            "status": "failed" if value.get("error_code") else value.get("status") or "completed",
            "startedAt": value.get("started_at"),
            "completedAt": value.get("completed_at"),
            "updatedAt": value.get("completed_at"),
        }
    return {"id": part_id, "type": kind, **value}


def _tool_activity_view(backend: Any, record: ToolCallRecord) -> dict[str, Any]:
    status = {
        "proposed": "proposed",
        "waiting_approval": "approval",
        "running": "started",
        "completed": "completed",
        "cancelled": "cancelled",
    }.get(record.status, "failed")
    return {
        "activityKey": record.tool_call_id,
        "requestId": backend._frontend_request_id(
            record.runtime_instance_id,
            record.request_id,
        ),
        "eventType": f"tool_call_{status}",
        "timestamp": record.completed_at or record.started_at or record.updated_at,
        "createdAt": record.created_at,
        "startedAt": record.started_at,
        "completedAt": record.completed_at,
        "stageId": None,
        "nodeId": None,
        "toolCallId": record.tool_call_id,
        "toolName": record.model_alias,
        "status": status,
        "approvalState": "pending" if status == "approval" else None,
        "payload": {
            "tool_call_id": record.tool_call_id,
            "tool_name": record.model_alias,
            "capability_id": record.capability_id,
            "arguments": record.arguments,
            "output": record.result,
            "error": record.error_code,
            "started_at": record.started_at,
            "completed_at": record.completed_at,
        },
    }


def _process_events(backend: Any, session_id: str) -> list[dict[str, Any]]:
    events = backend.application.stores.runtime_events.after_session_sequence(
        session_id=session_id,
        session_sequence=0,
        limit=500,
    )
    projected = []
    for event in events:
        request_id = backend._frontend_request_id(event.runtime_instance_id, event.request_id)
        projected.extend(
            project_runtime_event(
                event,
                request_id=request_id,
                delegated_task_name=backend._delegated_task_name(event.task_id or ""),
            )
        )
    return projected


def _frontend_request_for_runtime(backend: Any, runtime_instance_id: str | None) -> str | None:
    if not runtime_instance_id:
        return None
    return backend._frontend_request_id(runtime_instance_id, runtime_instance_id)


def _first_user_text(backend: Any, session_id: str) -> str | None:
    for message in backend.application.stores.conversations.messages(session_id):
        if message.role != "user":
            continue
        for part in message.parts:
            text = str(getattr(part, "text", "") or "").strip()
            if text:
                return text
    return None


def _turn_count(backend: Any, session_id: str) -> int:
    with backend.application.database.connection(query_only=True) as connection:
        return int(connection.execute(
            "select count(*) from conversation_turns where session_id = ?",
            (session_id,),
        ).fetchone()[0])


def _policy_or_none(backend: Any, principal_id: str) -> UserRuntimePolicy | None:
    try:
        return backend.application.stores.runtime_policies.require_for_principal(principal_id)
    except LookupError:
        return None


def _runtime_preferences_view(policy: UserRuntimePolicy | None) -> dict[str, Any]:
    return {
        "revision": policy.revision if policy else 0,
        "execution_preference": policy.execution_preference if policy else "react",
        "model_profile_id": policy.model_profile_id if policy else None,
        "reasoning_intensity": policy.reasoning_intensity if policy else None,
        "approval_mode": policy.approval_mode if policy else "ask",
        "request_timeout_seconds": policy.request_timeout_seconds if policy else 300,
        "browser_operation_timeout_ms": policy.browser_operation_timeout_ms if policy else 30_000,
        "browser_navigation_timeout_ms": policy.browser_navigation_timeout_ms if policy else 45_000,
        "max_retries": max(0, policy.max_model_attempts - 1) if policy else 5,
        "max_parallel_sub_agents": policy.max_parallel_temporary_agents if policy else 5,
        "memory_auto_write_enabled": policy.memory_auto_write_enabled if policy else True,
        "memory_write_interval_turns": policy.memory_write_interval_turns if policy else 3,
        "memory_agent_write_enabled": policy.memory_agent_write_enabled if policy else True,
        "memory_max_injected_items": policy.memory_max_injected_items if policy else 8,
        "memory_max_injected_tokens": policy.memory_max_injected_tokens if policy else 1200,
        "updated_at": policy.updated_at if policy else None,
    }


def _delegated_task_views(
    backend: Any,
    principal_id: str,
    session_id: str | None,
) -> list[dict[str, Any]]:
    return [
        _delegated_task_row_view(backend, row)
        for row in _delegated_task_rows(backend, principal_id, session_id=session_id)
    ]


def _delegated_task_view(
    backend: Any,
    principal_id: str,
    task_id: str,
) -> dict[str, Any]:
    rows = _delegated_task_rows(backend, principal_id, task_id=task_id)
    if not rows:
        raise HTTPException(status_code=404, detail="background task not found")
    return _delegated_task_row_view(backend, rows[0])


def _delegated_task_rows(
    backend: Any,
    principal_id: str,
    *,
    session_id: str | None = None,
    task_id: str | None = None,
) -> list[Any]:
    with backend.application.database.connection(query_only=True) as connection:
        rows = connection.execute(
            """
            select task.payload_json as task_json, task.status, task.created_at,
                   task.updated_at, task.terminal_at,
                   task.child_runtime_instance_id,
                   runtime.session_id, runtime.request_id,
                   runtime.payload_json as runtime_json
            from delegated_task_revisions as task
            join runtime_instances as runtime
              on runtime.runtime_instance_id = task.child_runtime_instance_id
            where task.principal_id = ?
              and (? is null or runtime.session_id = ?)
              and (? is null or task.task_id = ?)
            order by task.updated_at desc
            """,
            (principal_id, session_id, session_id, task_id, task_id),
        ).fetchall()
    return list(rows)


def _delegated_task_row_view(backend: Any, row: Any) -> dict[str, Any]:
    from combo.runtime_protocol import DelegatedTaskEvent, RuntimeInstance, TaskEnvelope

    task = TaskEnvelope.model_validate_json(str(row["task_json"]))
    child_runtime = RuntimeInstance.model_validate_json(str(row["runtime_json"]))
    selected_model = child_runtime.request.policy_snapshot.model
    with backend.application.database.connection(query_only=True) as connection:
        event_rows = connection.execute(
            """
            select payload_json from delegated_task_events
            where task_id = ? and task_revision = ?
            order by sequence
            """,
            (task.task_id, task.task_revision),
        ).fetchall()
    events = [
        DelegatedTaskEvent.model_validate_json(str(event_row["payload_json"]))
        for event_row in event_rows
    ]
    latest = events[-1] if events else None
    current_activity = _latest_runtime_activity(events)
    result = latest.payload.get("result") if latest and latest.event_type == "result" else None
    error = latest.payload.get("error") if latest and latest.event_type == "failed" else None
    artifacts = [
        dict(event.payload)
        for event in events
        if event.event_type == "artifact"
    ]
    try:
        context_window = backend.application.runtime_service.current_context_window(
            child_runtime.runtime_instance_id
        )
    except (LookupError, RuntimeError, ValueError):
        context_window = None
    return {
        "task_id": task.task_id,
        "session_id": str(row["session_id"]),
        "type": "sub_agent",
        "status": _background_task_status(str(row["status"]), latest),
        "request_id": str(row["request_id"]),
        "child_runtime_instance_id": str(row["child_runtime_instance_id"]),
        "agent_name": task.agent_name,
        "model": {
            "profile_id": selected_model.profile_id,
            "provider": selected_model.provider,
            "model_name": selected_model.model_name,
            "selection_source": task.model_selection_source,
            "selection_reason": task.model_selection_reason,
        },
        "task_text": task.objective,
        "activity_summary": current_activity.get("summary") or task.objective,
        "activity_updated_at": current_activity.get("created_at") or str(row["updated_at"]),
        "payload": task.model_dump(mode="json"),
        "parent_task_id": None,
        "delivery_standard": {"acceptance_criteria": list(task.acceptance_criteria)},
        "visible_context": {"context_facts": list(task.context_facts)},
        "depends_on": [],
        "input_artifacts": list(task.input_artifacts),
        "artifact_refs": artifacts,
        "context_window": context_window,
        "result_summary": _task_result_summary(result),
        "result": {"value": result} if result is not None else None,
        "error": _delegated_error_view(error),
        "pending_interaction": _pending_task_interaction(latest, task_name=task.agent_name),
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
        "started_at": str(row["created_at"]),
        "completed_at": str(row["terminal_at"]) if row["terminal_at"] else None,
        "revision": task.task_revision,
    }


def _delegated_task_event_views(
    backend: Any,
    principal_id: str,
    task_id: str,
) -> list[dict[str, Any]]:
    task = _delegated_task_view(backend, principal_id, task_id)
    child_runtime_id = str(task["child_runtime_instance_id"])
    timeline: list[tuple[str, str, dict[str, Any], str | None]] = []
    with backend.application.database.connection(query_only=True) as connection:
        runtime_rows = connection.execute(
            """
            select event_id, event_kind, payload_json, created_at
            from runtime_events where runtime_instance_id = ?
            order by sequence
            """,
            (child_runtime_id,),
        ).fetchall()
        task_rows = connection.execute(
            """
            select event_id, event_type, payload_json, created_at
            from delegated_task_events
            where principal_id = ? and task_id = ?
            order by sequence
            """,
            (principal_id, task_id),
        ).fetchall()
        tool_rows = connection.execute(
            """
            select payload_json from tool_calls
            where runtime_instance_id = ?
            order by
              case when json_extract(payload_json, '$.completed_at') is null then 1 else 0 end,
              json_extract(payload_json, '$.completed_at'),
              created_at,
              rowid
            """,
            (child_runtime_id,),
        ).fetchall()
    for row in runtime_rows:
        raw = json.loads(str(row["payload_json"]))
        payload = raw.get("payload") if isinstance(raw.get("payload"), dict) else {}
        timeline.append((str(row["created_at"]), str(row["event_id"]), _runtime_activity_payload(payload), str(row["event_kind"])))
    for row in task_rows:
        raw = json.loads(str(row["payload_json"]))
        payload = raw.get("payload") if isinstance(raw.get("payload"), dict) else {}
        activity = _task_activity_payload(str(row["event_type"]), payload)
        if activity is not None:
            timeline.append((str(row["created_at"]), str(row["event_id"]), activity, str(row["event_type"])))
    for row in tool_rows:
        record = ToolCallRecord.model_validate_json(str(row["payload_json"]))
        activity_at = record.completed_at or record.started_at or record.created_at
        timeline.append((activity_at, f"tool:{record.tool_call_id}:{record.status}", _tool_activity_payload(record), "tool"))
    timeline.sort(key=lambda item: (item[0], item[1]))
    return [
        {
            "seq": index,
            "event_id": event_id,
            "event_type": "background_task_activity",
            "created_at": created_at,
            "request_id": task["request_id"],
            "task_id": task_id,
            "session_id": task["session_id"],
            "payload": payload,
        }
        for index, (created_at, event_id, payload, _kind) in enumerate(timeline, start=1)
    ]


def _runtime_activity_payload(payload: dict[str, Any]) -> dict[str, Any]:
    kind = str(payload.get("kind") or "runtime_progress")
    labels = {
        "runtime_queued": ("backgroundTask.activity.queued", "backgroundTask.description.queued"),
        "runtime_started": ("backgroundTask.activity.started", "backgroundTask.description.running"),
        "runtime_waiting_approval": ("backgroundTask.activity.approval", "backgroundTask.pendingApproval"),
        "runtime_waiting_external": ("backgroundTask.activity.input", "backgroundTask.pendingInput"),
        "runtime_completed": ("backgroundTask.activity.completed", "backgroundTask.description.succeeded"),
        "failed": ("backgroundTask.activity.failed", "backgroundTask.failedFallback"),
        "cancelled": ("backgroundTask.activity.cancelled", "backgroundTask.description.cancelled"),
    }
    title_key, summary_key = labels.get(kind, ("backgroundTask.activity.progress", ""))
    return {"phase_id": kind, "title_key": title_key, "summary_key": summary_key, "summary": str(payload.get("status") or kind), "status": payload.get("status") or "running", "details": payload}


def _task_activity_payload(event_type: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    if event_type == "activity":
        source_event_id = str(payload.get("source_event_id") or "runtime_activity_updated")
        details = payload.get("details") if isinstance(payload.get("details"), dict) else {}
        if str(payload.get("source") or "") == "tool":
            tool_call_id = str(details.get("tool_call_id") or "").strip()
            if not tool_call_id:
                return None
            return {
                "phase_id": f"tool:{tool_call_id}",
                "category": "tool",
                "title": str(details.get("tool_name") or details.get("tool_id") or "").strip(),
                "summary": str(payload.get("summary") or "").strip(),
                "status": str(payload.get("status") or "running"),
                "details": details,
            }
        return {
            "phase_id": f"activity:{source_event_id}",
            "category": "activity",
            "title_key": "backgroundTask.activity.current",
            "summary": str(payload.get("summary") or "").strip(),
            "status": str(payload.get("status") or "active"),
            "details": payload,
        }
    title_key = {
        "question": "backgroundTask.activity.input",
        "approval_required": "backgroundTask.activity.approval",
        "result": "backgroundTask.activity.result",
        "failed": "backgroundTask.activity.failed",
        "cancelled": "backgroundTask.activity.cancelled",
    }.get(event_type, "backgroundTask.activity.progress")
    error = _delegated_error_view(payload.get("error")) if event_type == "failed" else None
    summary = (
        str(error.get("message") or "")
        if error is not None
        else _task_result_summary(payload.get("result")) or str(payload.get("summary") or event_type)
    )
    return {"phase_id": f"task:{event_type}", "category": "lifecycle", "title_key": title_key, "summary": summary, "status": "completed" if event_type == "result" else event_type, "details": payload}


def _tool_activity_payload(record: ToolCallRecord) -> dict[str, Any]:
    return {
        "phase_id": f"tool:{record.tool_call_id}",
        "category": "tool",
        "title": record.model_alias,
        "summary_key": f"backgroundTask.toolStatus.{record.status}",
        "summary": record.status,
        "status": record.status,
        "details": record.model_dump(mode="json"),
    }


def _latest_runtime_activity(events: list[Any]) -> dict[str, str]:
    for event in reversed(events):
        if event.event_type != "activity":
            continue
        payload = event.payload if isinstance(event.payload, dict) else {}
        summary = str(payload.get("summary") or "").strip()
        if summary:
            return {"summary": summary, "created_at": str(event.created_at)}
    return {}


def _pending_task_interaction(event: Any, *, task_name: str) -> dict[str, Any] | None:
    if event is None or event.event_type not in {"approval_required", "question"}:
        return None
    details = event.payload.get("details") if isinstance(event.payload.get("details"), dict) else {}
    interrupts = details.get("interrupts") if isinstance(details.get("interrupts"), list) else []
    interrupt = interrupts[0] if interrupts and isinstance(interrupts[0], dict) else {}
    interaction_id = str(interrupt.get("interrupt_id") or interrupt.get("id") or "").strip()
    if not interaction_id:
        return None
    requests = interrupt.get("requests") if isinstance(interrupt.get("requests"), list) else []
    return {
        "interaction_id": interaction_id,
        "kind": "tool_approval" if event.event_type == "approval_required" else "ask_user",
        "title": "tool.pendingApproval" if event.event_type == "approval_required" else "backgroundTask.activity.input",
        "message": str(interrupt.get("message") or ""),
        "source": {
            "task_id": event.task_id,
            "task_name": task_name,
            "runtime_instance_id": event.child_runtime_instance_id,
        },
        "options": interrupt.get("choices") if isinstance(interrupt.get("choices"), list) else [],
        "requests": [dict(item) for item in requests if isinstance(item, dict)],
        "resource_requests": [],
        "payload": dict(interrupt),
    }


def _task_result_summary(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value[:240]
    if isinstance(value, dict) and value.get("summary") is not None:
        return str(value["summary"])[:240]
    return json.dumps(value, ensure_ascii=False)[:240]


def _delegated_error_view(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    details = value.get("details") if isinstance(value.get("details"), dict) else {}
    message = str(
        details.get("message")
        or details.get("reason")
        or value.get("message")
        or value.get("user_message_key")
        or value.get("code")
        or ""
    ).strip()
    return {
        "code": str(value.get("code") or "runtime_execution_failed"),
        "message": message,
        "details": details,
    }


def _background_task_status(value: str, latest_event: Any = None) -> str:
    if value == "waiting" and latest_event is not None:
        return "waiting_approval" if latest_event.event_type == "approval_required" else "waiting_external"
    return {
        "completed": "succeeded",
    }.get(value, value)


def _enqueue_runtime_control(
    backend: Any,
    *,
    principal_id: str,
    session_id: str,
    payload: dict[str, Any],
) -> None:
    command_id = uuid4().hex
    envelope = CommandEnvelope(
        protocol_version=RuntimeProtocolDescriptor(
            build_revision=backend.config.build_revision
        ).protocol_version,
        command_id=command_id,
        client_instance_id="background-task-api",
        principal_id=principal_id,
        session_id=session_id,
        payload=payload,
    )
    backend.application.stores.commands.accept(
        envelope,
        CommandReceipt(
            command_id=command_id,
            client_instance_id=envelope.client_instance_id,
            principal_id=principal_id,
            session_id=session_id,
            status="received",
        ),
    )
    backend.supervisor.notify_commands()


def _workspace_projects(backend: Any, principal_id: str) -> list[dict[str, Any]]:
    return [
        _workspace_project_view(backend, workspace)
        for workspace in backend.application.stores.conversations.list_workspaces_for_principal(principal_id)
        if workspace.status == "active"
    ]


def _owned_scheduler_job(backend: Any, principal_id: str, job_id: str) -> dict[str, Any]:
    try:
        job = backend.application.stores.scheduler.require_job(job_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="scheduler job not found") from exc
    if str(job.get("principal_id") or "") != principal_id:
        raise HTTPException(status_code=404, detail="scheduler job not found")
    return job


def _workspace_project_view(backend: Any, workspace: Any) -> dict[str, Any]:
    source_path = workspace.managed_path
    if workspace.kind == "mounted" and workspace.mount_record_id:
        source_path = backend.application.stores.conversations.require_mount_path(
            workspace.mount_record_id,
            workspace.principal_id,
        )
    return {
        "workspace_id": workspace.workspace_id,
        "title": workspace.title or "工作区",
        "mode": workspace.mode,
        "root_kind": "linked" if workspace.kind == "mounted" else "managed",
        "owner_package_id": None,
        "workdir_root": source_path or "",
        "archived": workspace.status != "active",
        "created_at": workspace.created_at,
        "updated_at": workspace.updated_at,
    }


def _workspace_root(
    backend: Any,
    *,
    principal_id: str,
    session_id: str | None,
    workspace_id: str | None,
) -> Path:
    resolved_workspace_id = str(workspace_id or "").strip()
    if session_id:
        conversation = backend.application.stores.conversations.require_identity(session_id)
        if conversation.principal_id != principal_id:
            raise HTTPException(status_code=404, detail="conversation not found")
        resolved_workspace_id = conversation.workspace_id
    if not resolved_workspace_id:
        raise HTTPException(status_code=409, detail="active workspace is required")
    try:
        root = backend.application.stores.conversations.require_workspace_root(
            resolved_workspace_id,
            principal_id,
        )
    except (LookupError, PermissionError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="workspace not found") from exc
    return Path(root)


def _memory_workspace_id(
    backend: Any,
    principal_id: str,
    workspace_id: str | None,
) -> str:
    value = str(workspace_id or "").strip()
    if value:
        workspace = backend.application.stores.conversations.require_workspace(value)
        if workspace.principal_id != principal_id or workspace.status != "active":
            raise HTTPException(status_code=404, detail="workspace not found")
        return value
    conversations = backend.application.stores.conversations.list_for_principal(principal_id)
    if not conversations:
        raise HTTPException(status_code=409, detail="active workspace is required")
    return conversations[0].workspace_id


def _workspace_path(root: Path, relative_path: str) -> Path:
    candidate = (root / str(relative_path or "")).resolve()
    if candidate != root and root not in candidate.parents:
        raise HTTPException(status_code=403, detail="workspace path escapes the active workspace")
    return candidate


def _workspace_entry(root: Path, target: Path, scope: str) -> dict[str, Any]:
    stat = target.stat()
    return {
        "name": target.name,
        "scope": scope,
        "path": target.relative_to(root).as_posix(),
        "kind": "directory" if target.is_dir() else "file",
        "size_bytes": None if target.is_dir() else stat.st_size,
        "updated_at": utc_now_text() if stat.st_mtime <= 0 else _timestamp_text(stat.st_mtime),
        "mount": False,
        "mount_id": None,
        "mount_source": None,
        "connected": True,
    }


def _timestamp_text(value: float) -> str:
    from datetime import UTC, datetime
    return datetime.fromtimestamp(value, UTC).isoformat()


def _directory_size(root: Path) -> int:
    if not root.exists():
        return 0
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def _directory_file_count(root: Path) -> int:
    if not root.exists():
        return 0
    return sum(1 for path in root.rglob("*") if path.is_file())


def _system_package(session_count: int) -> dict[str, Any]:
    now = utc_now_text()
    return {
        "package_id": SYSTEM_CHAT_PACKAGE_ID,
        "package_origin": "system",
        "is_builtin": True,
        "capabilities": {"deletable": False, "exportable": False},
        "agent_name": "闲聊",
        "name": "闲聊",
        "agent_description": "主 Agent",
        "status": "ready",
        "tool_count": None,
        "session_count": session_count,
        "created_at": now,
        "updated_at": now,
    }


def _event(
    event_type: str,
    payload: dict[str, Any],
    *,
    session_id: str | None = None,
) -> dict[str, Any]:
    from web_frontend.backend.frontend_event_bridge import _frontend_event
    return _frontend_event(
        event_type=event_type,
        request_id=None,
        runtime_instance_id=None,
        session_id=session_id,
        node_id=None,
        timestamp=None,
        payload=payload,
    )


def _principal(request: Request) -> str:
    return _required_text(request.headers.get("X-Combo-Principal"), "principal header")


def _knowledge_source_payload(value: Any) -> dict[str, Any]:
    try:
        source = KnowledgeSourceWrite.model_validate(value)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="invalid knowledge source metadata") from exc
    return source.model_dump(mode="json", exclude_none=True)


def _attachment_references(principal_id: str, value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise HTTPException(status_code=422, detail="attachments must be an array")
    references: list[dict[str, Any]] = []
    store = attachment_upload_store()
    for index, raw in enumerate(value):
        if not isinstance(raw, dict):
            raise HTTPException(status_code=422, detail=f"attachments.{index} must be an object")
        attachment_id = str(raw.get("attachment_id") or "").strip()
        try:
            if attachment_id:
                staged = store.resolve(attachment_id)
                if staged.principal_id != principal_id:
                    raise PermissionError("attachment does not belong to the runtime principal")
            else:
                content = raw.get("content")
                if not isinstance(content, str):
                    raise AttachmentUploadError("inline attachment requires string content")
                if raw.get("encoding") == "base64":
                    try:
                        content_bytes = base64.b64decode(content, validate=True)
                    except ValueError as exc:
                        raise AttachmentUploadError("inline attachment base64 is invalid") from exc
                else:
                    content_bytes = content.encode("utf-8")
                staged = store.stage_bytes(
                    content=content_bytes,
                    name=str(raw.get("name") or f"attachment-{index + 1}"),
                    mime_type=str(raw.get("mime_type") or "").strip() or None,
                    principal_id=principal_id,
                )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except AttachmentUploadError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        references.append({
            "attachment_id": staged.attachment_id,
            "revision": 1,
            "content_digest": staged.content_digest,
        })
    return references


def _command_id(command: dict[str, Any]) -> str:
    return str(command.get("request_id") or uuid4().hex).strip()


def _require_system_package(value: Any) -> None:
    if str(value or "").strip() != SYSTEM_CHAT_PACKAGE_ID:
        raise HTTPException(status_code=410, detail="published Agent packages were removed")


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail=f"{field_name} must not be empty")
    return text
