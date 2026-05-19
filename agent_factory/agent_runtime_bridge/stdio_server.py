from __future__ import annotations

from dataclasses import dataclass, replace
import json
import sys
from pathlib import Path
from typing import Any

from agent_factory.agent_runtime_bridge.dependencies import ensure_dependencies
from agent_factory.assembly.compiler import AgentAssemblyCompiler
from agent_factory.factory_graph.frontend_bridge.event_normalizer import RuntimeEventNormalizer, json_safe
from agent_factory.factory_graph.frontend_bridge.protocol import FactoryFrontendEvent, event
from agent_factory.runtime_contracts import AgentPackageLoader, LoadedAgentPackage, RuntimeBuildPlanner
from agent_factory.runtime_contracts.builtins import default_runtime_contract_registry
from agent_factory.runtime_kernel.kernel import RuntimeKernelFacade


PACKAGE_ROOT = Path("/package")
PACKAGE_MANIFEST = PACKAGE_ROOT / "agent_package.json"
RESOURCES_PATH = Path("/resources/resources.json")
ARTIFACTS_ROOT = Path("/artifacts")
RUNTIME_ROOT = Path("/runtime")


@dataclass(slots=True)
class CompiledRuntime:
    package: LoadedAgentPackage
    compiled: Any
    facade: RuntimeKernelFacade


@dataclass(slots=True)
class BridgeRuntimeState:
    sandbox_initialized: bool = False
    compiled_runtime: CompiledRuntime | None = None

    def handle(self, command: dict[str, Any]) -> int:
        command_type = str(command.get("type") or "")
        request_id = command.get("request_id")
        payload = command.get("payload") if isinstance(command.get("payload"), dict) else {}
        normalizer = RuntimeEventNormalizer(
            emit=_write_event,
            request_id=str(request_id) if request_id else None,
            session_id=str(payload.get("session_id") or "") or None,
            mode="agent_package",
            graph_id="agent_runtime_bridge",
            producer_type="agent_runtime",
        )
        if command_type == "shutdown":
            return 0
        normalizer.emit_run_started({"command": command_type})
        if command_type == "list_sessions":
            return _list_sessions(normalizer, self._load_package())
        if command_type in {"run_message", "resume_interrupt", "run_harness"}:
            if not self._ensure_sandbox_initialized(normalizer):
                return 1
            runtime = self._ensure_compiled(normalizer)
            if command_type == "run_message":
                return _run_message(normalizer, payload, runtime)
            if command_type == "resume_interrupt":
                return _resume_interrupt(normalizer, payload, runtime)
            return _run_harness(normalizer, payload, runtime)
        normalizer.runtime_event("error", severity="error", payload={"message": f"unknown command: {command_type}"})
        return 1

    def _ensure_sandbox_initialized(self, normalizer: RuntimeEventNormalizer) -> bool:
        if self.sandbox_initialized:
            return True
        package = self._load_package()
        sandbox = dict(package.sandbox_contract or {})
        network_policy = sandbox.get("network_policy") if isinstance(sandbox.get("network_policy"), dict) else {}
        services = sandbox.get("services") if isinstance(sandbox.get("services"), list) else []
        normalizer.runtime_event(
            "node_started",
            node_id="runtime_container",
            node_label="Runtime Container",
            node_kind="system",
            payload={
                "package_root": str(PACKAGE_ROOT),
                "runtime_root": str(RUNTIME_ROOT),
                "image": sandbox.get("image"),
                "network_policy": network_policy,
                "service_count": len(services),
            },
        )
        normalizer.runtime_event(
            "node_completed",
            node_id="runtime_container",
            node_label="Runtime Container",
            node_kind="system",
            payload={"status": "ready"},
        )
        normalizer.runtime_event(
            "node_started",
            node_id="sandbox_init",
            node_label="Sandbox Init",
            node_kind="system",
            payload={"package_root": str(PACKAGE_ROOT)},
        )
        dependency_report = ensure_dependencies(PACKAGE_ROOT, ARTIFACTS_ROOT, runtime_root=RUNTIME_ROOT)
        if dependency_report.get("status") == "failed":
            normalizer.runtime_event(
                "node_failed",
                node_id="sandbox_init",
                node_label="Sandbox Init",
                node_kind="system",
                severity="error",
                payload=dependency_report,
            )
            normalizer.emit_run_failed(RuntimeError("sandbox dependency initialization failed"))
            return False
        normalizer.runtime_event(
            "node_completed",
            node_id="sandbox_init",
            node_label="Sandbox Init",
            node_kind="system",
            payload=dependency_report,
        )
        self.sandbox_initialized = True
        return True

    def _ensure_compiled(self, normalizer: RuntimeEventNormalizer) -> CompiledRuntime:
        if self.compiled_runtime is not None:
            return self.compiled_runtime
        normalizer.runtime_event(
            "node_started",
            node_id="package_compile",
            node_label="Package Compile",
            node_kind="system",
            payload={"manifest": str(PACKAGE_MANIFEST)},
        )
        package = self._load_package()
        facade = RuntimeKernelFacade()
        runtime_build = RuntimeBuildPlanner(registry=default_runtime_contract_registry()).build(
            package,
            base_services=facade.instance.services,
        )
        compiler = AgentAssemblyCompiler(facade=facade)
        compiled = compiler.compile(package.assembly_spec, runtime_build=runtime_build)
        self.compiled_runtime = CompiledRuntime(package=package, compiled=compiled, facade=facade)
        normalizer.runtime_event(
            "node_completed",
            node_id="package_compile",
            node_label="Package Compile",
            node_kind="system",
            payload={"agent_id": package.assembly_spec.agent.id, "package_id": package.package_root.name},
        )
        return self.compiled_runtime

    def _load_package(self) -> LoadedAgentPackage:
        return _load_package()


