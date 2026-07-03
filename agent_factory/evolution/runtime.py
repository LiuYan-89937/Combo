from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import shutil
import threading
from typing import Any
from uuid import uuid4

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from agent_factory.create_agent.models import CreateAgentAction, initial_system_manufacturing_state
from agent_factory.create_agent.runtime import (
    _ModelTraceAccumulator,
    _is_model_cache_chunk,
    _json_safe,
    _tool_trace_records,
)
from agent_factory.create_agent.output_safety import looks_like_internal_observation_text
from agent_factory.create_agent.tooling import CreateAgentToolEnvironmentBuilder
from agent_factory.create_agent.validation_state import package_fingerprint
from agent_factory.create_agent.workflow import CreateAgentWorkflow
from agent_factory.create_agent.workspace import CreateAgentWorkspace
from agent_factory.evolution.trace_gate import decide_trace_relevance
from agent_factory.evolution.target_gate import decide_evolution_target
from agent_factory.factory_graph.frontend_bridge.event_normalizer import RuntimeEventNormalizer
from agent_factory.factory_graph.frontend_bridge.protocol import FactoryFrontendEvent
from agent_factory.factory_graph.frontend_bridge.runtime_adapter_support import extract_interrupt_payload
from agent_factory.factory_graph.session import build_factory_checkpointer_handle
from agent_factory.model_pool.runtime_override import (
    RUNTIME_MAIN_MODEL_PROFILE_ID_KEY,
    main_model_profile_id_from_user_config,
)
from agent_factory.paths import factory_artifact_path, project_root
from agent_factory.runtime_attachments import ATTACHMENT_INPUT_DIR, import_runtime_attachments, time_named_attachment_scope
from agent_factory.runtime_contracts import AgentPackageLoader
from agent_factory.trace_system.diagnostics import TraceDiagnostics
from agent_factory.trace_system.projector import TraceProjector
from agent_factory.trace_system.reader import TraceReader
from agent_factory.trace_system.schema import RepairTracePack, TraceRunFilter


@dataclass(frozen=True, slots=True)
class AgentEvolutionStreamRun:
    package_id: str
    trace_id: str | None
    events: Iterator[tuple[str, Any]]


@dataclass(slots=True)
class _EvolutionRunContext:
    package_id: str
    trace_id: str | None
    user_input: str
    package_path: Path
    graph_thread_id: str
    backup_path: Path | None
    before_fingerprint: dict[str, str]
    runtime_attachments: list[dict[str, Any]]
    runtime_main_model_profile_id: str | None = None


