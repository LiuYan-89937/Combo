from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph

from agent_factory.factory_graph.state import FactoryGraphState
from agent_factory.factory_graph.tools import get_factory_base_tool_ids, get_factory_model_tools
from agent_factory.models import get_task_model, get_task_model_settings
from agent_factory.prompts import CaptureIntentOutput, PromptId, get_prompt, output_json_schema


Intent = Literal["chat", "inspect_factory", "manufacture_agent", "repair_agent", "unclear"]


@dataclass(slots=True)
class IntentDecision:
    intent: Intent
    confidence: float
    reason: str
    extracted_requirement: str | None = None
    reply_hint: str | None = None
    entry_stage: str | None = None
    should_run_graph: bool = False
    router: str = "rule_fallback"
    fallback_used: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "confidence": self.confidence,
            "reason": self.reason,
            "extracted_requirement": self.extracted_requirement,
            "reply_hint": self.reply_hint,
            "entry_stage": self.entry_stage,
            "should_run_graph": self.should_run_graph,
            "router": self.router,
            "fallback_used": self.fallback_used,
        }


class ModelFirstIntentRouter:
    """Intent classifier shell: model first, deterministic rules as fallback."""

    def classify(self, user_input: str) -> IntentDecision:
        model_decision = self._classify_with_model(user_input)
        if model_decision is not None and model_decision.confidence >= 0.7:
            return model_decision
        fallback = self._classify_with_rules(user_input)
        if model_decision is not None:
            fallback.reason = f"{fallback.reason}; model_result_low_confidence"
        return fallback

    def _classify_with_model(self, user_input: str) -> IntentDecision | None:
        task_model = get_task_model()
        task_settings = get_task_model_settings()
        if task_model is None:
            return None
        try:
            prompt_value = get_prompt(PromptId.CAPTURE_REQUIREMENT_INTENT).invoke(
                {
                    "user_input": user_input,
                    "output_json_schema": output_json_schema(CaptureIntentOutput),
                }
            )
            structured_model = task_model.with_structured_output(
                CaptureIntentOutput,
                method="json_mode",
            ).with_config(tags=["nostream"])
            if task_settings.max_tokens is not None:
                structured_model = structured_model.bind(max_tokens=task_settings.max_tokens)
            output = structured_model.invoke(prompt_value)
            return _decision_from_structured_output(output, router=f"task_model:{task_settings.model}")
        except Exception as exc:
            return IntentDecision(
                intent="unclear",
                confidence=0.0,
                reason=f"task model intent routing failed: {type(exc).__name__}: {exc}",
                router=f"task_model:{task_settings.model}",
                fallback_used=False,
            )

    def _classify_with_rules(self, user_input: str) -> IntentDecision:
        text = user_input.strip()
        lowered = text.lower()

        if _contains_any(lowered, ["修复", "维修", "返厂", "报错", "harness", "report", "repair"]):
            return IntentDecision(
                intent="repair_agent",
                confidence=0.88,
                reason="用户表达了返厂维修或错误修复意图",
                extracted_requirement=text,
                reply_hint="repair_not_ready",
                should_run_graph=False,
            )
        if _contains_any(
            lowered,
            [
                "工具",
                "tool",
                "阶段",
                "stage",
                "状态",
                "你能做什么",
                "有什么能力",
                "可以使用",
            ],
        ):
            return IntentDecision(
                intent="inspect_factory",
                confidence=0.9,
                reason="用户在询问工厂自身能力、工具、阶段或状态",
                reply_hint="show_tools",
                should_run_graph=False,
            )
        if _contains_any(
            lowered,
            [
                "创建",
                "生成",
                "做一个",
                "造一个",
                "构建",
                "制造",
                "build",
                "create",
                "agent",
                "智能体",
            ],
        ):
            return IntentDecision(
                intent="manufacture_agent",
                confidence=0.92,
                reason="用户表达了创建或制造 Agent 的需求",
                extracted_requirement=text,
                entry_stage="capture_requirement",
                should_run_graph=True,
            )
        if text.endswith("?") or text.endswith("？"):
            return IntentDecision(
                intent="chat",
                confidence=0.8,
                reason="用户输入是普通提问",
                reply_hint="chat",
                should_run_graph=False,
            )
        return IntentDecision(
            intent="chat",
            confidence=0.65,
            reason="未识别到制造、维修或工厂检查意图，进入闲聊",
            reply_hint="chat",
            should_run_graph=False,
        )