def main() -> int:
    state = BridgeRuntimeState()
    exit_code = 0
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            command = json.loads(line)
            if not isinstance(command, dict):
                raise ValueError("command must be a JSON object")
        except Exception as exc:
            _write_event(event("error", mode="agent_package", payload={"message": f"invalid command: {exc}"}))
            exit_code = 1
            continue
        if str(command.get("type") or "") == "shutdown":
            break
        try:
            result = state.handle(command)
            if result != 0:
                exit_code = result
        except Exception as exc:
            _write_event(
                event(
                    "run_failed",
                    request_id=str(command.get("request_id") or "") or None,
                    mode="agent_package",
                    graph_id="agent_runtime_bridge",
                    severity="error",
                    payload={"message": f"{type(exc).__name__}: {exc}"},
                )
            )
            exit_code = 1
    return exit_code


def _run_message(normalizer: RuntimeEventNormalizer, payload: dict[str, Any], runtime: CompiledRuntime) -> int:
    message = str(payload.get("message") or "").strip()
    if not message:
        normalizer.emit_run_failed(ValueError("run_message requires payload.message"))
        return 1
    package = runtime.package
    compiled = runtime.compiled
    facade = runtime.facade
    session_config = dict(compiled.runtime_config["session_config"])
    if payload.get("session_id"):
        session_config["session_id"] = str(payload["session_id"])
    run_context = facade.prepare_run_context(
        compiled.compiled_app,
        user_input=message,
        user_config=compiled.runtime_config["user_config"],
        agent_config=compiled.runtime_config["agent_config"],
        session_config=session_config,
    )
    normalizer.session_id = run_context.session_id
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
    agent_session = run_context.session_manager.touch_turn(
        run_context.session_id,
        first_user_input=run_context.first_user_input,
    )
    normalizer.complete_open_model_streams(reason="run_completed")
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


def _resume_interrupt(normalizer: RuntimeEventNormalizer, payload: dict[str, Any], runtime: CompiledRuntime) -> int:
    session_id = str(payload.get("session_id") or "").strip()
    resume_payload = payload.get("resume_payload")
    if not session_id:
        normalizer.emit_run_failed(ValueError("resume_interrupt requires payload.session_id"))
        return 1
    package = runtime.package
    compiled = runtime.compiled
    facade = runtime.facade
    session_config = dict(compiled.runtime_config["session_config"])
    session_config["session_id"] = session_id
    normalizer.session_id = session_id
    normalizer.emit_runtime_resumed(resume_payload if isinstance(resume_payload, dict) else {})
    for stream_mode, chunk in facade.stream_resume(
        compiled.compiled_app,
        session_id=session_id,
        resume_payload=resume_payload if isinstance(resume_payload, dict) else {},
        session_config=session_config,
    ):
        if _handle_stream_item(normalizer, stream_mode, chunk):
            return 0
    normalizer.complete_open_model_streams(reason="run_completed")
    agent_session = facade.prepare_resume_context(
        compiled.compiled_app,
        session_id=session_id,
        session_config=session_config,
    ).session_manager.load(session_id)
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


