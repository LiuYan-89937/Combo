from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from agent_factory.create_agent.assist_workflow import CreateAgentAssistWorkflow
from agent_factory.create_agent.intent import classify_create_agent_intent
from agent_factory.create_agent.tooling import CreateAgentToolEnvironmentBuilder
from agent_factory.create_agent.validator import CreateAgentPackageValidator
from agent_factory.create_agent.workflow import CreateAgentWorkflow
from agent_factory.create_agent.workspace import CreateAgentWorkspace
from agent_factory.factory_graph.frontend_bridge.protocol import FactoryFrontendEvent, event
from agent_factory.factory_graph.frontend_bridge.runtime_adapter_support import extract_interrupt_payload
from agent_factory.factory_graph.session import build_factory_checkpointer_handle


@dataclass(frozen=True, slots=True)
class CreateAgentStreamRun:
    session_id: str
    workspace: CreateAgentWorkspace
    events: Iterator[tuple[str, Any]]


class CreateAgentRuntime:
    def __init__(
        self,
        *,
        tool_environment_builder: CreateAgentToolEnvironmentBuilder | None = None,
        validator: CreateAgentPackageValidator | None = None,
        checkpointer: Any | None = None,
        model: Any | None = None,
    ) -> None:
        self.tool_environment_builder = tool_environment_builder or CreateAgentToolEnvironmentBuilder()
        self.validator = validator or CreateAgentPackageValidator()
        self.checkpointer = checkpointer or build_factory_checkpointer_handle().saver
        self.model = model
        self._active_graph_by_session: dict[str, str] = {}

    def stream(
        self,
        *,
        user_input: str,
        session_id: str | None,
        request_id: str | None,
    ) -> CreateAgentStreamRun:
        resolved_session_id = session_id or uuid4().hex
        workspace = CreateAgentWorkspace.for_session(resolved_session_id)
        intent = classify_create_agent_intent(
            user_input=user_input,
            workspace=workspace,
            model=self.model,
        )
        graph_kind = "manufacture" if intent.intent == "manufacture_agent" else "assist"
        self._active_graph_by_session[resolved_session_id] = graph_kind
        if graph_kind == "manufacture":
            workspace.initialize(user_input=user_input)
        else:
            workspace.root.mkdir(parents=True, exist_ok=True)
        return CreateAgentStreamRun(
            session_id=resolved_session_id,
            workspace=workspace,
            events=self._events(
                user_input=user_input,
                session_id=resolved_session_id,
                request_id=request_id,
                workspace=workspace,
                resume_payload=None,
                graph_kind=graph_kind,
                intent=intent.model_dump(mode="json"),
            ),
        )

    def resume_stream(
        self,
        *,
        session_id: str,
        resume_payload: dict[str, Any] | None,
        request_id: str | None,
    ) -> CreateAgentStreamRun:
        workspace = CreateAgentWorkspace.for_session(session_id)
        graph_kind = self._active_graph_by_session.get(session_id, "manufacture")
        return CreateAgentStreamRun(
            session_id=session_id,
            workspace=workspace,
            events=self._events(
                user_input="",
                session_id=session_id,
                request_id=request_id,
                workspace=workspace,
                resume_payload=resume_payload or {},
                graph_kind=graph_kind,
                intent=None,
            ),
        )

    def _events(
        self,
        *,
        user_input: str,
        session_id: str,
        request_id: str | None,
        workspace: CreateAgentWorkspace,
        resume_payload: dict[str, Any] | None,
        graph_kind: str,
        intent: dict[str, Any] | None,
    ) -> Iterator[tuple[str, Any]]:
        request_id = request_id or uuid4().hex
        graph_id = "create_agent_react" if graph_kind == "manufacture" else "create_agent_assist"
        node_label = "Create Agent ReAct" if graph_kind == "manufacture" else "Create Agent Assist"
        yield "frontend_event", _runtime_event(
            "run_started",
            request_id=request_id,
            session_id=session_id,
            graph_id=graph_id,
            payload={
                "workspace_path": str(workspace.root),
                "status": "started",
                "intent": intent,
                "graph_kind": graph_kind,
            },
        )
        yield "frontend_event", _runtime_event(
            "node_started",
            request_id=request_id,
            session_id=session_id,
            graph_id=graph_id,
            node_id=graph_id,
            node_label=node_label,
            payload={"workspace_path": str(workspace.root), "graph_kind": graph_kind},
        )
        try:
            tool_env = self.tool_environment_builder.build(workspace_root=workspace.root)
            if graph_kind == "manufacture":
                workflow = CreateAgentWorkflow(
                    tools=tool_env.tools,
                    validator=self.validator,
                    model=self.model,
                ).compile(checkpointer=self.checkpointer)
            else:
                workflow = CreateAgentAssistWorkflow(
                    tools=tool_env.tools,
                    model=self.model,
                ).compile(checkpointer=self.checkpointer)
            config = {"configurable": {"thread_id": f"{session_id}:{graph_kind}"}}
            stream_input: Any
            if resume_payload is None:
                stream_input = {
                    "request": user_input,
                    "workspace_path": str(workspace.root),
                    "iteration": 0,
                    "done": False,
                    "messages": [HumanMessage(content=user_input)],
                }
            else:
                stream_input = Command(resume=resume_payload)
                yield "frontend_event", _runtime_event(
                    "runtime_resumed",
                    request_id=request_id,
                    session_id=session_id,
                    graph_id=graph_id,
                    payload=resume_payload,
                )
            final_state: dict[str, Any] | None = None
            for stream_mode, chunk in workflow.stream(
                stream_input,
                config=config,
                stream_mode=["messages", "custom", "values"],
            ):
                interrupt_payload = extract_interrupt_payload(chunk)
                if interrupt_payload is not None:
                    yield "frontend_event", _runtime_event(
                        "interrupt_requested",
                        request_id=request_id,
                        session_id=session_id,
                        graph_id=graph_id,
                        payload=interrupt_payload,
                    )
                    return
                if stream_mode == "values" and isinstance(chunk, dict):
                    final_state = chunk
                    continue
                yield stream_mode, chunk
            if not final_state:
                raise RuntimeError("create-agent workflow did not produce final state")
            if final_state.get("done"):
                yield "frontend_event", _runtime_event(
                    "model_message_completed",
                    request_id=request_id,
                    session_id=session_id,
                    graph_id=graph_id,
                    node_id=graph_id,
                    node_label=node_label,
                    payload={"content": str(final_state.get("final_answer") or "")},
                )
                yield "frontend_event", _runtime_event(
                    "node_completed",
                    request_id=request_id,
                    session_id=session_id,
                    graph_id=graph_id,
                    node_id=graph_id,
                    node_label=node_label,
                    payload={"workspace_path": str(workspace.root), "status": "completed"},
                )
                yield "frontend_event", _runtime_event(
                    "run_completed",
                    request_id=request_id,
                    session_id=session_id,
                    graph_id=graph_id,
                    payload={
                        "status": "completed",
                        "workspace_path": str(workspace.root),
                        "graph_kind": graph_kind,
                        "agent_session": {"session_id": session_id},
                    },
                )
                return
            raise RuntimeError("create-agent workflow stopped before completion")
        except Exception as exc:
            yield "frontend_event", _runtime_event(
                "node_failed",
                request_id=request_id,
                session_id=session_id,
                graph_id=graph_id,
                node_id=graph_id,
                node_label=node_label,
                severity="error",
                payload={"message": f"{type(exc).__name__}: {exc}", "workspace_path": str(workspace.root)},
            )
            yield "frontend_event", _runtime_event(
                "run_failed",
                request_id=request_id,
                session_id=session_id,
                graph_id=graph_id,
                severity="error",
                message=f"{type(exc).__name__}: {exc}",
                payload={"message": f"{type(exc).__name__}: {exc}", "workspace_path": str(workspace.root)},
            )


def _runtime_event(
    event_type: str,
    *,
    request_id: str,
    session_id: str,
    payload: dict[str, Any],
    graph_id: str = "create_agent_react",
    node_id: str | None = None,
    node_label: str | None = None,
    severity: str | None = None,
    message: str | None = None,
) -> FactoryFrontendEvent:
    return event(
        event_type,  # type: ignore[arg-type]
        request_id=request_id,
        session_id=session_id,
        mode="create_agent",
        graph_id=graph_id,
        producer_type=graph_id,
        node_id=node_id,
        node_label=node_label,
        node_kind=graph_id if node_id else None,
        severity=severity,
        message=message,
        payload=payload,
    )