def build_capture_requirement_subgraph():
    graph = StateGraph(FactoryGraphState)
    graph.add_node("intent_classify", _classify_intent)
    graph.add_node("chat", _handle_chat)
    graph.add_node("inspect_factory", _handle_inspect_factory)
    graph.add_node("manufacture_agent", _handle_manufacture_agent)
    graph.add_node("repair_agent", _handle_repair_agent)
    graph.add_node("unclear", _handle_unclear)
    graph.add_edge(START, "intent_classify")
    graph.add_conditional_edges(
        "intent_classify",
        _route_after_classification,
        {
            "chat": "chat",
            "inspect_factory": "inspect_factory",
            "manufacture_agent": "manufacture_agent",
            "repair_agent": "repair_agent",
            "unclear": "unclear",
        },
    )
    for node_id in ["chat", "inspect_factory", "manufacture_agent", "repair_agent", "unclear"]:
        graph.add_edge(node_id, END)
    return graph.compile()


def run_capture_requirement_subgraph(state: FactoryGraphState) -> dict[str, Any]:
    original_messages = list(state.get("messages", []))
    original_stage_log = list(state.get("stage_log", []))
    final_state = build_capture_requirement_subgraph().invoke(state)
    return _delta_patch(
        final_state,
        original_message_count=len(original_messages),
        original_stage_log_count=len(original_stage_log),
    )


def _classify_intent(state: FactoryGraphState) -> dict[str, Any]:
    user_input = state.get("requirement", "")
    if state.get("force_manufacture"):
        return {
            "capture_intent": IntentDecision(
                intent="manufacture_agent",
                confidence=1.0,
                reason="explicit /run command forced manufacture_agent route",
                extracted_requirement=user_input,
                entry_stage="capture_requirement",
                should_run_graph=True,
                router="explicit_command",
                fallback_used=False,
            ).to_dict()
        }
    decision = ModelFirstIntentRouter().classify(user_input)
    return {"capture_intent": decision.to_dict()}


def _handle_manufacture_agent(state: FactoryGraphState) -> dict[str, Any]:
    intent = state.get("capture_intent", {})
    requirement = intent.get("extracted_requirement") or state.get("requirement", "")
    return {
        "current_stage": "capture_requirement",
        "status": "running",
        "graph_control": {
            "action": "continue",
            "reason": "capture_requirement_routed_to_manufacture_agent",
        },
        "requirement": requirement,
        "requirement_brief": {
            "raw_requirement": state.get("requirement", ""),
            "captured_requirement": requirement,
            "capture_route": "manufacture_agent",
            "intent": intent,
        },
        "stage_log": [
            {
                "stage_id": "capture_requirement",
                "status": "captured",
                "message": "capture subgraph routed input to manufacture_agent.",
                "details": {"intent": intent},
            }
        ],
    }


def _handle_inspect_factory(state: FactoryGraphState) -> dict[str, Any]:
    tools = get_factory_base_tool_ids()
    content = "我现在可以使用这些工厂基础工具：\n" + "\n".join(f"- {tool_id}" for tool_id in tools)
    return _terminal_response(
        state,
        status="answered",
        content=content,
        route="inspect_factory",
        message="capture subgraph answered a factory inspection request.",
    )


def _handle_chat(state: FactoryGraphState) -> dict[str, Any]:
    user_input = state.get("requirement", "")
    response, model_error = _generate_chat_reply(state)
    if response is None:
        response = AIMessage(content=_fallback_chat_reply(user_input))
    return _terminal_response(
        state,
        status="answered",
        content=response,
        route="chat",
        message="capture subgraph answered a chat request.",
        error=model_error,
    )


def _handle_repair_agent(state: FactoryGraphState) -> dict[str, Any]:
    content = (
        "我识别到这是返厂维修意图。维修入口还没有接入，后续会基于 harness/report "
        "进入 repair flow。"
    )
    return _terminal_response(
        state,
        status="repair_requested",
        content=content,
        route="repair_agent",
        message="capture subgraph routed input to repair_agent.",
    )


def _handle_unclear(state: FactoryGraphState) -> dict[str, Any]:
    content = "我不确定你是想了解工厂能力，还是要开始制造 Agent。可以用 /tools 或 /run <需求>。"
    return _terminal_response(
        state,
        status="needs_clarification",
        content=content,
        route="unclear",
        message="capture subgraph could not confidently classify the request.",
    )


