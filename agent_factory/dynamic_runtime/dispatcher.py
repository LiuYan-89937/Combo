from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Literal, Mapping, Protocol

from agent_factory.dynamic_runtime.repositories import CommandInbox, utc_now_text
from agent_factory.runtime_protocol import (
    CommandEnvelope,
    CommandReceipt,
    OutboxRecord,
    RuntimeErrorEnvelope,
)


CommandTerminalStatus = Literal["completed", "failed", "cancelled", "rejected"]


@dataclass(frozen=True, slots=True)
class CommandOutcome:
    status: CommandTerminalStatus
    request_id: str | None = None
    runtime_instance_id: str | None = None
    error: RuntimeErrorEnvelope | None = None
    rejection_code: str | None = None

    def __post_init__(self) -> None:
        if self.status == "failed" and self.error is None:
            raise ValueError("failed command outcome requires an error")
        if self.status == "rejected" and not str(self.rejection_code or "").strip():
            raise ValueError("rejected command outcome requires rejection_code")
        if self.status != "rejected" and self.rejection_code is not None:
            raise ValueError("only rejected command outcome can carry rejection_code")
        if self.error is not None:
            if self.error.request_id != self.request_id:
                raise ValueError("command outcome error request identity differs")
            if self.error.runtime_instance_id != self.runtime_instance_id:
                raise ValueError("command outcome error runtime identity differs")


class CommandHandler(Protocol):
    def handle(
        self,
        envelope: CommandEnvelope,
        receipt: CommandReceipt,
        *,
        generation: int,
    ) -> Awaitable[CommandOutcome]:
        ...


class CommandExecutionRegistry:
    """Own cancellable in-flight command handlers before runtime attachment."""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task[CommandOutcome]] = {}
        self._cancellation_reasons: dict[str, str] = {}

    def register(self, command_id: str, task: asyncio.Task[CommandOutcome]) -> None:
        if command_id in self._tasks:
            raise RuntimeError(f"command execution is already registered: {command_id}")
        self._tasks[command_id] = task

    def cancel(self, command_id: str, *, reason: str) -> bool:
        task = self._tasks.get(command_id)
        if task is None or task.done():
            return False
        self._cancellation_reasons[command_id] = str(reason or "user_cancelled")
        task.cancel()
        return True

    def cancellation_reason(self, command_id: str) -> str | None:
        return self._cancellation_reasons.get(command_id)

    def release(self, command_id: str, task: asyncio.Task[CommandOutcome]) -> None:
        if self._tasks.get(command_id) is task:
            self._tasks.pop(command_id, None)
        self._cancellation_reasons.pop(command_id, None)


class CommandDispatcher:
    """Claim durable commands and finalize each receipt exactly once."""

    def __init__(
        self,
        *,
        inbox: CommandInbox,
        handlers: Mapping[str, CommandHandler],
        executions: CommandExecutionRegistry,
    ) -> None:
        self._inbox = inbox
        self._handlers = dict(handlers)
        self._executions = executions

    async def dispatch_one(
        self,
        *,
        generation: int,
        lane: Literal["work", "control"],
    ) -> bool:
        claimed = self._inbox.claim_next(generation=generation, lane=lane)
        if claimed is None:
            return False
        envelope, receipt = claimed
        handler = self._handlers.get(envelope.payload.kind)
        if handler is None:
            outcome = CommandOutcome(
                status="rejected",
                rejection_code="unsupported_command_kind",
            )
        else:
            execution = asyncio.create_task(
                handler.handle(envelope, receipt, generation=generation),
                name=f"dynamic-runtime-command-{envelope.command_id}",
            )
            self._executions.register(envelope.command_id, execution)
            try:
                outcome = await execution
            except asyncio.CancelledError:
                if self._executions.cancellation_reason(envelope.command_id) is None:
                    raise
                outcome = CommandOutcome(status="cancelled")
            except Exception as exc:
                current_receipt = self._inbox.get_receipt(receipt.command_id)
                if current_receipt.runtime_instance_id is not None:
                    raise RuntimeError(
                        "command handler failed after attaching a runtime instance"
                    ) from exc
                outcome = CommandOutcome(
                    status="rejected",
                    rejection_code="command_handler_failed_before_runtime",
                )
            finally:
                self._executions.release(envelope.command_id, execution)
        current_receipt = self._inbox.get_receipt(receipt.command_id)
        self._finalize(current_receipt, outcome)
        return True

    def _finalize(self, receipt: CommandReceipt, outcome: CommandOutcome) -> None:
        now = utc_now_text()
        terminal = receipt.model_copy(
            update={
                "status": outcome.status,
                "receipt_revision": receipt.receipt_revision + 1,
                "request_id": outcome.request_id,
                "runtime_instance_id": outcome.runtime_instance_id,
                "error": outcome.error,
                "rejection_code": outcome.rejection_code,
                "updated_at": now,
                "terminal_at": now,
            }
        )
        self._inbox.replace_receipt(
            receipt=terminal,
            expected_revision=receipt.receipt_revision,
            outbox=OutboxRecord(
                aggregate_kind="command",
                aggregate_id=terminal.command_id,
                aggregate_revision=terminal.receipt_revision,
                event_id=f"command:{terminal.command_id}:{terminal.receipt_revision}",
                event_kind=f"command_{terminal.status}",
                payload=terminal.model_dump(mode="json"),
                created_at=now,
                updated_at=now,
            ),
        )
