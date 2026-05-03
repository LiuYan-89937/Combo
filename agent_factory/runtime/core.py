from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import ConfigDict, Field

from agent_factory.context import ContextBundle, ContextManager, tool_runtime_context
from agent_factory.core.types import JsonDumpMixin
from agent_factory.memory import AgentMemoryRecord, AgentMemoryStore
from agent_factory.model import (
    LLMMessage,
    LLMRequest,
    MessageBuilder,
    ModelConfigError,
    ModelService,
)
from agent_factory.model.types import ModelError, TokenUsage, ToolCallProposal
from agent_factory.package import PackageLoader
from agent_factory.tools import ToolExecutor, ToolInvocation, ToolResult, ToolRouter


class RuntimeEvent(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    stage: str
    status: Literal["started", "completed", "failed", "interrupted"]
    message: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AgentRunRequest(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    package_path: Path
    user_input: str
    session_id: str = "default"
    history: list[LLMMessage] = Field(default_factory=list)
    process_isolated: bool = False
    approved_tool_call_id: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class AgentRunResult(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    package_path: Path
    status: Literal["completed", "failed", "interrupted", "needs_upgrade"]
    answer: str = ""
    runtime_type: str = "workflow"
    session_id: str = "default"
    history_turn_count: int = 0
    tool_summary_fallback: bool = False
    intent: str | None = None
    trace_path: Path | None = None
    memory_path: Path | None = None
    events: list[RuntimeEvent] = Field(default_factory=list)
    context_bundle: ContextBundle | None = None
    tool_proposals: list[ToolCallProposal] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)
    usage: TokenUsage | None = None
    error: ModelError | None = None
    upgrade_request_path: Path | None = None

    @property
    def ok(self) -> bool:
        return self.status == "completed"


class WorkflowRuntime:
    def __init__(
        self,
        *,
        model_service: ModelService | None = None,
        env_file: str | Path | None = None,
        loader: PackageLoader | None = None,
        context_manager: ContextManager | None = None,
    ) -> None:
        self.model_service = model_service
        self.env_file = Path(env_file) if env_file is not None else None
        self.loader = loader or PackageLoader()
        self.context_manager = context_manager or ContextManager(loader=self.loader)

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        run_id = uuid.uuid4().hex
        package_path = request.package_path
        trace_path = package_path / "traces" / f"agent_run_{run_id}.jsonl"
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        events: list[RuntimeEvent] = []

        def record(event: RuntimeEvent) -> None:
            events.append(event)
            with trace_path.open("a", encoding="utf-8") as file:
                file.write(json.dumps(event.model_dump(mode="json"), ensure_ascii=False) + "\n")

        try:
            package = self.loader.load_full_package(package_path)
            memory = AgentMemoryStore(package_path, loader=self.loader)
            context_bundle = self.context_manager.compile(
                package_path,
                session_context=request.context,
            )
            record(RuntimeEvent(run_id=run_id, stage="load_context", status="completed"))
            history = request.history or memory.recent_messages(
                session_id=request.session_id,
                limit_turns=package.primitives.conversation.history_window,
            )
            history_turn_count = _history_turn_count(history)
            record(
                RuntimeEvent(
                    run_id=run_id,
                    stage="load_memory",
                    status="completed",
                    payload={
                        "session_id": request.session_id,
                        "history_turn_count": history_turn_count,
                        "source": "request" if request.history else "memory",
                    },
                )
            )
            prompt = self._build_request(package, request, context_bundle, history)
            response = asyncio.run(self._model().generate(prompt))
            if response.error:
                record(
                    RuntimeEvent(
                        run_id=run_id,
                        stage="model_turn",
                        status="failed",
                        message=response.error.message,
                    )
                )
                return AgentRunResult(
                    run_id=run_id,
                    package_path=package_path,
                    status="failed",
                    session_id=request.session_id,
                    history_turn_count=history_turn_count,
                    trace_path=trace_path,
                    memory_path=memory.path,
                    events=events,
                    context_bundle=context_bundle,
                    error=response.error,
                )

            intent = _infer_intent(request.user_input, response.content, package)
            proposals = _proposals_from_response(response.tool_call_proposals, request.user_input, package)
            tool_results = self._handle_tools(package_path, proposals, request, context_bundle)
            tool_summary_fallback = False
            status: Literal["completed", "failed", "interrupted", "needs_upgrade"] = "completed"
            if any(result.status == "interrupted" for result in tool_results):
                status = "interrupted"
            upgrade_path = None
            if intent == "unknown":
                status = "needs_upgrade"
                upgrade_path = _write_upgrade_request(package_path, run_id, request.user_input)

            answer = response.content
            if tool_results and any(result.status == "completed" for result in tool_results):
                summary = asyncio.run(
                    self._model().generate(
                        self._build_tool_summary_request(
                            package,
                            request,
                            context_bundle,
                            history,
                            response.content,
                            proposals,
                            tool_results,
                        )
                    )
                )
                if summary.ok and summary.content.strip():
                    answer = summary.content
                else:
                    tool_summary_fallback = True
                    answer = _fallback_answer(request.user_input, intent, tool_results)
            if not answer:
                answer = _answer_from_history(request.user_input, history) or _fallback_answer(
                    request.user_input,
                    intent,
                    tool_results,
                )
            memory.append(
                AgentMemoryRecord(
                    run_id=run_id,
                    session_id=request.session_id,
                    type="agent_turn",
                    summary=f"Handled intent={intent}",
                    payload={
                        "user_input": request.user_input,
                        "answer": answer,
                        "intent": intent,
                        "tool_results": [item.model_dump(mode="json") for item in tool_results],
                    },
                )
            )
            record(
                RuntimeEvent(
                    run_id=run_id,
                    stage="complete" if status == "completed" else status,
                    status="completed" if status in {"completed", "needs_upgrade"} else "interrupted",
                    payload={
                        "intent": intent,
                        "tool_count": len(tool_results),
                        "session_id": request.session_id,
                        "history_turn_count": history_turn_count,
                        "tool_summary_fallback": tool_summary_fallback,
                    },
                )
            )
            return AgentRunResult(
                run_id=run_id,
                package_path=package_path,
                status=status,
                answer=answer,
                runtime_type=package.runtime.runtime_type,
                session_id=request.session_id,
                history_turn_count=history_turn_count,
                tool_summary_fallback=tool_summary_fallback,
                intent=intent,
                trace_path=trace_path,
                memory_path=memory.path,
                events=events,
                context_bundle=context_bundle,
                tool_proposals=proposals,
                tool_results=tool_results,
                usage=response.usage,
                upgrade_request_path=upgrade_path,
            )
        except ModelConfigError as error:
            model_error = ModelError(type="model_config_error", message=str(error))
            record(
                RuntimeEvent(
                    run_id=run_id,
                    stage="model_config",
                    status="failed",
                    message=str(error),
                )
            )
            return AgentRunResult(
                run_id=run_id,
                package_path=package_path,
                status="failed",
                session_id=request.session_id,
                trace_path=trace_path,
                events=events,
                error=model_error,
            )
        except Exception as error:
            model_error = ModelError(type="runtime_error", message=str(error))
            record(
                RuntimeEvent(run_id=run_id, stage="runtime", status="failed", message=str(error))
            )
            return AgentRunResult(
                run_id=run_id,
                package_path=package_path,
                status="failed",
                session_id=request.session_id,
                trace_path=trace_path,
                events=events,
                error=model_error,
            )

    def _build_request(
        self,
        package: Any,
        request: AgentRunRequest,
        context_bundle: ContextBundle,
        history: list[LLMMessage],
    ) -> LLMRequest:
        instructions = package.primitives.instructions
        sections = [
            f"Persona: {instructions.persona}",
            f"Goal: {instructions.goal}",
            "The model may propose tools but must not claim it executed them directly.",
        ]
        if instructions.boundaries:
            sections.append("Boundaries:\n" + "\n".join(f"- {item}" for item in instructions.boundaries))
        if context_bundle.visible_to_model:
            sections.append(
                "Visible context:\n" + "\n".join(f"- {item}" for item in context_bundle.visible_to_model)
            )
        builder = MessageBuilder.start().system("\n\n".join(sections))
        for message in history[-package.primitives.conversation.history_window * 2 :]:
            builder.add(message)
        builder.user(request.user_input)
        return builder.request(metadata={"agent": package.manifest.agent_id})

    def _build_tool_summary_request(
        self,
        package: Any,
        request: AgentRunRequest,
        context_bundle: ContextBundle,
        history: list[LLMMessage],
        draft_answer: str,
        proposals: list[ToolCallProposal],
        tool_results: list[ToolResult],
    ) -> LLMRequest:
        builder = MessageBuilder.start().system(
            "\n\n".join(
                [
                    f"Persona: {package.primitives.instructions.persona}",
                    f"Goal: {package.primitives.instructions.goal}",
                    "Use the controlled tool results below to answer the user naturally.",
                    "Do not claim actions beyond the tool output.",
                ]
            )
        )
        if context_bundle.visible_to_model:
            builder.system(
                "Visible context:\n"
                + "\n".join(f"- {item}" for item in context_bundle.visible_to_model)
            )
        for message in history[-package.primitives.conversation.history_window * 2 :]:
            builder.add(message)
        builder.user(request.user_input)
        if draft_answer:
            builder.assistant(draft_answer)
        builder.system(
            "Tool proposals and results:\n"
            + json.dumps(
                {
                    "proposals": [proposal.model_dump(mode="json") for proposal in proposals],
                    "results": [result.model_dump(mode="json") for result in tool_results],
                },
                ensure_ascii=False,
            )
        )
        return builder.request(metadata={"agent": package.manifest.agent_id, "purpose": "tool_summary"})

    def _handle_tools(
        self,
        package_path: Path,
        proposals: list[ToolCallProposal],
        request: AgentRunRequest,
        context_bundle: ContextBundle,
    ) -> list[ToolResult]:
        if not proposals:
            return []
        router = ToolRouter(package_path, loader=self.loader)
        executor = ToolExecutor()
        results: list[ToolResult] = []
        for proposal in proposals:
            invocation = ToolInvocation(
                invocation_id=proposal.id,
                tool_id=proposal.name,
                arguments=proposal.arguments,
                approved=request.approved_tool_call_id == proposal.id,
            )
            route = router.route(invocation)
            if isinstance(route, ToolResult):
                results.append(route)
            else:
                results.append(
                    executor.execute(
                        package_path,
                        route,
                        invocation,
                        runtime_context=tool_runtime_context(context_bundle),
                    )
                )
        return results

    def _model(self) -> ModelService:
        if self.model_service is not None:
            return self.model_service
        return ModelService.from_env(env_file=self.env_file or ".env")


class GraphRuntime(WorkflowRuntime):
    """Interface-compatible placeholder for future AgentInstance graph runtime."""


def _infer_intent(user_input: str, content: str, package: Any) -> str:
    text = f"{user_input}\n{content}".lower()
    if _looks_like_strange_number_request(text) and _find_generated_tool(
        package,
        "calculate_strange_number",
        markers=("strange", "calculate"),
    ):
        return "calculate_strange_number"
    if "返厂" in text or "维修" in text or "repair" in text:
        if any(tool.tool_id == "repair_ticket_create" for tool in package.generated_tools):
            return "repair_return"
        return "unknown"
    if "订单" in text or "order" in text:
        return "order_query"
    if "退款" in text or "refund" in text:
        return "refund"
    if "投诉" in text or "complaint" in text:
        return "complaint"
    return "in_scope"


def _proposals_from_response(
    proposals: list[ToolCallProposal],
    user_input: str,
    package: Any,
) -> list[ToolCallProposal]:
    if proposals:
        return proposals
    if ("订单" in user_input or "order" in user_input.lower()) and any(
        tool.tool_id == "order_query" for tool in package.generated_tools
    ):
        return [
            ToolCallProposal(
                id=uuid.uuid4().hex,
                name="order_query",
                arguments={"query": user_input},
            )
        ]
    if ("返厂" in user_input or "维修" in user_input or "repair" in user_input.lower()) and any(
        tool.tool_id == "repair_ticket_create" for tool in package.generated_tools
    ):
        return [
            ToolCallProposal(
                id=uuid.uuid4().hex,
                name="repair_ticket_create",
                arguments={"description": user_input},
            )
        ]
    strange_tool = _find_generated_tool(
        package,
        "calculate_strange_number",
        markers=("strange", "calculate"),
    )
    if strange_tool is not None and _looks_like_strange_number_request(user_input.lower()):
        return [
            ToolCallProposal(
                id=uuid.uuid4().hex,
                name=strange_tool.tool_id,
                arguments={"query": user_input},
            )
        ]
    sqlite_proposal = _sqlite_ticket_tool_proposal(user_input, package)
    if sqlite_proposal is not None:
        return [sqlite_proposal]
    return []


def _sqlite_ticket_tool_proposal(user_input: str, package: Any) -> ToolCallProposal | None:
    tools = {tool.tool_id for tool in package.generated_tools}
    text = user_input.lower()
    if "customer_ticket" not in " ".join(tools) and not any(
        tool_id in tools
        for tool_id in {
            "list_customer_tickets",
            "get_customer_ticket",
            "search_customer_tickets",
            "create_customer_ticket",
            "update_customer_ticket_status",
            "close_customer_ticket",
        }
    ):
        return None
    ticket_match = re.search(r"T[-_]?\d+", user_input, flags=re.IGNORECASE)
    if ticket_match and "get_customer_ticket" in tools and not any(
        marker in user_input for marker in ["更新", "修改", "关闭", "close", "resolved", "closed"]
    ):
        ticket_id = ticket_match.group(0).replace("_", "-").upper()
        return ToolCallProposal(
            id=uuid.uuid4().hex,
            name="get_customer_ticket",
            arguments={"ticket_id": ticket_id},
        )
    if any(marker in user_input for marker in ["列出", "有哪些", "有什么", "现在数据库", "全部", "列表"]):
        if "list_customer_tickets" in tools:
            return ToolCallProposal(
                id=uuid.uuid4().hex,
                name="list_customer_tickets",
                arguments={"limit": 20, "offset": 0},
            )
    if any(marker in user_input for marker in ["搜索", "查找", "查一下", "查询", "search"]) and "search_customer_tickets" in tools:
        arguments: dict[str, Any] = {"query": user_input, "limit": 20}
        for status in ("open", "pending", "resolved", "closed"):
            if status in text:
                arguments["status"] = status
                break
        return ToolCallProposal(
            id=uuid.uuid4().hex,
            name="search_customer_tickets",
            arguments=arguments,
        )
    return None


def _find_generated_tool(
    package: Any,
    preferred_tool_id: str,
    *,
    markers: tuple[str, ...] = (),
) -> Any | None:
    for tool in package.generated_tools:
        if tool.tool_id == preferred_tool_id:
            return tool
    lowered_markers = tuple(marker.lower() for marker in markers)
    for tool in package.generated_tools:
        tool_id = tool.tool_id.lower()
        if any(marker in tool_id for marker in lowered_markers):
            return tool
    return None


def _looks_like_strange_number_request(text: str) -> bool:
    return (
        "奇异" in text
        or "strange" in text
        or ("计算" in text and re.search(r"[-+]?\d", text) is not None)
    )


def _fallback_answer(user_input: str, intent: str, tool_results: list[ToolResult]) -> str:
    if intent == "unknown":
        return "这个需求当前不在能力范围内，我已记录为升级请求。"
    if tool_results:
        completed = [item for item in tool_results if item.status == "completed"]
        interrupted = [item for item in tool_results if item.status == "interrupted"]
        if completed:
            summaries = []
            for item in completed:
                rendered = json.dumps(item.output or {}, ensure_ascii=False)
                summaries.append(f"{item.tool_id}: {rendered}")
            return "已通过受控工具链处理：" + "；".join(summaries)
        if interrupted:
            return f"该操作需要人工确认后才能执行：{interrupted[0].tool_id}。"
    return "我会根据当前客服规则继续协助处理。"


def _answer_from_history(user_input: str, history: list[LLMMessage]) -> str | None:
    if not any(marker in user_input for marker in ["我叫什么", "我的名字", "我是谁"]):
        return None
    for message in reversed(history):
        if message.role != "user":
            continue
        match = re.search(r"我叫\s*([^，。,.!！?\s]+)", message.content)
        if match:
            return f"你叫{match.group(1)}。"
    return None


def _history_turn_count(history: list[LLMMessage]) -> int:
    return sum(1 for message in history if message.role == "user")


def _write_upgrade_request(package_path: Path, run_id: str, user_input: str) -> Path:
    path = package_path / "upgrades" / f"upgrade_request_{run_id}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    content = (
        "schema_version: '0.1'\n"
        "kind: UpgradeRequest\n"
        f"run_id: {run_id}\n"
        "reason: unknown_intent\n"
        "proposed_intent: repair_return\n"
        f"user_input: {json.dumps(user_input, ensure_ascii=False)}\n"
    )
    path.write_text(content, encoding="utf-8")
    return path
