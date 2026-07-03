from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
import threading
from typing import Any, Callable

from agent_factory.assembly.compiler import AgentAssemblyCompiler
from agent_factory.factory_graph.frontend_bridge.event_normalizer import RuntimeEventNormalizer, json_safe
from agent_factory.factory_graph.frontend_bridge.protocol import FactoryFrontendEvent, event
from agent_factory.factory_graph.frontend_bridge.runtime_adapter_support import interrupt_payload
from agent_factory.runtime_contracts import LoadedAgentPackage, RuntimeBuildPlanner
from agent_factory.runtime_contracts.builtins import default_runtime_contract_registry
from agent_factory.runtime_kernel.background_workers import RuntimeBackgroundWorkerManager, WorkerLifecycleEvent
from agent_factory.runtime_kernel.kernel import RuntimeKernelFacade
from agent_factory.runtime_kernel.persistence import LangGraphCheckpointerConfig
from agent_factory.runtime_kernel.session import AgentSessionConfig
from agent_factory.runtime_protocol.completion import runtime_completed, runtime_error_message
from agent_factory.runtime_protocol.messages import incomplete_tool_call_ids
from agent_factory.scheduler_system import SchedulerExecutor, runtime_tool_runner, scheduler_tool_approval_override
from agent_factory.scheduler_system.events import SchedulerEventPayload
from agent_factory.scheduler_system.management import manage_scheduler_runtime
from agent_factory.scheduler_system.seeds import apply_scheduler_seed_contract
from agent_factory.knowledge_system.events import KNOWLEDGE_EVENT_TYPES
from agent_factory.memory_system import default_agent_memory_config
from agent_factory.package_runtime.request_lifecycle import RuntimeRequestPolicy
from agent_factory.package_runtime.session_turns import (
    resume_user_input,
    session_attachments_from_state,
    session_final_answer,
    session_reasoning_content,
    session_trace_ref,
    session_user_input_from_state,
)
from agent_factory.runtime_attachments import has_attachment_payload, merge_attachments_into_user_config


Emit = Callable[[FactoryFrontendEvent], None]


@dataclass(slots=True)
class CompiledPackageRuntime:
    package: LoadedAgentPackage
    compiled: Any
    facade: RuntimeKernelFacade