class AgentEvolutionRuntime:
    def __init__(
        self,
        *,
        package_root: str | Path | None = None,
        runtime_root: str | Path | None = None,
        model: Any | None = None,
        tool_environment_builder: CreateAgentToolEnvironmentBuilder | None = None,
        checkpointer: Any | None = None,
    ) -> None:
        self.package_root = Path(package_root).expanduser() if package_root else factory_artifact_path("packages")
        self.runtime_root = Path(runtime_root).expanduser() if runtime_root else factory_artifact_path("agent_runtime")
        self.model = model
        self.tool_environment_builder = tool_environment_builder or CreateAgentToolEnvironmentBuilder()
        self.checkpointer = checkpointer or build_factory_checkpointer_handle().saver
        self._active_runs: dict[str, _EvolutionRunContext] = {}
        self._cancel_lock = threading.Lock()
        self._active_cancel_tokens: dict[str, threading.Event] = {}

    def stream(
        self,
        *,
        package_id: str,
        user_input: str,
        request_id: str | None,
        session_id: str | None,
        attachments: Any = None,
        user_config: dict[str, Any] | None = None,
    ) -> AgentEvolutionStreamRun:
        safe_package_id = _safe_id(package_id, label="package_id")
        trace_id = self.latest_failed_trace_id(safe_package_id)
        return AgentEvolutionStreamRun(
            package_id=safe_package_id,
            trace_id=trace_id,
            events=self._events(
                package_id=safe_package_id,
                trace_id=trace_id,
                user_input=user_input,
                request_id=request_id or uuid4().hex,
                session_id=session_id,
                resume_payload=None,
                attachments=attachments,
                user_config=user_config,
            ),
        )

    def resume_stream(
        self,
        *,
        package_id: str,
        session_id: str,
        resume_payload: dict[str, Any] | None,
        request_id: str | None,
    ) -> AgentEvolutionStreamRun:
        safe_package_id = _safe_id(package_id, label="package_id")
        active_context = self._active_runs.get(_active_run_key(session_id, safe_package_id))
        if active_context is None:
            raise RuntimeError(f"no active evolution run to resume: {safe_package_id}")
        trace_id = active_context.trace_id if active_context is not None else None
        return AgentEvolutionStreamRun(
            package_id=safe_package_id,
            trace_id=trace_id,
            events=self._events(
                package_id=safe_package_id,
                trace_id=trace_id,
                user_input="",
                request_id=request_id or uuid4().hex,
                session_id=session_id,
                resume_payload=resume_payload or {},
                attachments=None,
                user_config=None,
            ),
        )

    def cancel_active_requests(self, *, reason: str = "user_cancelled", request_id: str | None = None) -> int:
        del reason
        target = (request_id or "").strip()
        with self._cancel_lock:
            request_ids = [target] if target and target in self._active_cancel_tokens else list(self._active_cancel_tokens)
            for active_request_id in request_ids:
                self._active_cancel_tokens[active_request_id].set()
            return len(request_ids)

    def _register_cancel_token(self, request_id: str) -> threading.Event:
        token = threading.Event()
        with self._cancel_lock:
            self._active_cancel_tokens[request_id] = token
        return token

    def _forget_cancel_token(self, request_id: str, token: threading.Event) -> None:
        with self._cancel_lock:
            if self._active_cancel_tokens.get(request_id) is token:
                self._active_cancel_tokens.pop(request_id, None)

    def latest_failed_trace_id(self, package_id: str) -> str | None:
        safe_package_id = _safe_id(package_id, label="package_id")
        reader = TraceReader(self.runtime_root / safe_package_id / "trace")
        runs = reader.list_runs(TraceRunFilter(status=["failed"], limit=1))
        if not runs:
            return None
        return runs[0].trace_id

    def _events(
        self,
        *,
        package_id: str,
        trace_id: str | None,
        user_input: str,
        request_id: str,
        session_id: str | None,
        resume_payload: dict[str, Any] | None,
        attachments: Any,
        user_config: dict[str, Any] | None,
    ) -> Iterator[tuple[str, Any]]:
        cancel_token = self._register_cancel_token(request_id)
        pending_events: list[FactoryFrontendEvent] = []

        def emit_frontend(item: FactoryFrontendEvent) -> None:
            pending_events.append(item)

        def drain_events() -> Iterator[tuple[str, FactoryFrontendEvent]]:
            while pending_events:
                yield "frontend_event", pending_events.pop(0)

        normalizer = RuntimeEventNormalizer(
            emit=emit_frontend,
            request_id=request_id,
            session_id=session_id,
            mode="evolve_agent",
            graph_id="agent_evolution",
            producer_type="agent_evolution",
        )
        package_path = _safe_child(self.package_root, package_id)
        active_run_key = _active_run_key(session_id or request_id, package_id)
        context = self._active_runs.get(active_run_key) if resume_payload is not None else None
        if context is None:
            context = _EvolutionRunContext(
                package_id=package_id,
                trace_id=trace_id,
                user_input=user_input,
                package_path=package_path,
                graph_thread_id=_thread_id(f"{session_id or 'sessionless'}:{request_id}", package_id),
                backup_path=None,
                before_fingerprint={},
                runtime_attachments=[],
                runtime_main_model_profile_id=main_model_profile_id_from_user_config(user_config),
            )
        resolved_thread_id = context.graph_thread_id
        normalizer.emit_run_started({"package_id": package_id, "trace_id": context.trace_id})
        yield from drain_events()
        workspace = CreateAgentWorkspace(package_path)
        try:
            if not package_path.is_dir():
                raise RuntimeError(f"agent package not found: {package_id}")
            _ensure_evolution_managed_files(workspace)
            if resume_payload is None:
                context.backup_path = _backup_package(package_path, package_id=package_id)
                context.before_fingerprint = package_fingerprint(package_path)
                attachment_scope = time_named_attachment_scope()
                attachment_result = import_runtime_attachments(
                    context.user_input,
                    attachments,
                    storage_root=package_path / ".factory" / ATTACHMENT_INPUT_DIR / attachment_scope,
                    runtime_path_root=f".factory/{ATTACHMENT_INPUT_DIR}/{attachment_scope}",
                    base_dir=project_root(),
                    scope=attachment_scope,
                )
                context.user_input = attachment_result.message
                context.runtime_attachments = attachment_result.attachments
                self._active_runs[active_run_key] = context
            package = AgentPackageLoader().load_path(package_path / "agent_package.json")
            if context.trace_id:
                repair_pack = _repair_pack(self.runtime_root, package_id=package_id, trace_id=context.trace_id)
                error_pack = _error_only_pack(repair_pack)
                trace_gate = decide_trace_relevance(user_goal=context.user_input, error_pack=error_pack)
                trace_context = trace_gate.model_dump(mode="json")
                provided_error_pack = error_pack if trace_gate.provide_trace else {}
            else:
                error_pack = {}
                provided_error_pack = {}
                trace_context = {
                    "provided": False,
                    "reason": "no failed trace is available for this package; evolution will use the user goal and package state only",
                }
            package_summary = _package_summary(package_id, package_path, package)
            target_plan = decide_evolution_target(
                user_goal=context.user_input,
                package_summary=package_summary,
                trace_context=trace_context,
                error_pack=provided_error_pack,
            )
            if resume_payload is None:
                workspace.reset_evolution_trace(
                    session_id=session_id,
                    request_id=request_id,
                    graph_id="agent_evolution",
                    package_id=package_id,
                    trace_id=context.trace_id,
                    target_plan=target_plan.to_context(),
                )
            trace_sequence = workspace.evolution_trace_record_count()

            def record_trace(kind: str, payload: dict[str, Any]) -> None:
                nonlocal trace_sequence
                trace_sequence += 1
                workspace.append_evolution_trace_record(
                    {
                        "sequence": trace_sequence,
                        "timestamp": datetime.now(UTC).isoformat(),
                        "kind": kind,
                        "session_id": session_id,
                        "request_id": request_id,
                        "graph_id": "agent_evolution",
                        "package_id": package_id,
                        **payload,
                    }
                )

            model_trace = _ModelTraceAccumulator(record_trace)

            def emit_cancelled() -> Iterator[tuple[str, FactoryFrontendEvent]]:
                model_trace.flush()
                normalizer.complete_open_model_streams(reason="user_stopped")
                if context.backup_path is not None and context.backup_path.exists():
                    _restore_package(context.backup_path, context.package_path)
                self._active_runs.pop(active_run_key, None)
                normalizer.runtime_event(
                    "node_completed",
                    node_id="agent_evolution",
                    node_label="Agent Evolution",
                    node_kind="create_agent_workflow",
                    payload={"package_id": package_id, "status": "stopped", "trace_id": context.trace_id},
                )
                record_trace(
                    "lifecycle",
                    {
                        "event_type": "run_completed",
                        "payload": {"status": "stopped", "package_id": package_id, "trace_id": context.trace_id},
                    },
                )
                normalizer.emit_run_completed(
                    {
                        "status": "stopped",
                        "package_id": package_id,
                        "trace_id": context.trace_id,
                        "agent_session": {"session_id": session_id} if session_id else {},
                    }
                )
                yield from drain_events()

            record_trace(
                "lifecycle",
                {
                    "event_type": "run_started",
                    "payload": {
                        "package_id": package_id,
                        "trace_id": context.trace_id,
                        "package_path": str(package_path),
                        "trace_gate": _json_safe(trace_context),
                        "target_plan": _json_safe(target_plan.to_context()),
                    },
                },
            )
            if cancel_token.is_set():
                yield from emit_cancelled()
                return
            if target_plan.surface == "runtime_blocker":
                record_trace(
                    "lifecycle",
                    {
                        "event_type": "runtime_blocked",
                        "success": False,
                        "payload": _json_safe(target_plan.to_context()),
                    },
                )
                if context.backup_path is not None:
                    shutil.rmtree(context.backup_path, ignore_errors=True)
                self._active_runs.pop(active_run_key, None)
                normalizer.complete_visible_assistant_output_from_text(
                    "本次进化被运行环境问题阻塞，不能通过修改 AgentPackage 解决。请先处理 runtime/Docker/model infrastructure blocker。",
                    node_id="agent_evolution",
                    reason="runtime_blocked",
                )
                normalizer.emit_run_completed(
                    {
                        "status": "blocked",
                        "package_id": package_id,
                        "trace_id": context.trace_id,
                        "target_plan": target_plan.to_context(),
                    }
                )
                yield from drain_events()
                return
            tool_env = self.tool_environment_builder.build(
                workspace_root=package_path,
                mode="evolution",
                evolution_target_plan=target_plan.to_context(),
            )
            normalizer.runtime_event(
                "node_started",
                node_id="agent_evolution",
                node_label="Agent Evolution",
                node_kind="create_agent_workflow",
                payload={
                    "package_id": package_id,
                    "trace_id": context.trace_id,
                    "package_path": str(package_path),
                    "tool_ids": tool_env.tool_ids,
                    "extension_report": tool_env.extension_report,
                    "trace_gate": trace_context,
                    "target_plan": target_plan.to_context(),
                },
            )
            record_trace(
                "lifecycle",
                {
                    "event_type": "node_started",
                    "node_id": "agent_evolution",
                    "node_label": "Agent Evolution",
                    "payload": {
                        "package_id": package_id,
                        "tool_ids": tool_env.tool_ids,
                        "target_plan": _json_safe(target_plan.to_context()),
                    },
                },
            )
            yield from drain_events()
            if cancel_token.is_set():
                yield from emit_cancelled()
                return
            workflow = CreateAgentWorkflow(
                tools=tool_env.tools,
                model=self.model,
                capability_inventory=tool_env.capability_inventory,
                workflow_kind="evolution",
            ).compile(checkpointer=self.checkpointer)
            if resume_payload is None:
                stream_input: Any = {
                    "request": context.user_input,
                    "workspace_path": str(package_path),
                    "runtime_attachments": context.runtime_attachments,
                    RUNTIME_MAIN_MODEL_PROFILE_ID_KEY: context.runtime_main_model_profile_id or "",
                    "graph_kind": "evolution",
                    "evolution_context": {
                        "package_id": package_id,
                        "package_path": str(package_path),
                        "package_summary": package_summary,
                        "trace_gate": trace_context,
                        "target_plan": target_plan.to_context(),
                        **({"error_pack": provided_error_pack} if provided_error_pack else {}),
                    },
                    "iteration": 0,
                    "done": False,
                    "messages": [HumanMessage(content=context.user_input)],
                }
            else:
                stream_input = Command(resume=resume_payload)
                normalizer.emit_runtime_resumed(resume_payload)
                record_trace("lifecycle", {"event_type": "runtime_resumed", "payload": _json_safe(resume_payload)})
                yield from drain_events()
            final_state: dict[str, Any] | None = None
            config = {"configurable": {"thread_id": resolved_thread_id}}
            stream_iter = workflow.stream(
                stream_input,
                config=config,
                stream_mode=["messages", "custom", "values"],
            )
            try:
                for stream_mode, chunk in stream_iter:
                    if cancel_token.is_set():
                        yield from emit_cancelled()
                        return
                    interrupt_payload = extract_interrupt_payload(chunk)
                    if interrupt_payload is not None:
                        normalizer.emit_interrupt(interrupt_payload)
                        record_trace(
                            "lifecycle",
                            {"event_type": "interrupt_requested", "payload": _json_safe(interrupt_payload)},
                        )
                        model_trace.flush()
                        yield from drain_events()
                        return
                    if stream_mode == "values" and isinstance(chunk, dict):
                        final_state = chunk
                        continue
                    if stream_mode == "messages":
                        model_trace.accept(chunk)
                    if stream_mode == "custom":
                        model_trace.flush()
                        if _is_model_cache_chunk(chunk):
                            record_trace("model_cache", _json_safe(chunk.get("payload") or {}))
                            continue
                        for record in _tool_trace_records(chunk):
                            record_trace("tool_call", record)
                    normalizer.emit_stream_item(stream_mode, chunk, updates_payload_key="evolution_update")
                    yield from drain_events()
            finally:
                close = getattr(stream_iter, "close", None)
                if callable(close):
                    close()
            model_trace.flush()
            if not final_state:
                raise RuntimeError("agent evolution workflow did not produce final state")
            if not final_state.get("done"):
                raise RuntimeError("agent evolution workflow stopped before completion")
            changed_files = _changed_files(context.before_fingerprint, package_fingerprint(package_path))
            final_answer = _safe_evolution_summary(str(final_state.get("final_answer") or ""))
            report_path = _write_evolution_publish_report(
                package_path=package_path,
                package_id=package_id,
                trace_id=context.trace_id,
                user_input=context.user_input,
                summary=final_answer,
                changed_files=changed_files,
                validation=final_state.get("validation") if isinstance(final_state.get("validation"), dict) else {},
            )
            if context.backup_path is not None:
                shutil.rmtree(context.backup_path, ignore_errors=True)
            self._active_runs.pop(active_run_key, None)
            normalizer.runtime_event(
                "node_completed",
                node_id="agent_evolution",
                node_label="Agent Evolution",
                node_kind="create_agent_workflow",
                payload={"package_id": package_id, "changed_files": changed_files, "report_path": str(report_path)},
            )
            record_trace(
                "lifecycle",
                {
                    "event_type": "node_completed",
                    "node_id": "agent_evolution",
                    "node_label": "Agent Evolution",
                    "payload": {
                        "package_id": package_id,
                        "changed_files": changed_files,
                        "report_path": str(report_path),
                    },
                },
            )
            normalizer.complete_visible_assistant_output_from_text(
                final_answer,
                node_id="agent_evolution",
                reason="run_completed",
            )
            normalizer.emit_run_completed(
                {
                    "status": "published",
                    "package_id": package_id,
                    "trace_id": context.trace_id,
                    "changed_files": changed_files,
                    "report_path": str(report_path),
                }
            )
            record_trace(
                "lifecycle",
                {
                    "event_type": "run_completed",
                    "payload": {
                        "status": "published",
                        "package_id": package_id,
                        "trace_id": context.trace_id,
                        "changed_files": changed_files,
                        "report_path": str(report_path),
                    },
                },
            )
            yield from drain_events()
        except Exception as exc:
            failed_trace_payload = _evolution_trace_payload_with_record(
                workspace,
                {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "kind": "lifecycle",
                    "session_id": session_id,
                    "request_id": request_id,
                    "graph_id": "agent_evolution",
                    "package_id": package_id,
                    "event_type": "run_failed",
                    "success": False,
                    "message": f"{type(exc).__name__}: {exc}",
                    "payload": {"package_path": str(package_path)},
                },
            )
            if context.backup_path is not None and context.backup_path.exists():
                _restore_package(context.backup_path, package_path)
            if failed_trace_payload is not None:
                _write_evolution_trace_payload(workspace, failed_trace_payload)
            self._active_runs.pop(active_run_key, None)
            normalizer.emit_run_failed(exc)
            yield from drain_events()
        finally:
            self._forget_cancel_token(request_id, cancel_token)


