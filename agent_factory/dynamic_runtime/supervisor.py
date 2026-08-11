from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from agent_factory.dynamic_runtime.application import DynamicRuntimeApplication
from agent_factory.dynamic_runtime.dispatcher import CommandDispatcher
from agent_factory.dynamic_runtime.outbox_publisher import OutboxPublisher


FailureReporter = Callable[[str, BaseException], None]


@dataclass(frozen=True, slots=True)
class DynamicRuntimeSupervisorConfig:
    command_worker_count: int
    idle_poll_seconds: float
    generation_renew_seconds: float

    def __post_init__(self) -> None:
        if self.command_worker_count < 1:
            raise ValueError("command_worker_count must be positive")
        if self.idle_poll_seconds <= 0:
            raise ValueError("idle_poll_seconds must be positive")
        if self.generation_renew_seconds <= 0:
            raise ValueError("generation_renew_seconds must be positive")


class DynamicRuntimeSupervisor:
    """Own dispatcher, outbox, and generation-lease task lifecycles."""

    def __init__(
        self,
        *,
        application: DynamicRuntimeApplication,
        dispatcher: CommandDispatcher,
        outbox_publisher: OutboxPublisher,
        config: DynamicRuntimeSupervisorConfig,
        report_failure: FailureReporter,
    ) -> None:
        self._application = application
        self._dispatcher = dispatcher
        self._outbox_publisher = outbox_publisher
        self._config = config
        self._report_failure = report_failure
        self._stop = asyncio.Event()
        self._command_wakeup: asyncio.Queue[None] = asyncio.Queue(maxsize=1)
        self._control_wakeup: asyncio.Queue[None] = asyncio.Queue(maxsize=1)
        self._outbox_wakeup: asyncio.Queue[None] = asyncio.Queue(maxsize=1)
        self._tasks: list[asyncio.Task[None]] = []

    @property
    def running(self) -> bool:
        return bool(self._tasks) and any(not task.done() for task in self._tasks)

    def start(self) -> None:
        if self._tasks:
            raise RuntimeError("dynamic runtime supervisor is already started")
        self._outbox_publisher.recover_interrupted_publications()
        self._tasks = [
            *(
                asyncio.create_task(
                    self._command_loop(worker_index),
                    name=f"dynamic-runtime-command-{worker_index}",
                )
                for worker_index in range(self._config.command_worker_count)
            ),
            asyncio.create_task(
                self._command_loop(-1, lane="control"),
                name="dynamic-runtime-command-control",
            ),
            asyncio.create_task(self._outbox_loop(), name="dynamic-runtime-outbox"),
            asyncio.create_task(self._generation_loop(), name="dynamic-runtime-generation"),
        ]
        self.notify_commands()
        self.notify_outbox()

    async def stop(self) -> None:
        tasks = tuple(self._tasks)
        if not tasks:
            return
        self._stop.set()
        self.notify_commands()
        self.notify_outbox()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()

    def notify_commands(self) -> None:
        _notify(self._command_wakeup)
        _notify(self._control_wakeup)

    def notify_outbox(self) -> None:
        _notify(self._outbox_wakeup)

    async def _command_loop(self, worker_index: int, *, lane: str = "work") -> None:
        component = f"command_dispatcher[{lane}:{worker_index}]"
        while not self._stop.is_set():
            try:
                processed = await self._dispatcher.dispatch_one(
                    generation=self._application.generation.generation,
                    lane="control" if lane == "control" else "work",
                )
            except BaseException as exc:
                if isinstance(exc, asyncio.CancelledError):
                    raise
                self._report_failure(component, exc)
                processed = False
            if processed:
                self.notify_outbox()
                continue
            await self._wait_for(
                self._control_wakeup if lane == "control" else self._command_wakeup
            )

    async def _outbox_loop(self) -> None:
        while not self._stop.is_set():
            try:
                processed = await self._outbox_publisher.publish_one()
            except BaseException as exc:
                if isinstance(exc, asyncio.CancelledError):
                    raise
                self._report_failure("outbox_publisher", exc)
                processed = False
            if processed:
                continue
            await self._wait_for(self._outbox_wakeup)

    async def _generation_loop(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=self._config.generation_renew_seconds,
                )
                return
            except asyncio.TimeoutError:
                pass
            try:
                await asyncio.to_thread(self._application.renew_generation_lease)
            except BaseException as exc:
                if isinstance(exc, asyncio.CancelledError):
                    raise
                self._report_failure("application_generation", exc)
                self._stop.set()
                self.notify_commands()
                self.notify_outbox()
                return

    async def _wait_for(self, wakeup: asyncio.Queue[None]) -> None:
        if self._stop.is_set():
            return
        try:
            await asyncio.wait_for(wakeup.get(), timeout=self._config.idle_poll_seconds)
        except asyncio.TimeoutError:
            return


def _notify(wakeup: asyncio.Queue[None]) -> None:
    try:
        wakeup.put_nowait(None)
    except asyncio.QueueFull:
        return
