from __future__ import annotations

import asyncio
from collections import deque
import json
import logging
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from agent_factory.factory_graph.frontend_bridge.protocol import (
    FactoryFrontendCommand,
)

logger = logging.getLogger(__name__)


class RuntimeBridge:
    """Owns the stdio runtime process and SSE event fan-out."""

    def __init__(self) -> None:
        self.process: subprocess.Popen | None = None
        self.event_history: deque[dict[str, Any]] = deque(maxlen=500)
        self.subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self.command_lock = asyncio.Lock()
        self._reader_task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        if self.process is not None:
            logger.warning("Runtime bridge already started")
            return

        python_exec = sys.executable
        stdio_server_path = (
            Path(__file__).parent.parent.parent
            / "agent_factory"
            / "factory_graph"
            / "frontend_bridge"
            / "stdio_server.py"
        )

        logger.info("Starting stdio_server: %s", stdio_server_path)
        self.process = subprocess.Popen(
            [python_exec, str(stdio_server_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        self._running = True
        self._reader_task = asyncio.create_task(self._read_events())
        logger.info("Runtime bridge started")

    async def stop(self) -> None:
        self._running = False
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass

        if self.process:
            try:
                shutdown_cmd = FactoryFrontendCommand(
                    type="shutdown",
                    request_id=str(uuid.uuid4()),
                )
                await self.send_command(shutdown_cmd.model_dump(mode="json"))
            except Exception:
                pass

            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None
        logger.info("Runtime bridge stopped")

    async def send_command(self, command: dict[str, Any]) -> None:
        if not self.process or not self.process.stdin:
            raise RuntimeError("Runtime bridge not started")

        async with self.command_lock:
            try:
                command_json = json.dumps(command, ensure_ascii=False)
                logger.debug("Sending command: %s", command["type"])
                self.process.stdin.write(command_json + "\n")
                self.process.stdin.flush()
            except Exception as exc:
                logger.error("Failed to send command: %s", exc)
                raise

    async def send_frontend_command(self, command: FactoryFrontendCommand) -> None:
        await self.send_command(command.model_dump(mode="json"))

    async def send_and_wait(
        self,
        command: FactoryFrontendCommand,
        *,
        event_types: set[str],
        timeout_seconds: float = 30.0,
    ) -> dict[str, Any]:
        event_queue = self.subscribe(replay_history=False)
        try:
            await self.send_frontend_command(command)
            loop = asyncio.get_running_loop()
            deadline = loop.time() + timeout_seconds
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise HTTPException(status_code=504, detail=f"Timed out waiting for {command.type}")
                event = await asyncio.wait_for(event_queue.get(), timeout=remaining)
                if event.get("request_id") != command.request_id:
                    continue
                if event.get("event_type") == "error":
                    raise HTTPException(status_code=400, detail=event.get("message") or "Runtime command failed")
                if event.get("event_type") in event_types:
                    return event
        finally:
            self.unsubscribe(event_queue)

    def subscribe(self, *, replay_history: bool = True) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)
        if replay_history:
            for event in self.event_history:
                queue.put_nowait(event)
        self.subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self.subscribers.discard(queue)

    async def _read_events(self) -> None:
        if not self.process or not self.process.stdout:
            return

        loop = asyncio.get_event_loop()

        try:
            while self._running and self.process.poll() is None:
                line = await loop.run_in_executor(None, self.process.stdout.readline)

                if not line:
                    break

                line = line.strip()
                if not line:
                    continue

                try:
                    event = json.loads(line)
                    logger.debug("Received event: %s", event.get("event_type", "unknown"))
                    self.event_history.append(event)
                    await self._broadcast_event(event)
                except json.JSONDecodeError as exc:
                    logger.error("Invalid JSON from backend: %s... Error: %s", line[:100], exc)
                    continue

        except Exception as exc:
            logger.error("Error reading events: %s", exc)
        finally:
            logger.info("Event reader stopped")

    async def _broadcast_event(self, event: dict[str, Any]) -> None:
        stale_subscribers: list[asyncio.Queue[dict[str, Any]]] = []
        for queue in list(self.subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                stale_subscribers.append(queue)
        for queue in stale_subscribers:
            self.unsubscribe(queue)