def _ensure_evolution_managed_files(workspace: CreateAgentWorkspace) -> None:
    workspace.root.mkdir(parents=True, exist_ok=True)
    workspace.factory_dir.mkdir(parents=True, exist_ok=True)
    if not workspace.system_state_path.exists():
        workspace.write_system_state(initial_system_manufacturing_state())
    workspace.write_action(CreateAgentAction())
    if not workspace.resources_path.exists():
        workspace._write_json(workspace.resources_path, {"version": "resource_facts.v0", "facts": []})


def _repair_pack(runtime_root: Path, *, package_id: str, trace_id: str) -> RepairTracePack:
    diagnostics = TraceDiagnostics(TraceProjector(TraceReader(runtime_root / package_id / "trace")))
    return diagnostics.build_repair_pack(trace_id)


def _error_only_pack(pack: RepairTracePack) -> dict[str, Any]:
    return {
        "trace_id": pack.trace_id,
        "run_id": pack.run_id,
        "status": pack.status,
        "failed_node": pack.failed_node,
        "failed_span_id": pack.failed_span_id,
        "failure_category": pack.failure_category,
        "error_chain": [item.model_dump(mode="json") for item in pack.error_chain],
        "suspected_root_causes": pack.suspected_root_causes,
        "repair_targets": pack.repair_targets,
    }


