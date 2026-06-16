from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
from typing import Any, Callable

from agent_factory.assembly.compiler import AgentAssemblyCompiler
from agent_factory.factory_graph.frontend_bridge.event_normalizer import RuntimeEventNormalizer, json_safe
from agent_factory.factory_graph.frontend_bridge.protocol import FactoryFrontendEvent, event
from agent_factory.factory_graph.frontend_bridge.runtime_adapter_support import interrupt_payload
from agent_factory.runtime_contracts import LoadedAgentPackage, RuntimeBuildPlanner
from agent_factory.runtime_contracts.builtins import default_runtime_contract_registry
from agent_factory.runtime_kernel.background_workers import RuntimeBackgroundWorkerManager, WorkerLifecycleEvent
from agent_factory.runtime_kernel.kernel import RuntimeKernelFacade
from agent_factory.runtime_kernel.persistence import LangGraphCheckpointerConfig, LangGraphStoreConfig
from agent_factory.runtime_protocol.completion import runtime_completed, runtime_error_message
from agent_factory.runtime_protocol.messages import incomplete_tool_call_ids
from agent_factory.scheduler_system import SchedulerExecutor, runtime_tool_runner
from agent_factory.scheduler_system.events import SchedulerEventPayload
from agent_factory.scheduler_system.seeds import apply_scheduler_seed_contract
from agent_factory.knowledge_system.events import KNOWLEDGE_EVENT_TYPES
from agent_factory.package_runtime.approval_resume import tool_approval_resume_context
from agent_factory.package_runtime.request_lifecycle import RuntimeRequestPolicy


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
        emit_background: Emit | None = None,
        graph_id: str = "agent_package_runtime",
        producer_type: str = "agent_runtime",
    ) -> None:
        self.package = package
        self.graph_id = graph_id
        self.producer_type = producer_type
        self.emit_background = emit_background
        self.compiled_runtime: CompiledPackageRuntime | None = None
        self.background_workers = RuntimeBackgroundWorkerManager()

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
        normalizer.emit_run_started({"command": command_type})
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
        normalizer.runtime_event(
            "node_started",
            node_id="package_compile",
            node_label="Package Compile",
            node_kind="system",
            payload={"manifest": str(self.package.manifest_path)},
        )
        facade = RuntimeKernelFacade(
            checkpointer_config=LangGraphCheckpointerConfig(backend="memory"),
            memory_store_config=LangGraphStoreConfig(backend="memory"),
        )
        runtime_build = RuntimeBuildPlanner(registry=default_runtime_contract_registry()).build(
            self.package,
            base_services=facade.instance.services,
        )
        register_package_patterns(facade=facade, package=self.package, runtime_build=runtime_build)
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

    def _run_message(self, normalizer: RuntimeEventNormalizer, payload: dict[str, Any]) -> int:
        message = str(payload.get("message") or "").strip()
        if not message:
            normalizer.emit_run_failed(ValueError("run_message requires payload.message"))
            return 1
        runtime = self.ensure_compiled(normalizer)
        package = runtime.package
        compiled = runtime.compiled
        facade = runtime.facade
        session_config = dict(compiled.runtime_config["session_config"])
        if payload.get("session_id"):
            session_config["session_id"] = str(payload["session_id"])
        user_config = _merged_config(compiled.runtime_config["user_config"], payload.get("user_config"))
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
        if not runtime_completed(final_state):
            return _emit_failed_runtime_final(normalizer, final_state, command="run_message")
        agent_session = run_context.session_manager.touch_turn(
            run_context.session_id,
            first_user_input=run_context.first_user_input,
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
        with tool_approval_resume_context(resume_payload):
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
        if not runtime_completed(final_state):
            return _emit_failed_runtime_final(normalizer, final_state, command="resume_interrupt")
        agent_session = run_context.session_manager.touch_turn(session_id)
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
        session_root = Path(str(session_config.get("session_root") or ".agent_runtime/sessions"))
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
        self._emit_background_or_noop(
            event(
                payload.event_type,
                mode="agent_package",
                graph_id=f"{self.graph_id}.scheduler",
                producer_type=self.producer_type,
                payload={key: value for key, value in payload.model_dump(mode="json").items() if key != "event_type"},
            )
        )

    def _knowledge_event_sink(self, payload: dict[str, Any]) -> None:
        event_type = str(payload.get("event_type") or "")
        if event_type not in KNOWLEDGE_EVENT_TYPES:
            event_type = "knowledge_ingestion_progress"
        self._emit_background_or_noop(
            event(
                event_type,  # type: ignore[arg-type]
                mode="agent_package",
                graph_id=f"{self.graph_id}.knowledge",
                producer_type=self.producer_type,
                severity="error" if event_type.endswith("failed") else None,
                payload={key: value for key, value in payload.items() if key != "event_type"},
            )
        )

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


def register_package_patterns(
    *,
    facade: RuntimeKernelFacade,
    package: LoadedAgentPackage,
    runtime_build: Any | None = None,
) -> None:
    if runtime_build is not None and getattr(runtime_build, "node_providers", None):
        facade.register_node_providers(runtime_build.node_providers)
    for pattern in package.patterns:
        facade.instance.pattern_registry.register(pattern)


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
    if stream_mode == "messages":
        normalizer.emit_message_chunk(chunk)
    elif stream_mode == "debug":
        normalizer.emit_debug_event(json_safe(chunk))
    elif stream_mode == "custom":
        normalizer.emit_custom_event(json_safe(chunk))
    elif stream_mode == "updates":
        normalizer.runtime_event(
            "debug_patch",
            span_id=normalizer.run_span_id,
            payload={"agent_package_update": json_safe(chunk)},
        )
    return False


def _emit_failed_runtime_final(normalizer: RuntimeEventNormalizer, final_state: Any, *, command: str) -> int:
    normalizer.complete_open_model_streams(reason="run_failed")
    normalizer.emit_run_failed(RuntimeError(runtime_error_message(final_state, command=command)))
    return 1


def _extract_interrupt_payload(chunk: Any) -> Any | None:
    if not isinstance(chunk, dict):
        return None
    interrupts = chunk.get("__interrupt__")
    if not interrupts:
        return None
    first = interrupts[0]
    return interrupt_payload(first)
