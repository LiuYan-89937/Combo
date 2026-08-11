from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
from typing import Protocol
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent_factory.dynamic_runtime import (
    DynamicRuntimeApplication,
    DynamicRuntimeSupervisor,
    RuntimeEventBroadcaster,
)
from agent_factory.dynamic_runtime.repositories import utc_now_text
from agent_factory.runtime_protocol import (
    CommandEnvelope,
    CommandReceipt,
    RuntimeProtocolDescriptor,
    RuntimeProtocolHandshake,
    RuntimeProtocolHandshakeResult,
    UserRuntimePolicy,
)


class RequestPrincipalResolver(Protocol):
    def resolve(self, request: Request) -> str:
        ...


@dataclass(frozen=True, slots=True)
class DynamicRuntimeApiConfig:
    keepalive_seconds: float
    replay_limit: int

    def __post_init__(self) -> None:
        if self.keepalive_seconds <= 0:
            raise ValueError("keepalive_seconds must be positive")
        if self.replay_limit < 1:
            raise ValueError("replay_limit must be positive")


class RuntimePolicyWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int | None = Field(default=None, ge=1)
    execution_preference: str
    approval_mode: str
    model_profile_id: str
    reasoning_intensity: int | None = Field(default=None, ge=0)
    request_timeout_seconds: int = Field(ge=1)
    max_model_attempts: int = Field(ge=1)
    max_parallel_temporary_agents: int = Field(ge=1)
    timezone: str

    @field_validator("execution_preference")
    @classmethod
    def _execution_preference_is_supported(cls, value: str) -> str:
        if value not in {"auto", "react", "plan_and_execute"}:
            raise ValueError("unsupported execution_preference")
        return value

    @field_validator("approval_mode")
    @classmethod
    def _approval_mode_is_supported(cls, value: str) -> str:
        if value not in {"ask", "auto", "always_approval"}:
            raise ValueError("unsupported approval_mode")
        return value

    @field_validator("model_profile_id")
    @classmethod
    def _model_profile_is_present(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("model_profile_id must not be empty")
        return text

    @field_validator("timezone")
    @classmethod
    def _timezone_is_supported(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("timezone must not be empty")
        try:
            ZoneInfo(text)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown timezone: {text}") from exc
        return text


def create_dynamic_runtime_router(
    *,
    application: DynamicRuntimeApplication,
    supervisor: DynamicRuntimeSupervisor,
    broadcaster: RuntimeEventBroadcaster,
    principal_resolver: RequestPrincipalResolver,
    config: DynamicRuntimeApiConfig,
) -> APIRouter:
    router = APIRouter(prefix="/api/runtime")

    @router.post("/handshake", response_model=RuntimeProtocolHandshakeResult)
    async def handshake(payload: RuntimeProtocolHandshake) -> RuntimeProtocolHandshakeResult:
        server = _server_descriptor(application)
        accepted = server.matches(payload.client)
        return RuntimeProtocolHandshakeResult(
            status="accepted" if accepted else "incompatible",
            server=server,
            client_instance_id=payload.client_instance_id,
            generation=application.generation.generation,
            error_code=None if accepted else "runtime_protocol_mismatch",
        )

    @router.get("/policy", response_model=UserRuntimePolicy)
    async def runtime_policy(request: Request) -> UserRuntimePolicy:
        principal_id = principal_resolver.resolve(request)
        try:
            return application.stores.runtime_policies.require_for_principal(principal_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="runtime_policy_not_configured") from exc

    @router.put("/policy", response_model=UserRuntimePolicy)
    async def write_runtime_policy(
        request: Request,
        payload: RuntimePolicyWriteRequest,
    ) -> UserRuntimePolicy:
        principal_id = principal_resolver.resolve(request)
        now = utc_now_text()
        try:
            current = application.stores.runtime_policies.require_for_principal(principal_id)
        except LookupError:
            current = None
        policy = UserRuntimePolicy(
            principal_id=principal_id,
            policy_id=current.policy_id if current is not None else uuid4().hex,
            revision=current.revision + 1 if current is not None else 1,
            execution_preference=payload.execution_preference,
            approval_mode=payload.approval_mode,
            model_profile_id=payload.model_profile_id,
            reasoning_intensity=payload.reasoning_intensity,
            request_timeout_seconds=payload.request_timeout_seconds,
            max_model_attempts=payload.max_model_attempts,
            max_parallel_temporary_agents=payload.max_parallel_temporary_agents,
            timezone=payload.timezone,
            updated_at=now,
        )
        if current is None:
            if payload.expected_revision is not None:
                raise HTTPException(status_code=409, detail="runtime_policy_revision_conflict")
            saved = application.stores.runtime_policies.create(policy, created_at=now)
        else:
            if payload.expected_revision != current.revision:
                raise HTTPException(status_code=409, detail="runtime_policy_revision_conflict")
            saved = application.stores.runtime_policies.replace(
                policy,
                expected_revision=current.revision,
            )
        supervisor.notify_outbox()
        return saved

    @router.post("/commands", response_model=CommandReceipt)
    async def submit_command(
        request: Request,
        envelope: CommandEnvelope,
        x_agentfactory_protocol: str = Header(alias="X-AgentFactory-Protocol"),
        x_agentfactory_schema: str = Header(alias="X-AgentFactory-Schema"),
        x_agentfactory_build: str = Header(alias="X-AgentFactory-Build"),
        x_agentfactory_generation: int = Header(alias="X-AgentFactory-Generation"),
    ) -> CommandReceipt:
        _require_compatible_headers(
            application,
            protocol_version=x_agentfactory_protocol,
            schema_version=x_agentfactory_schema,
            build_revision=x_agentfactory_build,
            generation=x_agentfactory_generation,
        )
        principal_id = principal_resolver.resolve(request)
        if envelope.principal_id != principal_id:
            raise HTTPException(status_code=403, detail="command principal does not match authenticated principal")
        if envelope.protocol_version != x_agentfactory_protocol:
            raise HTTPException(status_code=409, detail="runtime_protocol_mismatch")
        identity = application.stores.conversations.require_identity(envelope.session_id)
        if identity.principal_id != principal_id:
            raise HTTPException(status_code=403, detail="conversation is owned by a different principal")
        receipt = application.stores.commands.accept(
            envelope,
            CommandReceipt(
                command_id=envelope.command_id,
                client_instance_id=envelope.client_instance_id,
                principal_id=envelope.principal_id,
                session_id=envelope.session_id,
                status="received",
            ),
        )
        supervisor.notify_commands()
        supervisor.notify_outbox()
        return receipt

    @router.get("/commands/{command_id}", response_model=CommandReceipt)
    async def command_receipt(request: Request, command_id: str) -> CommandReceipt:
        principal_id = principal_resolver.resolve(request)
        receipt = application.stores.commands.get_receipt(command_id)
        if receipt.principal_id != principal_id:
            raise HTTPException(status_code=404, detail="command receipt not found")
        return receipt

    @router.get("/events")
    async def runtime_events(
        request: Request,
        session_id: str,
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        principal_id = principal_resolver.resolve(request)
        identity = application.stores.conversations.require_identity(session_id)
        if identity.principal_id != principal_id:
            raise HTTPException(status_code=404, detail="conversation not found")
        subscription = await broadcaster.subscribe(session_id)
        try:
            replay_sequence = application.stores.runtime_events.session_sequence_for_event(
                session_id=session_id,
                event_id=last_event_id,
            )
            replay_high_water = application.stores.runtime_events.latest_session_sequence(session_id)
        except LookupError as exc:
            await broadcaster.unsubscribe(subscription)
            raise HTTPException(status_code=409, detail="runtime_event_cursor_unknown") from exc

        async def stream():
            delivered_sequence = replay_sequence
            try:
                while delivered_sequence < replay_high_water:
                    replay = application.stores.runtime_events.after_session_sequence(
                        session_id=session_id,
                        session_sequence=delivered_sequence,
                        limit=config.replay_limit,
                    )
                    if not replay:
                        yield _sse_control("runtime_event_gap")
                        return
                    for event in replay:
                        if event.session_sequence <= delivered_sequence:
                            continue
                        delivered_sequence = event.session_sequence
                        yield _sse_event(event.event_id, event.model_dump(mode="json"))
                while not await request.is_disconnected():
                    queue_task = asyncio.create_task(subscription.queue.get())
                    disconnect_task = asyncio.create_task(subscription.disconnected.wait())
                    done, pending = await asyncio.wait(
                        {queue_task, disconnect_task},
                        timeout=config.keepalive_seconds,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for task in pending:
                        task.cancel()
                    if pending:
                        await asyncio.gather(*pending, return_exceptions=True)
                    if not done:
                        yield ": keep-alive\n\n"
                        continue
                    if disconnect_task in done and disconnect_task.result():
                        yield _sse_control(subscription.disconnect_reason or "stream_disconnected")
                        return
                    event = queue_task.result()
                    if event.session_sequence <= delivered_sequence:
                        continue
                    while delivered_sequence < event.session_sequence:
                        recovered = application.stores.runtime_events.after_session_sequence(
                            session_id=session_id,
                            session_sequence=delivered_sequence,
                            limit=config.replay_limit,
                        )
                        if not recovered:
                            yield _sse_control("runtime_event_gap")
                            return
                        for recovered_event in recovered:
                            if recovered_event.session_sequence <= delivered_sequence:
                                continue
                            delivered_sequence = recovered_event.session_sequence
                            yield _sse_event(
                                recovered_event.event_id,
                                recovered_event.model_dump(mode="json"),
                            )
            finally:
                await broadcaster.unsubscribe(subscription)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return router


def _server_descriptor(application: DynamicRuntimeApplication) -> RuntimeProtocolDescriptor:
    return RuntimeProtocolDescriptor(
        build_revision=application.config.build_revision,
    )


def _require_compatible_headers(
    application: DynamicRuntimeApplication,
    *,
    protocol_version: str,
    schema_version: str,
    build_revision: str,
    generation: int,
) -> None:
    descriptor = _server_descriptor(application)
    if (
        protocol_version != descriptor.protocol_version
        or schema_version != descriptor.schema_version
        or build_revision != descriptor.build_revision
    ):
        raise HTTPException(status_code=409, detail="runtime_protocol_mismatch")
    if generation != application.generation.generation:
        raise HTTPException(status_code=409, detail="application_generation_changed")


def _sse_event(event_id: str, payload: dict[str, object]) -> str:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"id: {event_id}\nevent: runtime_event\ndata: {data}\n\n"


def _sse_control(reason: str) -> str:
    data = json.dumps({"reason": reason}, ensure_ascii=False, separators=(",", ":"))
    return f"event: stream_control\ndata: {data}\n\n"