def _package_summary(package_id: str, package_path: Path, package: Any) -> dict[str, Any]:
    return {
        "package_id": package_id,
        "package_path": str(package_path),
        "agent_id": package.assembly_spec.agent.id,
        "agent_name": package.assembly_spec.agent.name,
        "agent_description": package.assembly_spec.agent.description,
        "pattern_id": package.assembly_spec.runtime.pattern_id,
        "tool_ids": [tool.id for tool in package.assembly_spec.tools],
        "contract_keys": sorted(package.contracts.keys()),
    }


def _backup_package(package_path: Path, *, package_id: str) -> Path:
    root = package_path.parent / ".evolution_backups"
    root.mkdir(parents=True, exist_ok=True)
    backup_path = root / f"{package_id}-{uuid4().hex}"
    shutil.copytree(package_path, backup_path)
    return backup_path


def _restore_package(backup_path: Path, package_path: Path) -> None:
    if package_path.exists():
        shutil.rmtree(package_path)
    shutil.copytree(backup_path, package_path)
    shutil.rmtree(backup_path, ignore_errors=True)


def _changed_files(before: dict[str, str], after: dict[str, str]) -> list[str]:
    keys = sorted(set(before) | set(after))
    return [key for key in keys if before.get(key) != after.get(key)]


def _write_evolution_publish_report(
    *,
    package_path: Path,
    package_id: str,
    trace_id: str | None,
    user_input: str,
    summary: str,
    changed_files: list[str],
    validation: dict[str, Any],
) -> Path:
    now = datetime.now(UTC).isoformat()
    report_path = package_path / "package_report.json"
    previous: dict[str, Any] = {}
    if report_path.is_file():
        try:
            value = json.loads(report_path.read_text(encoding="utf-8"))
            previous = value if isinstance(value, dict) else {}
        except Exception:
            previous = {}
    evolution_history = list(previous.get("evolution_history") or []) if isinstance(previous.get("evolution_history"), list) else []
    evolution_history.append(
        {
            "version": "agent_evolution_publish.v0",
            "package_id": package_id,
            "trace_id": trace_id,
            "user_goal": user_input,
            "summary": summary,
            "changed_files": changed_files,
            "validation": validation,
            "published_at": now,
        }
    )
    report = {
        **previous,
        "version": previous.get("version") or "agent_package_publish_report.v0",
        "status": "available",
        "package_id": package_id,
        "package_path": str(package_path),
        "manifest_path": str(package_path / "agent_package.json"),
        "published_at": now,
        "package_fingerprint": package_fingerprint(package_path),
        "last_evolution": evolution_history[-1],
        "evolution_history": evolution_history[-20:],
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report_path


def _safe_evolution_summary(value: str) -> str:
    text = str(value or "").strip()
    if text and not looks_like_internal_observation_text(text):
        return text
    return "AgentPackage 进化已完成并自动发布。"


def _safe_id(value: str, *, label: str) -> str:
    raw = str(value).strip()
    if not raw:
        raise RuntimeError(f"{label} must not be empty")
    if raw in {".", ".."} or "/" in raw or "\\" in raw:
        raise RuntimeError(f"invalid {label}: {value}")
    return raw


def _safe_child(root: Path, child: str) -> Path:
    target = (root / child).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise RuntimeError(f"path escapes root: {child}") from exc
    return target


def _thread_id(session_id: str, package_id: str) -> str:
    return f"{session_id}:evolution:{package_id}"


def _active_run_key(session_id: str, package_id: str) -> str:
    return f"{session_id}:evolution-active:{package_id}"


def _evolution_trace_payload_with_record(workspace: CreateAgentWorkspace, record: dict[str, Any]) -> dict[str, Any] | None:
    try:
        path = workspace.manufacturing_trace_path
        payload = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        if not isinstance(payload, dict) or payload.get("version") != "agent_evolution_manufacturing_trace.v0":
            payload = {
                "version": "agent_evolution_manufacturing_trace.v0",
                "workspace_path": str(workspace.root),
                "created_at": datetime.now(UTC).isoformat(),
                "records": [],
            }
        records = payload.get("records")
        if not isinstance(records, list):
            records = []
            payload["records"] = records
        records.append({"sequence": len(records) + 1, **record})
        payload["updated_at"] = datetime.now(UTC).isoformat()
        return payload
    except Exception:
        return None


def _write_evolution_trace_payload(workspace: CreateAgentWorkspace, payload: dict[str, Any]) -> None:
    try:
        workspace._write_json(workspace.manufacturing_trace_path, payload)
    except Exception:
        pass