def _list_sessions(normalizer: RuntimeEventNormalizer, package: LoadedAgentPackage) -> int:
    session_contract = package.contracts.get("session") if isinstance(package.contracts, dict) else None
    session_config = session_contract.get("config", {}) if isinstance(session_contract, dict) else {}
    session_root = Path(str(session_config.get("session_root") or "/runtime/sessions"))
    sessions = []
    for path in sorted(session_root.glob("*.json")):
        try:
            sessions.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    normalizer.runtime_event(
        "agent_package_sessions_listed",
        payload={"package_id": package.package_root.name, "sessions": sessions},
    )
    return 0


def _run_harness(normalizer: RuntimeEventNormalizer, payload: dict[str, Any], runtime: CompiledRuntime) -> int:
    plan = payload.get("execution_plan") if isinstance(payload.get("execution_plan"), dict) else {}
    compiled = runtime.compiled
    facade = runtime.facade
    result = {
        "dependency_results": [json.loads((ARTIFACTS_ROOT / "dependency_report.json").read_text(encoding="utf-8"))],
        "scenario_results": [],
        "tool_test_results": [],
        "errors": [],
    }
    for scenario in plan.get("scenarios") or []:
        input_text = str(scenario.get("input_text") or "")
        if not input_text:
            continue
        run_context = facade.prepare_run_context(
            compiled.compiled_app,
            user_input=input_text,
            user_config=compiled.runtime_config["user_config"],
            agent_config=compiled.runtime_config["agent_config"],
            session_config=compiled.runtime_config["session_config"],
        )
        final_state = None
        for stream_mode, chunk in facade.instance.controller.stream(
            compiled.compiled_app,
            run_context.state,
            thread_id=run_context.thread_id,
        ):
            _handle_stream_item(normalizer, stream_mode, chunk)
            if stream_mode == "runtime_final":
                final_state = chunk
        result["scenario_results"].append(
            {
                "scenario_id": scenario.get("scenario_id"),
                "status": getattr(getattr(final_state, "execution", None), "finish_status", "failed") if final_state else "failed",
                "final_answer": getattr(getattr(final_state, "conversation", None), "final_answer", None) if final_state else None,
            }
        )
    _run_harness_tool_tests(compiled, plan, result)
    (ARTIFACTS_ROOT / "sandbox_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    normalizer.emit_run_completed({"status": "failed" if result["errors"] else "passed", "command": "run_harness"})
    return 1 if result["errors"] else 0


def _run_harness_tool_tests(compiled: Any, plan: dict[str, Any], result: dict[str, Any]) -> None:
    registry = compiled.compiled_app.services.tool_registry
    if registry is None:
        return
    from agent_factory.runtime_kernel.state import RuntimeState

    state = RuntimeState()
    for item in plan.get("tool_tests") or []:
        tool_id = str(item.get("tool_id") or "")
        if not tool_id:
            continue
        try:
            output = registry.execute(tool_id, dict(item.get("arguments") or {}), state=state)
            result["tool_test_results"].append({"tool_id": tool_id, **output.model_dump(mode="json")})
            if output.status != "completed":
                result["errors"].append({"where": f"tool_test.{tool_id}", "why": "tool_failed", "message": output.error or output.observation_summary or "tool failed", "evidence": output.model_dump(mode="json")})
        except Exception as exc:
            result["errors"].append({"where": f"tool_test.{tool_id}", "why": "tool_failed", "message": f"{type(exc).__name__}: {exc}", "evidence": {}})


def _load_package() -> LoadedAgentPackage:
    package = AgentPackageLoader().load_path(PACKAGE_MANIFEST)
    if RESOURCES_PATH.is_file():
        resources = json.loads(RESOURCES_PATH.read_text(encoding="utf-8"))
        package = replace(package, resources=resources)
    return package


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
        normalizer.runtime_event("debug_patch", span_id=normalizer.run_span_id, payload={"agent_package_update": json_safe(chunk)})
    return False


def _extract_interrupt_payload(chunk: Any) -> Any | None:
    if not isinstance(chunk, dict):
        return None
    interrupts = chunk.get("__interrupt__")
    if not interrupts:
        return None
    first = interrupts[0]
    return getattr(first, "value", first)


def _write_event(item: FactoryFrontendEvent) -> None:
    sys.stdout.write(item.model_dump_json() + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    raise SystemExit(main())
