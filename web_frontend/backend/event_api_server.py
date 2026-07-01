"""
FastAPI Event/API Server - FastAgentFactory Web Frontend Bridge

这是一个轻量级的交互层，负责：
1. 通过 SSE 将 FactoryFrontendEvent 推送给前端
2. 通过 HTTP API 接收 FactoryFrontendCommand
3. 将资源、配置、任务等管理类操作暴露为普通 HTTP API

不修改核心后端逻辑，只作为通信桥梁。
"""
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
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import ValidationError
from starlette.background import BackgroundTask

# 动态导入协议定义
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from agent_factory.env import load_agentfactory_dotenv
from agent_factory.factory_graph.frontend_bridge.agent_package_runtime import AgentPackageRuntimeManager
from agent_factory.factory_graph.frontend_bridge.protocol import (
    FactoryFrontendCommand,
    FactoryFrontendEvent,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
load_agentfactory_dotenv()

app = FastAPI(title="FastAgentFactory Web Bridge")

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应限制为具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RuntimeBridge:
    """管理与后端 stdio_server 的通信"""

    def __init__(self):
        self.process: subprocess.Popen | None = None
        self.event_history: deque[dict[str, Any]] = deque(maxlen=500)
        self.subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self.command_lock = asyncio.Lock()
        self._reader_task: asyncio.Task | None = None
        self._running = False

    async def start(self):
        """启动后端 stdio_server 进程"""
        if self.process is not None:
            logger.warning("Runtime bridge already started")
            return

        # 启动后端 stdio_server
        python_exec = sys.executable
        stdio_server_path = (
            Path(__file__).parent.parent.parent
            / "agent_factory"
            / "factory_graph"
            / "frontend_bridge"
            / "stdio_server.py"
        )

        logger.info(f"Starting stdio_server: {stdio_server_path}")
        self.process = subprocess.Popen(
            [python_exec, str(stdio_server_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        self._running = True
        # 启动异步读取任务
        self._reader_task = asyncio.create_task(self._read_events())
        logger.info("Runtime bridge started")

    async def stop(self):
        """停止后端进程"""
        self._running = False
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass

        if self.process:
            try:
                # 发送 shutdown 命令
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

    async def send_command(self, command: dict[str, Any]):
        """发送命令到后端"""
        if not self.process or not self.process.stdin:
            raise RuntimeError("Runtime bridge not started")

        async with self.command_lock:
            try:
                command_json = json.dumps(command, ensure_ascii=False)
                logger.debug(f"Sending command: {command['type']}")
                self.process.stdin.write(command_json + "\n")
                self.process.stdin.flush()
            except Exception as e:
                logger.error(f"Failed to send command: {e}")
                raise

    async def _read_events(self):
        """从后端读取事件并放入队列"""
        if not self.process or not self.process.stdout:
            return

        loop = asyncio.get_event_loop()

        try:
            while self._running and self.process.poll() is None:
                # 在线程池中读取一行（避免阻塞事件循环）
                line = await loop.run_in_executor(None, self.process.stdout.readline)

                if not line:
                    break

                line = line.strip()
                if not line:
                    continue

                try:
                    event = json.loads(line)
                    logger.debug(f"Received event: {event.get('event_type', 'unknown')}")
                    self.event_history.append(event)
                    await self._broadcast_event(event)
                except json.JSONDecodeError as e:
                    logger.error(f"Invalid JSON from backend: {line[:100]}... Error: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error reading events: {e}")
        finally:
            logger.info("Event reader stopped")

    def subscribe(self, *, replay_history: bool = True) -> asyncio.Queue[dict[str, Any]]:
        """创建客户端专属事件队列。"""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)
        if replay_history:
            for event in self.event_history:
                queue.put_nowait(event)
        self.subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self.subscribers.discard(queue)

    async def _broadcast_event(self, event: dict[str, Any]) -> None:
        stale_subscribers: list[asyncio.Queue[dict[str, Any]]] = []
        for queue in list(self.subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                stale_subscribers.append(queue)
        for queue in stale_subscribers:
            self.unsubscribe(queue)

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


# 全局 runtime bridge 实例
runtime_bridge = RuntimeBridge()


@app.on_event("startup")
async def startup_event():
    """应用启动时启动 runtime bridge"""
    await runtime_bridge.start()


@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭时停止 runtime bridge"""
    await runtime_bridge.stop()


@app.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "ok",
        "runtime_bridge_active": runtime_bridge.process is not None
        and runtime_bridge.process.poll() is None,
    }


@app.get("/events")
async def events_endpoint(request: Request):
    """SSE 事件流端点。"""
    client_id = str(uuid.uuid4())[:8]
    event_queue = runtime_bridge.subscribe(replay_history=True)
    logger.info(f"SSE client {client_id} connected")

    async def event_stream():
        try:
            while not await request.is_disconnected():
                try:
                    event = await asyncio.wait_for(event_queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                message = {"kind": "factory_frontend_event", "event": event}
                data = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
                yield f"event: factory_frontend_event\ndata: {data}\n\n"
        finally:
            runtime_bridge.unsubscribe(event_queue)
            logger.info(f"SSE client {client_id} disconnected")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/commands")
async def command_endpoint(payload: dict[str, Any]):
    """运行类命令入口。长运行结果通过 SSE 返回。"""
    try:
        command = FactoryFrontendCommand.model_validate(payload.get("command", payload))
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await runtime_bridge.send_frontend_command(command)
    logger.info(f"HTTP command sent: {command.type}")
    return {"accepted": True, "command": command.model_dump(mode="json")}


@app.get("/api/agent-packages")
async def list_agent_packages():
    event = await _send_and_wait("list_agent_packages", {}, {"agent_packages_listed"})
    return {"event": event}


@app.post("/api/agent-packages/select")
async def select_agent_package(payload: dict[str, Any]):
    event = await _send_and_wait("select_agent_package", payload, {"agent_package_selected"})
    return {"event": event}


@app.get("/api/agent-packages/instances")
async def list_agent_package_instances():
    event = await _send_and_wait(
        "list_agent_package_instances",
        {},
        {"agent_package_instances_listed"},
    )
    return {"event": event}


@app.get("/api/agent-packages/recent-sessions")
async def list_recent_agent_package_sessions(limit: int = Query(default=5, ge=1, le=20)):
    runtime = AgentPackageRuntimeManager()
    sessions: list[dict[str, Any]] = []
    for package in runtime.list_packages():
        package_id = str(package.get("package_id") or "").strip()
        if not package_id:
            continue
        package_name = str(package.get("agent_name") or package.get("name") or package_id)
        try:
            package_sessions = runtime.list_sessions(package_id)
        except Exception as exc:
            logger.warning("Failed to list sessions for package %s: %s", package_id, exc)
            continue
        for session in package_sessions:
            item = dict(session)
            item["package_id"] = package_id
            item["package_name"] = package_name
            item["agent_name"] = package_name
            sessions.append(item)
    sessions.sort(key=_session_updated_sort_key, reverse=True)
    return {"sessions": sessions[:limit]}


@app.post("/api/agent-packages/{package_id}/initialize")
async def initialize_agent_package(package_id: str):
    event = await _send_and_wait(
        "initialize_agent_package",
        {"package_id": package_id},
        {"agent_package_instance_updated"},
        timeout_seconds=180.0,
    )
    return {"event": event}


@app.post("/api/agent-packages/{package_id}/shutdown")
async def shutdown_agent_package_instance(package_id: str):
    event = await _send_and_wait(
        "shutdown_agent_package_instance",
        {"package_id": package_id},
        {"agent_package_instance_updated"},
    )
    return {"event": event}


@app.delete("/api/agent-packages/{package_id}")
async def delete_agent_package(package_id: str):
    event = await _send_and_wait("delete_agent_package", {"package_id": package_id}, {"agent_package_deleted"})
    return {"event": event}


@app.get("/api/agent-packages/{package_id}/export")
async def export_agent_package(package_id: str):
    try:
        archive_path = AgentPackageRuntimeManager().export_package_archive(package_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    filename = f"{package_id}.zip"
    quoted_filename = quote(filename)
    return FileResponse(
        archive_path,
        media_type="application/zip",
        filename=filename,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quoted_filename}"},
        background=BackgroundTask(_unlink_file, archive_path),
    )


@app.get("/api/agent-packages/{package_id}/sessions")
async def list_agent_package_sessions(package_id: str):
    event = await _send_and_wait(
        "list_agent_package_sessions",
        {"package_id": package_id},
        {"agent_package_sessions_listed"},
    )
    return {"event": event}


@app.get("/api/agent-packages/{package_id}/sessions/{session_id}")
async def load_agent_package_session(package_id: str, session_id: str):
    event = await _send_and_wait(
        "load_agent_package_session",
        {"package_id": package_id, "session_id": session_id},
        {"agent_package_session_loaded"},
    )
    return {"event": event}


@app.get("/api/workspace/roots")
async def workspace_roots(package_id: str | None = None):
    event = await _resource_command(
        "workspace_manage",
        {"action": "roots", **_optional_package(package_id)},
        {"workspace_roots_listed"},
    )
    return {"event": event}


@app.get("/api/workspace/entries")
async def workspace_entries(
    scope: str = "workdir",
    path: str = "",
    package_id: str | None = None,
):
    event = await _resource_command(
        "workspace_manage",
        {"action": "list", "scope": scope, "path": path, **_optional_package(package_id)},
        {"workspace_entries_listed"},
    )
    return {"event": event}


@app.get("/api/workspace/file")
async def workspace_file(
    scope: str = "workdir",
    path: str = "",
    max_chars: int = Query(default=120000, ge=1000, le=200000),
    package_id: str | None = None,
):
    event = await _resource_command(
        "workspace_manage",
        {
            "action": "read",
            "scope": scope,
            "path": path,
            "max_chars": max_chars,
            **_optional_package(package_id),
        },
        {"workspace_file_read"},
    )
    return {"event": event}


@app.get("/api/knowledge/sources")
async def list_knowledge_sources(package_id: str | None = None):
    event = await _resource_command(
        "knowledge_manage",
        {"action": "list_sources", **_optional_package(package_id)},
        {"knowledge_sources_listed"},
    )
    return {"event": event}


@app.post("/api/knowledge/sources")
async def create_knowledge_source(payload: dict[str, Any]):
    event = await _resource_command(
        "knowledge_manage",
        {"action": "confirm_source", **payload},
        {"knowledge_source_registered"},
        timeout_seconds=120.0,
    )
    return {"event": event}


@app.delete("/api/knowledge/sources/{source_id}")
async def delete_knowledge_source(source_id: str, package_id: str | None = None):
    event = await _resource_command(
        "knowledge_manage",
        {"action": "remove_source", "source_id": source_id, **_optional_package(package_id)},
        {"knowledge_source_removed"},
    )
    return {"event": event}


@app.post("/api/knowledge/sources/{source_id}/reindex")
async def reindex_knowledge_source(source_id: str, package_id: str | None = None):
    event = await _resource_command(
        "knowledge_manage",
        {"action": "reindex", "source_id": source_id, **_optional_package(package_id)},
        {"knowledge_source_reindex_requested"},
        timeout_seconds=120.0,
    )
    return {"event": event}


@app.get("/api/knowledge/documents")
async def list_knowledge_documents(source_id: str, package_id: str | None = None):
    event = await _resource_command(
        "knowledge_manage",
        {"action": "list_documents", "source_id": source_id, **_optional_package(package_id)},
        {"knowledge_documents_listed"},
    )
    return {"event": event}


@app.get("/api/knowledge/search")
async def search_knowledge(
    query: str,
    source_id: str | None = None,
    package_id: str | None = None,
):
    payload = {"action": "search", "query": query, **_optional_package(package_id)}
    if source_id:
        payload["source_id"] = source_id
    event = await _resource_command("knowledge_manage", payload, {"knowledge_search_completed"})
    return {"event": event}


@app.get("/api/knowledge/document")
async def read_knowledge_document(document_id: str, package_id: str | None = None):
    event = await _resource_command(
        "knowledge_manage",
        {"action": "read", "document_id": document_id, **_optional_package(package_id)},
        {"knowledge_document_read"},
    )
    return {"event": event}


@app.get("/api/extensions")
async def list_extensions(package_id: str | None = None):
    event = await _resource_command(
        "extensions_manage",
        {"action": "list", **_optional_package(package_id)},
        {"extension_configs_listed"},
    )
    return {"event": event}


@app.post("/api/extensions/mcp")
async def save_mcp(payload: dict[str, Any]):
    event = await _resource_command(
        "extensions_manage",
        {"action": "upsert_mcp", **payload},
        {"extension_config_updated"},
    )
    return {"event": event}


@app.post("/api/extensions/mcp/test")
async def test_mcp(payload: dict[str, Any]):
    event = await _resource_command(
        "extensions_manage",
        {"action": "test_mcp", **payload},
        {"extension_config_tested"},
        timeout_seconds=60.0,
    )
    return {"event": event}


@app.patch("/api/extensions/mcp/{server_id}")
async def set_mcp_enabled(server_id: str, payload: dict[str, Any]):
    event = await _resource_command(
        "extensions_manage",
        {
            "action": "set_mcp_enabled",
            "server_id": server_id,
            "enabled": payload.get("enabled", True),
            **_optional_package(payload.get("package_id")),
        },
        {"extension_config_updated"},
    )
    return {"event": event}


@app.delete("/api/extensions/mcp/{server_id}")
async def remove_mcp(server_id: str, package_id: str | None = None):
    event = await _resource_command(
        "extensions_manage",
        {"action": "remove_mcp", "server_id": server_id, **_optional_package(package_id)},
        {"extension_config_updated"},
    )
    return {"event": event}


@app.post("/api/extensions/skills")
async def save_skill(payload: dict[str, Any]):
    package_id = payload.get("package_id")
    event = await _resource_command(
        "extensions_manage",
        {
            "action": "upsert_skill",
            "skill": payload.get("skill") if isinstance(payload.get("skill"), dict) else payload,
            "replace_skill_id": payload.get("replace_skill_id"),
            **_optional_package(package_id),
        },
        {"extension_config_updated"},
    )
    return {"event": event}


@app.patch("/api/extensions/skills/{skill_id}")
async def set_skill_enabled(skill_id: str, payload: dict[str, Any]):
    event = await _resource_command(
        "extensions_manage",
        {
            "action": "set_skill_enabled",
            "skill_id": skill_id,
            "enabled": payload.get("enabled", True),
            **_optional_package(payload.get("package_id")),
        },
        {"extension_config_updated"},
    )
    return {"event": event}


@app.delete("/api/extensions/skills/{skill_id}")
async def remove_skill(skill_id: str, package_id: str | None = None):
    event = await _resource_command(
        "extensions_manage",
        {"action": "remove_skill", "skill_id": skill_id, **_optional_package(package_id)},
        {"extension_config_updated"},
    )
    return {"event": event}


@app.get("/api/scheduler/jobs")
async def scheduler_jobs(package_id: str | None = None):
    event = await _resource_command(
        "scheduler_manage",
        {"action": "list", **_optional_package(package_id)},
        {"scheduler_jobs_listed"},
    )
    return {"event": event}


@app.get("/api/scheduler/options")
async def scheduler_options(package_id: str | None = None):
    event = await _resource_command(
        "scheduler_manage",
        {"action": "options", **_optional_package(package_id)},
        {"scheduler_options_listed"},
    )
    return {"event": event}


@app.post("/api/scheduler/jobs")
async def create_scheduler_job(payload: dict[str, Any]):
    package_id = payload.get("package_id")
    job_payload = payload.get("job") if isinstance(payload.get("job"), dict) else {
        key: value for key, value in payload.items() if key != "package_id"
    }
    event = await _resource_command(
        "scheduler_manage",
        {"action": "create", "job": job_payload, **_optional_package(package_id)},
        {"scheduler_job_created"},
    )
    return {"event": event}


@app.get("/api/scheduler/jobs/{job_id}")
async def describe_scheduler_job(job_id: str, package_id: str | None = None):
    event = await _resource_command(
        "scheduler_manage",
        {"action": "describe", "job_id": job_id, **_optional_package(package_id)},
        {"scheduler_job_described"},
    )
    return {"event": event}


@app.get("/api/scheduler/runs")
async def scheduler_runs(
    job_id: str | None = None,
    package_id: str | None = None,
    limit: int = Query(default=20, ge=1, le=200),
):
    payload: dict[str, Any] = {"action": "runs", "limit": limit, **_optional_package(package_id)}
    if job_id:
        payload["job_id"] = job_id
    event = await _resource_command("scheduler_manage", payload, {"scheduler_runs_listed"})
    return {"event": event}


@app.post("/api/scheduler/jobs/{job_id}/pause")
async def pause_scheduler_job(job_id: str, payload: dict[str, Any] | None = None):
    event = await _resource_command(
        "scheduler_manage",
        {"action": "pause", "job_id": job_id, **_optional_package((payload or {}).get("package_id"))},
        {"scheduler_job_updated"},
    )
    return {"event": event}


@app.post("/api/scheduler/jobs/{job_id}/resume")
async def resume_scheduler_job(job_id: str, payload: dict[str, Any] | None = None):
    event = await _resource_command(
        "scheduler_manage",
        {"action": "resume", "job_id": job_id, **_optional_package((payload or {}).get("package_id"))},
        {"scheduler_job_updated"},
    )
    return {"event": event}


@app.delete("/api/scheduler/jobs/{job_id}")
async def delete_scheduler_job(job_id: str, package_id: str | None = None):
    event = await _resource_command(
        "scheduler_manage",
        {"action": "delete", "job_id": job_id, **_optional_package(package_id)},
        {"scheduler_job_deleted"},
    )
    return {"event": event}


@app.post("/api/scheduler/jobs/{job_id}/run")
async def run_scheduler_job_now(job_id: str, payload: dict[str, Any] | None = None):
    command = FactoryFrontendCommand(
        type="scheduler_manage",
        request_id=_request_id(),
        payload={"action": "run_now", "job_id": job_id, **_optional_package((payload or {}).get("package_id"))},
    )
    await runtime_bridge.send_frontend_command(command)
    return {"accepted": True, "command": command.model_dump(mode="json")}


async def _resource_command(
    command_type: str,
    payload: dict[str, Any],
    event_types: set[str],
    *,
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    return await _send_and_wait(command_type, payload, event_types, timeout_seconds=timeout_seconds)


async def _send_and_wait(
    command_type: str,
    payload: dict[str, Any],
    event_types: set[str],
    *,
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    command = FactoryFrontendCommand(type=command_type, request_id=_request_id(), payload=payload)
    return await runtime_bridge.send_and_wait(command, event_types=event_types, timeout_seconds=timeout_seconds)


def _request_id() -> str:
    return f"http-{uuid.uuid4().hex}"


def _optional_package(package_id: str | None) -> dict[str, str]:
    return {"package_id": package_id} if package_id else {}


def _session_updated_sort_key(session: dict[str, Any]) -> str:
    return str(session.get("updated_at") or session.get("created_at") or "")


def _unlink_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("Failed to remove temporary file: %s", path)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