class PackageRuntimeCore:
    """Shared AgentPackage runtime compile/stream core.

    The core has no transport opinion. Docker stdio bridges and host
    SystemPackage handles can both feed commands into it and receive standard
    frontend events from the supplied emitter.
    """

    def __init__(
        self,
        *,
        package: LoadedAgentPackage,
        runtime_root: str | Path | None = None,
        emit_background: Emit | None = None,
        graph_id: str = "agent_package_runtime",
        producer_type: str = "agent_runtime",
        runtime_resources_override: dict[str, Any] | None = None,
    ) -> None:
        self.package = package
        self.runtime_root = Path(runtime_root).expanduser().resolve() if runtime_root is not None else None
        self.graph_id = graph_id
        self.producer_type = producer_type
        self.emit_background = emit_background
        self.runtime_resources_override = dict(runtime_resources_override or {})
        self.compiled_runtime: CompiledPackageRuntime | None = None
        self.background_workers = RuntimeBackgroundWorkerManager()
        self._compile_lock = threading.Lock()

    def set_runtime_resources_override(self, resources: dict[str, Any]) -> None:
        self.runtime_resources_override = dict(resources)
        if self.compiled_runtime is not None:
            self.compiled_runtime.compiled.compiled_app.services.runtime_resources.update(self.runtime_resources_override)

    def handle(self, command: dict[str, Any], *, emit: Emit) -> int:
        command_type = str(command.get("type") or "")
        request_id = str(command.get("request_id") or "") or None
        payload = command.get("payload") if isinstance(command.get("payload"), dict) else {}
        normalizer = RuntimeEventNormalizer(
            emit=emit,
            request_id=request_id,
            session_id=str(payload.get("session_id") or "") or None,
            mode="agent_package",
            graph_id=self.graph_id,
            producer_type=self.producer_type,
        )
        if command_type == "shutdown":
            self.shutdown()
            return 0
        if command_type == "initialize_runtime":
            try:
                runtime = self.ensure_compiled(normalizer)
                normalizer.runtime_event(
                    "agent_package_instance_updated",
                    payload=self._instance_status_payload(runtime=runtime, status="ready"),
                )
                return 0
            except Exception as exc:
                normalizer.runtime_event(
                    "agent_package_instance_updated",
                    severity="error",
                    payload=self._instance_status_payload(status="failed", error=f"{type(exc).__name__}: {exc}"),
                )
                return 1
        if command_type == "scheduler_manage":
            try:
                runtime = self.ensure_compiled(normalizer)
                self._manage_scheduler(normalizer=normalizer, payload=payload, runtime=runtime)
                return 0
            except Exception as exc:
                normalizer.runtime_event(
                    "error",
                    severity="error",
                    message=f"{type(exc).__name__}: {exc}",
                    payload={"message": str(exc), "error_type": type(exc).__name__},
                )
                return 1
        normalizer.emit_run_started({"command": command_type, "attachment_count": _attachment_count(payload)})
        try:
            if command_type == "list_sessions":
                return self._list_sessions(normalizer)
            if command_type == "run_message":
                return self._run_message(normalizer, payload)
            if command_type == "resume_interrupt":
                return self._resume_interrupt(normalizer, payload)
        except Exception as exc:
            normalizer.emit_run_failed(exc)
            return 1
        normalizer.runtime_event("error", severity="error", payload={"message": f"unknown command: {command_type}"})
        return 1

    def ensure_compiled(self, normalizer: RuntimeEventNormalizer) -> CompiledPackageRuntime:
        if self.compiled_runtime is not None:
            return self.compiled_runtime
        with self._compile_lock:
            if self.compiled_runtime is not None:
                return self.compiled_runtime
            normalizer.runtime_event(
                "node_started",
                node_id="package_compile",
                node_label="Package Compile",
                node_kind="system",
                payload={"manifest": str(self.package.manifest_path)},
            )
            runtime_root = _runtime_workspace_root(
                runtime_root=self.runtime_root,
                package_root=self.package.package_root,
            )
            facade = RuntimeKernelFacade(
                checkpointer_config=LangGraphCheckpointerConfig(
                    backend="sqlite",
                    path=runtime_root / "checkpoints" / "agent.sqlite",
                ),
                memory_system_config=_runtime_memory_config(runtime_root),
                session_config=AgentSessionConfig(root=runtime_root / "sessions"),
            )
            runtime_build = RuntimeBuildPlanner(registry=default_runtime_contract_registry()).build(
                self.package,
                base_services=facade.instance.services,
                runtime_root=self.runtime_root,
            )
            runtime_build.services.runtime_resources.update(self.runtime_resources_override)
            compiled = AgentAssemblyCompiler(facade=facade).compile(
                self.package.assembly_spec,
                runtime_build=runtime_build,
            )
            self.compiled_runtime = CompiledPackageRuntime(
                package=self.package,
                compiled=compiled,
                facade=facade,
            )
            self._configure_scheduler_runtime(runtime=self.compiled_runtime)
            self._configure_knowledge_runtime(runtime=self.compiled_runtime)
            self._apply_scheduler_seeds(runtime=self.compiled_runtime)
            self.background_workers.add_many(runtime_build.background_workers)
            for lifecycle_event in self.background_workers.start_all():
                if lifecycle_event.status == "failed":
                    self._emit_worker_lifecycle_failure(lifecycle_event)
            normalizer.runtime_event(
                "node_completed",
                node_id="package_compile",
                node_label="Package Compile",
                node_kind="system",
                payload={
                    "agent_id": self.package.assembly_spec.agent.id,
                    "package_id": self.package.package_root.name,
                },
            )
            return self.compiled_runtime

    def shutdown(self) -> None:
        for lifecycle_event in self.background_workers.shutdown_all():
            if lifecycle_event.status == "failed":
                self._emit_worker_lifecycle_failure(lifecycle_event)

    def _instance_status_payload(
        self,
        *,
        runtime: CompiledPackageRuntime | None = None,
        status: str,
        error: str | None = None,
    ) -> dict[str, Any]:
        package = runtime.package if runtime is not None else self.package
        payload: dict[str, Any] = {
            "package_id": package.package_root.name,
            "agent_id": package.assembly_spec.agent.id,
            "agent_name": package.assembly_spec.agent.name,
            "backend": self.producer_type,
            "status": status,
            "ready": status == "ready",
        }
        if error:
            payload["error"] = error
        return payload

    def _manage_scheduler(
        self,
        *,
        normalizer: RuntimeEventNormalizer,
        payload: dict[str, Any],
        runtime: CompiledPackageRuntime,
    ) -> None:
        scheduler_runtime = getattr(runtime.compiled.compiled_app.services, "scheduler_runtime", None)
        if scheduler_runtime is None:
            raise RuntimeError("scheduler runtime is not enabled for this package")
        tool_registry = getattr(runtime.compiled.compiled_app.services, "tool_registry", None)
        manage_scheduler_runtime(
            runtime=scheduler_runtime,
            payload=payload,
            tool_registry=tool_registry,
            emit=lambda scheduler_payload: normalizer.emit_custom_event(
                {"type": "scheduler_event", "payload": self._scheduler_event_payload(scheduler_payload)}
            ),
        )

    def _scheduler_event_payload(self, payload: SchedulerEventPayload) -> dict[str, Any]:
        value = payload.model_dump(mode="json")
        value["package_id"] = self.package.package_root.name
        value["package_name"] = self.package.assembly_spec.agent.name
        value["agent_id"] = self.package.assembly_spec.agent.id
        return value

    def _run_message(self, normalizer: RuntimeEventNormalizer, payload: dict[str, Any]) -> int:
        message = str(payload.get("message") or "").strip()
        if not message and not has_attachment_payload(payload.get("attachments")):
            normalizer.emit_run_failed(ValueError("run_message requires payload.message"))
            return 1
        runtime = self.ensure_compiled(normalizer)
        package = runtime.package
        compiled = runtime.compiled
        facade = runtime.facade
        session_config = dict(compiled.runtime_config["session_config"])
        if payload.get("session_id"):
            session_config["session_id"] = str(payload["session_id"])
        user_config = merge_attachments_into_user_config(
            _merged_config(compiled.runtime_config["user_config"], payload.get("user_config")),
            payload.get("attachments"),
        )
        run_context = facade.prepare_run_context(
            compiled.compiled_app,
            user_input=message,
            user_config=user_config,
            agent_config=compiled.runtime_config["agent_config"],
            session_config=session_config,
        )
        run_context.state.execution.timeout_seconds = RuntimeRequestPolicy.from_payload(
            payload.get("runtime_request")
        ).timeout_seconds
        normalizer.session_id = run_context.session_id
        if _emit_pending_checkpoint_interrupt(normalizer, compiled.compiled_app, run_context.thread_id):
            return 0
        missing_tool_call_ids = _checkpoint_incomplete_tool_call_ids(compiled.compiled_app, run_context.thread_id)
        if missing_tool_call_ids:
            normalizer.emit_run_failed(
                RuntimeError(
                    "agent session has incomplete tool call history; resume the pending tool interaction "
                    f"before sending a new message. missing_tool_call_ids={missing_tool_call_ids}"
                )
            )
            return 1
        final_state = None
        for stream_mode, chunk in facade.instance.controller.stream(
            compiled.compiled_app,
            run_context.state,
            thread_id=run_context.thread_id,
        ):
            if _handle_stream_item(normalizer, stream_mode, chunk):
                return 0
            if stream_mode == "runtime_final":
                final_state = chunk
        if final_state is None:
            normalizer.emit_run_failed(RuntimeError("agent runtime did not produce a final state"))
            return 1
        agent_session = _touch_session_turn_from_final_state(
            run_context,
            compiled,
            final_state,
            fallback_user_input=run_context.first_user_input,
            fallback_attachments=user_config.get("attachments"),
        )
        if not runtime_completed(final_state):
            return _emit_failed_runtime_final(
                normalizer,
                final_state,
                command="run_message",
                package=package,
                agent_session=agent_session.model_dump(mode="json"),
            )
        normalizer.complete_open_model_streams(reason="run_completed")
        normalizer.emit_final_answer_if_needed(final_state, reason="run_completed")
        normalizer.emit_run_completed(
            {
                "status": final_state.execution.finish_status,
                "command": "run_message",
                "package_id": package.package_root.name,
                "agent_id": package.assembly_spec.agent.id,
                "agent_session": agent_session.model_dump(mode="json"),
            }
        )
        return 0

    def _resume_interrupt(self, normalizer: RuntimeEventNormalizer, payload: dict[str, Any]) -> int:
        session_id = str(payload.get("session_id") or "").strip()
        resume_payload = payload.get("resume_payload")
        if not session_id:
            normalizer.emit_run_failed(ValueError("resume_interrupt requires payload.session_id"))
            return 1
        runtime = self.ensure_compiled(normalizer)
        package = runtime.package
        compiled = runtime.compiled
        facade = runtime.facade
        session_config = dict(compiled.runtime_config["session_config"])
        session_config["session_id"] = session_id
        normalizer.session_id = session_id
        normalizer.emit_runtime_resumed(resume_payload if isinstance(resume_payload, dict) else {})
        run_context = facade.prepare_resume_context(
            compiled.compiled_app,
            session_id=session_id,
            session_config=session_config,
        )
        run_context.state.execution.timeout_seconds = RuntimeRequestPolicy.from_payload(
            payload.get("runtime_request")
        ).timeout_seconds
        final_state = None
        for stream_mode, chunk in facade.instance.controller.stream_resume(
            compiled.compiled_app,
            run_context.state,
            thread_id=run_context.thread_id,
            resume_payload=resume_payload if isinstance(resume_payload, dict) else {},
        ):
            if _handle_stream_item(normalizer, stream_mode, chunk):
                return 0
            if stream_mode == "runtime_final":
                final_state = chunk
        if final_state is None:
            normalizer.emit_run_failed(RuntimeError("agent runtime resume did not produce a final state"))
            return 1
        agent_session = _touch_session_turn_from_final_state(
            run_context,
            compiled,
            final_state,
            session_id=session_id,
            fallback_user_input=resume_user_input(resume_payload) or run_context.first_user_input,
        )
        if not runtime_completed(final_state):
            return _emit_failed_runtime_final(
                normalizer,
                final_state,
                command="resume_interrupt",
                package=package,
                agent_session=agent_session.model_dump(mode="json"),
            )
        normalizer.complete_open_model_streams(reason="run_completed")
        normalizer.emit_final_answer_if_needed(final_state, reason="run_completed")
        normalizer.emit_run_completed(
            {
                "status": "completed",
                "command": "resume_interrupt",
                "package_id": package.package_root.name,
                "agent_id": package.assembly_spec.agent.id,
                "agent_session": agent_session.model_dump(mode="json"),
            }
        )
        return 0

    def _list_sessions(self, normalizer: RuntimeEventNormalizer) -> int:
        session_contract = self.package.contracts.get("session") if isinstance(self.package.contracts, dict) else None
        session_config = session_contract.get("config", {}) if isinstance(session_contract, dict) else {}
        session_root = _runtime_session_root(
            runtime_root=self.runtime_root,
            package_root=self.package.package_root,
            configured=str(session_config.get("session_root") or ".agent_runtime/sessions"),
        )
        sessions = []
        for path in sorted(session_root.glob("*.json")):
            try:
                sessions.append(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                continue
        normalizer.runtime_event(
            "agent_package_sessions_listed",
            payload={"package_id": self.package.package_root.name, "sessions": sessions},
        )
        return 0

    def _configure_scheduler_runtime(self, *, runtime: CompiledPackageRuntime) -> None:
        scheduler_runtime = getattr(runtime.compiled.compiled_app.services, "scheduler_runtime", None)
        if scheduler_runtime is None:
            return
        tool_registry = getattr(runtime.compiled.compiled_app.services, "tool_registry", None)
        scheduler_runtime.event_sink = self._scheduler_event_sink
        scheduler_runtime.executor = SchedulerExecutor(
            graph_runner=self._scheduled_graph_runner(runtime=runtime),
            tool_runner=runtime_tool_runner(tool_registry) if tool_registry is not None else None,
        )

    def _configure_knowledge_runtime(self, *, runtime: CompiledPackageRuntime) -> None:
        knowledge_runtime = getattr(runtime.compiled.compiled_app.services, "knowledge_runtime", None)
        if knowledge_runtime is None:
            return
        knowledge_runtime.event_sink = self._knowledge_event_sink

    def _apply_scheduler_seeds(self, *, runtime: CompiledPackageRuntime) -> None:
        scheduler_runtime = getattr(runtime.compiled.compiled_app.services, "scheduler_runtime", None)
        if scheduler_runtime is None:
            return
        contract = runtime.package.contracts.get("scheduler_seed") if isinstance(runtime.package.contracts, dict) else None
        package_id = runtime.package.manifest.factory_run_id or runtime.package.package_root.name
        apply_scheduler_seed_contract(
            runtime=scheduler_runtime,
            contract_payload=contract if isinstance(contract, dict) else None,
            package_id=package_id,
        )

    def _scheduled_graph_runner(self, *, runtime: CompiledPackageRuntime):
        def run(job, run_record) -> dict[str, Any]:
            payload = dict(job.target.payload)
            message = str(payload.get("message") or "").strip()
            session_config = dict(runtime.compiled.runtime_config["session_config"])
            thread_policy = str(payload.get("thread_policy") or "new_thread_per_run")
            if thread_policy == "fixed_thread":
                session_config["session_id"] = str(payload.get("fixed_thread_id") or "")
            normalizer = RuntimeEventNormalizer(
                emit=self._emit_background_or_noop,
                request_id=None,
                session_id=None,
                mode="agent_package",
                graph_id=f"{self.graph_id}.scheduler",
                producer_type=self.producer_type,
            )
            normalizer.emit_run_started(
                {
                    "command": "scheduler_graph_run",
                    "job_id": job.job_id,
                    "scheduler_run_id": run_record.run_id,
                    "package_id": runtime.package.package_root.name,
                    "agent_id": runtime.package.assembly_spec.agent.id,
                }
            )
            run_context = runtime.facade.prepare_run_context(
                runtime.compiled.compiled_app,
                user_input=message,
                user_config=runtime.compiled.runtime_config["user_config"],
                agent_config=runtime.compiled.runtime_config["agent_config"],
                session_config=session_config,
            )
            normalizer.session_id = run_context.session_id
            final_state = None
            interrupted = False
            with scheduler_tool_approval_override(job=job, tool_id="graph_run"):
                for stream_mode, chunk in runtime.facade.instance.controller.stream(
                    runtime.compiled.compiled_app,
                    run_context.state,
                    thread_id=run_context.thread_id,
                ):
                    if _handle_stream_item(normalizer, stream_mode, chunk):
                        interrupted = True
                        break
                    if stream_mode == "runtime_final":
                        final_state = chunk
            if interrupted:
                normalizer.emit_run_failed(RuntimeError("scheduled graph run requires interrupt handling"))
                return {"status": "failed", "error": "scheduled graph run requires interrupt handling"}
            if final_state is None:
                normalizer.emit_run_failed(RuntimeError("scheduled graph run did not produce a final state"))
                return {"status": "failed", "error": "scheduled graph run did not produce a final state"}
            if not runtime_completed(final_state):
                error = runtime_error_message(final_state, command="scheduler_graph_run")
                normalizer.emit_run_failed(RuntimeError(error))
                return {"status": "failed", "error": error}
            agent_session = run_context.session_manager.touch_turn(
                run_context.session_id,
                first_user_input=run_context.first_user_input,
                user_input=run_context.first_user_input,
                reasoning_content=session_reasoning_content(final_state),
                final_answer=session_final_answer(final_state),
                status=final_state.execution.finish_status,
                trace_ref=session_trace_ref(runtime.compiled, final_state),
            )
            normalizer.complete_open_model_streams(reason="run_completed")
            normalizer.emit_final_answer_if_needed(final_state, reason="run_completed")
            normalizer.emit_run_completed(
                {
                    "status": final_state.execution.finish_status,
                    "command": "scheduler_graph_run",
                    "package_id": runtime.package.package_root.name,
                    "agent_id": runtime.package.assembly_spec.agent.id,
                    "agent_session": agent_session.model_dump(mode="json"),
                }
            )
            return {
                "status": final_state.execution.finish_status or "completed",
                "final_answer": final_state.conversation.final_answer,
                "output_summary": final_state.conversation.final_answer,
            }

        return run

    def _scheduler_event_sink(self, payload: SchedulerEventPayload) -> None:
        normalizer = RuntimeEventNormalizer(
            emit=self._emit_background_or_noop,
            request_id=None,
            session_id=None,
            mode="agent_package",
            graph_id=f"{self.graph_id}.scheduler",
            producer_type=self.producer_type,
        )
        normalizer.emit_custom_event({"type": "scheduler_event", "payload": self._scheduler_event_payload(payload)})

    def _knowledge_event_sink(self, payload: dict[str, Any]) -> None:
        normalizer = RuntimeEventNormalizer(
            emit=self._emit_background_or_noop,
            request_id=None,
            session_id=None,
            mode="agent_package",
            graph_id=f"{self.graph_id}.knowledge",
            producer_type=self.producer_type,
        )
        normalizer.emit_custom_event({"type": "knowledge_event", "payload": _normalized_knowledge_payload(payload)})

    def _emit_worker_lifecycle_failure(self, lifecycle_event: WorkerLifecycleEvent) -> None:
        self._scheduler_event_sink(
            SchedulerEventPayload(
                event_type="scheduler_run_failed",
                owner_type="agent",
                owner_id=self.package.assembly_spec.agent.id,
                status="failed",
                error_summary=(
                    f"background worker {lifecycle_event.action} failed: "
                    f"{lifecycle_event.worker_id}: {lifecycle_event.message}"
                ),
            )
        )

    def _emit_background_or_noop(self, item: FactoryFrontendEvent) -> None:
        if self.emit_background is not None:
            self.emit_background(item)

def host_runtime_package_view(
    package: LoadedAgentPackage,
    *,
    runtime_root: Path,
    artifacts_root: Path,
    workdir_root: Path,
    extension_root: Path,
) -> LoadedAgentPackage:
    replacements = {
        "/runtime/extensions": extension_root,
        "/runtime": runtime_root,
        "/artifacts": artifacts_root,
        "/workdir": workdir_root,
    }

    def translate(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: translate(item) for key, item in value.items()}
        if isinstance(value, list):
            return [translate(item) for item in value]
        if not isinstance(value, str):
            return value
        for prefix, target_root in replacements.items():
            if value == prefix:
                return str(target_root)
            if value.startswith(prefix + "/"):
                suffix = value[len(prefix) + 1 :]
                return str(target_root / suffix)
        return value

    return replace(
        package,
        contracts=translate(package.contracts),
        sandbox_contract=translate(package.sandbox_contract),
        resources=translate(package.resources),
    )


def _merged_config(base: dict[str, Any], override: Any) -> dict[str, Any]:
    result = dict(base or {})
    if isinstance(override, dict):
        result.update(override)
    return result


def _attachment_count(payload: dict[str, Any]) -> int:
    attachments = payload.get("attachments")
    return len(attachments) if isinstance(attachments, list) else 0


def _emit_pending_checkpoint_interrupt(normalizer: RuntimeEventNormalizer, compiled_app: Any, thread_id: str) -> bool:
    try:
        snapshot = compiled_app.graph_app.get_state({"configurable": {"thread_id": thread_id}})
    except Exception:
        return False
    interrupts = tuple(getattr(snapshot, "interrupts", ()) or ())
    if not interrupts:
        return False
    first = interrupts[0]
    normalizer.emit_interrupt(json_safe(interrupt_payload(first)))
    return True


def _checkpoint_incomplete_tool_call_ids(compiled_app: Any, thread_id: str) -> list[str]:
    try:
        snapshot = compiled_app.graph_app.get_state({"configurable": {"thread_id": thread_id}})
    except Exception:
        return []
    values = getattr(snapshot, "values", {}) or {}
    if not isinstance(values, dict):
        return []
    return incomplete_tool_call_ids(list(values.get("messages") or []))


def _handle_stream_item(normalizer: RuntimeEventNormalizer, stream_mode: str, chunk: Any) -> bool:
    interrupt_payload = _extract_interrupt_payload(chunk)
    if interrupt_payload is not None:
        normalizer.emit_interrupt(json_safe(interrupt_payload))
        return True
    normalizer.emit_stream_item(stream_mode, chunk, updates_payload_key="agent_package_update")
    return False


def _touch_session_turn_from_final_state(
    run_context: Any,
    compiled: Any,
    final_state: Any,
    *,
    session_id: str | None = None,
    fallback_user_input: str | None = None,
    fallback_attachments: Any = None,
) -> Any:
    session_user_input = session_user_input_from_state(
        final_state,
        fallback_user_input=fallback_user_input or run_context.first_user_input,
    )
    session_attachments = session_attachments_from_state(
        final_state,
        fallback_attachments=fallback_attachments,
    )
    return run_context.session_manager.touch_turn(
        session_id or run_context.session_id,
        first_user_input=session_user_input,
        user_input=session_user_input,
        attachments=session_attachments,
        reasoning_content=session_reasoning_content(final_state),
        final_answer=session_final_answer(final_state),
        status=getattr(getattr(final_state, "execution", None), "finish_status", None),
        trace_ref=session_trace_ref(compiled, final_state),
    )


def _emit_failed_runtime_final(
    normalizer: RuntimeEventNormalizer,
    final_state: Any,
    *,
    command: str,
    package: LoadedAgentPackage | None = None,
    agent_session: dict[str, Any] | None = None,
) -> int:
    extra_payload: dict[str, Any] = {
        "status": getattr(getattr(final_state, "execution", None), "finish_status", None) or "failed",
        "command": command,
    }
    if package is not None:
        extra_payload.update(
            {
                "package_id": package.package_root.name,
                "agent_id": package.assembly_spec.agent.id,
            }
        )
    if agent_session is not None:
        extra_payload["agent_session"] = agent_session
    normalizer.complete_open_model_streams(reason="run_failed")
    normalizer.emit_run_failed(RuntimeError(runtime_error_message(final_state, command=command)), extra_payload)
    return 1


def _runtime_session_root(*, runtime_root: Path | None, package_root: Path, configured: str) -> Path:
    value = configured.strip() or ".agent_runtime/sessions"
    if runtime_root is not None:
        if value == "/runtime":
            return runtime_root.resolve()
        if value.startswith("/runtime/"):
            return _root_relative_path(
                runtime_root,
                Path(value.removeprefix("/runtime/")),
                field_path="session.config.session_root",
            )
        if value == ".agent_runtime":
            return runtime_root.resolve()
        if value.startswith(".agent_runtime/"):
            return _root_relative_path(
                runtime_root,
                Path(value.removeprefix(".agent_runtime/")),
                field_path="session.config.session_root",
            )
    path = Path(value).expanduser()
    if path.is_absolute():
        raise ValueError(
            "session.config.session_root must be package-relative or use /runtime/... "
            f"when a runtime workspace is mounted; got {value!r}"
        )
    return _root_relative_path(package_root, path, field_path="session.config.session_root")


def _root_relative_path(root_path: Path, path: Path, *, field_path: str) -> Path:
    root = root_path.resolve()
    target = (root / path).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{field_path} must resolve inside its runtime workspace; got {str(path)!r}") from exc
    return target


def _runtime_workspace_root(*, runtime_root: Path | None, package_root: Path) -> Path:
    if runtime_root is not None:
        return runtime_root
    return (package_root / ".agent_runtime").resolve()


def _runtime_memory_config(runtime_root: Path):
    config = default_agent_memory_config()
    return config.model_copy(
        update={
            "store": config.store.model_copy(
                update={"path": str(runtime_root / "memory" / "agent.sqlite")}
            ),
            "background": config.background.model_copy(
                update={"journal_root": str(runtime_root / "memory" / "jobs")}
            ),
        },
        deep=True,
    )


def _extract_interrupt_payload(chunk: Any) -> Any | None:
    if not isinstance(chunk, dict):
        return None
    interrupts = chunk.get("__interrupt__")
    if not interrupts:
        return None
    first = interrupts[0]
    return interrupt_payload(first)


def _normalized_knowledge_payload(payload: dict[str, Any]) -> dict[str, Any]:
    event_type = str(payload.get("event_type") or "")
    if event_type in KNOWLEDGE_EVENT_TYPES:
        return payload
    return {**payload, "event_type": "knowledge_ingestion_progress"}