def _terminal_response(
    state: FactoryGraphState,
    *,
    status: str,
    content: str | AIMessage,
    route: str,
    message: str,
    error: str | None = None,
) -> dict[str, Any]:
    intent = state.get("capture_intent", {})
    response_message = content if isinstance(content, AIMessage) else AIMessage(content=content)
    response_content = str(response_message.content)
    patch: dict[str, Any] = {
        "current_stage": "capture_requirement",
        "status": status,
        "graph_control": {
            "action": "end",
            "reason": f"capture_requirement_routed_to_{route}",
        },
        "factory_response": {"route": route, "content": response_content},
        "messages": [response_message],
        "stage_log": [
            {
                "stage_id": "capture_requirement",
                "status": status,
                "message": message,
                "details": {"intent": intent, "model_error": error} if error else {"intent": intent},
            }
        ],
    }
    if error:
        patch["errors"] = [
            {
                "stage_id": "capture_requirement",
                "where": "chat_model",
                "message": error,
            }
        ]
    return patch


def _route_after_classification(state: FactoryGraphState) -> str:
    intent = state.get("capture_intent", {}).get("intent", "unclear")
    if intent in {"chat", "inspect_factory", "manufacture_agent", "repair_agent"}:
        return intent
    return "chat"


def _delta_patch(
    final_state: FactoryGraphState,
    *,
    original_message_count: int,
    original_stage_log_count: int,
) -> dict[str, Any]:
    keys = [
        "requirement",
        "current_stage",
        "status",
        "capture_intent",
        "graph_control",
        "factory_response",
        "requirement_brief",
    ]
    patch = {key: final_state[key] for key in keys if key in final_state}
    messages = final_state.get("messages", [])[original_message_count:]
    if messages:
        patch["messages"] = messages
    stage_log = final_state.get("stage_log", [])[original_stage_log_count:]
    if stage_log:
        patch["stage_log"] = stage_log
    return patch


def _contains_any(text: str, candidates: list[str]) -> bool:
    return any(candidate in text for candidate in candidates)


def _generate_chat_reply(state: FactoryGraphState) -> tuple[AIMessage | None, str | None]:
    task_model = get_task_model()
    task_settings = get_task_model_settings()
    if task_model is None:
        return None, "task model is not configured"
    try:
        prompt_value = get_prompt(PromptId.FACTORY_CHAT).invoke(
            {"messages": state.get("messages", [])}
        )
        chat_model = task_model.bind_tools(get_factory_model_tools())
        if task_settings.max_tokens is not None:
            chat_model = chat_model.bind(max_tokens=task_settings.max_tokens)
        response = chat_model.invoke(prompt_value)
        if isinstance(response, AIMessage):
            if response.content or response.tool_calls:
                return response, None
        content = getattr(response, "content", "")
        if str(content).strip():
            return AIMessage(content=str(content).strip()), None
        return None, "task model returned an empty chat response"
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _fallback_chat_reply(user_input: str) -> str:
    return (
        f"我在。你刚才说的是：{user_input}\n"
        "如果你想制造 Agent，可以直接描述需求，或者用 /run <需求> 明确开始。"
    )


def _decision_from_structured_output(
    output: CaptureIntentOutput | dict[str, Any],
    *,
    router: str,
) -> IntentDecision:
    validated = _validate_intent_output(output)
    intent = validated.intent
    should_run_graph = validated.should_run_graph
    if intent == "manufacture_agent":
        should_run_graph = True
    elif intent in {"chat", "inspect_factory", "repair_agent", "unclear"}:
        should_run_graph = False
    return IntentDecision(
        intent=intent,
        confidence=validated.confidence,
        reason=validated.reason,
        extracted_requirement=_optional_str(validated.extracted_requirement),
        reply_hint=_optional_str(validated.reply_hint),
        entry_stage=_optional_str(validated.entry_stage) or (
            "capture_requirement" if intent == "manufacture_agent" else None
        ),
        should_run_graph=should_run_graph,
        router=router,
        fallback_used=False,
    )


def _validate_intent_output(output: CaptureIntentOutput | dict[str, Any]) -> CaptureIntentOutput:
    if isinstance(output, CaptureIntentOutput):
        return output
    return CaptureIntentOutput.model_validate(output)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
