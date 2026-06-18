from __future__ import annotations

from typing import Any, Literal

from langchain_core.messages import AIMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field

from agent_factory.runtime_kernel.errors import RuntimeKernelError
from agent_factory.runtime_kernel.activation import normalize_plan_and_execute_activation
from agent_factory.runtime_kernel.model_operations import ModelOperationService
from agent_factory.runtime_kernel.nodes.base import NodeExecutionContext
from agent_factory.runtime_kernel.state import RuntimeState


class IntentGateDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["start_workflow", "wait_for_input", "casual"] = "wait_for_input"
    user_message: str = ""
    reason: str = ""


class CognitiveIntentGateNode:
    impl_id = "cognitive.intent_gate"
    node_type = "cognitive"
    supports_interrupt = False
    supports_subgraph_slot = True
    writable_sections = {"conversation", "context", "execution"}

    def execute(
        self,
        state: RuntimeState,
        context: NodeExecutionContext,
    ) -> dict[str, Any]:
        activation = _activation_config(state)
        if not activation:
            raise RuntimeKernelError("cognitive.intent_gate requires runtime.agent_config.activation")
        if getattr(state.plan, "status", "empty") != "empty":
            return {
                "context": {"model_outputs": {context.node_id: {"decision": "start_workflow", "reason": "active plan exists"}}},
                "execution": {"current_node": context.node_id, "route_decision": "intent.start_workflow"},
            }
        service = _model_operation_service(context)
        decision = service.structured_json(
            output_model=IntentGateDecision,
            state=state,
            prebuilt_messages=[
                SystemMessage(content=_intent_gate_prompt(activation)),
                *list(context.graph_messages or []),
            ],
            max_attempts=2,
            emit_event=context.emit_event,
            operation_metadata={"node_id": context.node_id, "operation": "intent_gate"},
            services=context.services,
            node_id=context.node_id,
        )
        payload = decision.model_dump(mode="json")
        route = "intent.start_workflow" if decision.decision == "start_workflow" else "intent.wait_for_input"
        message = _response_text(decision, activation)
        return {
            "messages": [AIMessage(content=message)],
            "context": {"model_outputs": {context.node_id: payload}},
            "conversation": {"assistant_draft": message},
            "execution": {"current_node": context.node_id, "route_decision": route},
        }


def _model_operation_service(context: NodeExecutionContext):
    service = context.services.model_operation_service
    if service is None:
        raise RuntimeKernelError("cognitive.intent_gate requires model_operation_service")
    if getattr(service, "model_role", "task") == "task":
        return service
    return ModelOperationService(role="task")


def _activation_config(state: RuntimeState) -> dict[str, Any]:
    activation = state.runtime_config.agent_config.get("activation")
    return normalize_plan_and_execute_activation(activation)


def _intent_gate_prompt(activation: dict[str, Any]) -> str:
    workflow_goal = str(activation.get("workflow_goal") or "").strip()
    start_when = str(activation.get("start_when") or "").strip()
    ask_when_missing = str(activation.get("ask_when_missing") or "").strip()
    return (
        "You are a lightweight runtime intent gate for a Plan-and-Execute agent.\n"
        "Decide whether the latest user message is sufficient to start the agent's workflow.\n"
        "Return structured JSON only.\n\n"
        f"Workflow goal: {workflow_goal}\n"
        f"Start workflow when: {start_when}\n"
        f"If required information is missing, ask: {ask_when_missing}\n\n"
        "Decision rules:\n"
        "- start_workflow: the user provided enough concrete input to begin the workflow.\n"
        "- wait_for_input: the user wants the workflow but required start input is missing.\n"
        "- casual: the user is greeting, chatting, or asking a general question that should not start the workflow.\n"
        "Do not invent missing files, URLs, resources, accounts, or user choices."
    )


def _response_text(decision: IntentGateDecision, activation: dict[str, Any]) -> str:
    message = decision.user_message.strip()
    if message:
        return message
    if decision.decision == "casual":
        goal = str(activation.get("workflow_goal") or "这个工作流").strip()
        ask = str(activation.get("ask_when_missing") or "请补充开始所需的信息。").strip()
        return f"你好，我可以帮你完成{goal}。{ask}"
    return str(activation.get("ask_when_missing") or "请补充开始所需的信息。").strip()
