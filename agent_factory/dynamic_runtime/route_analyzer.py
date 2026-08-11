from __future__ import annotations

from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

from agent_factory.dynamic_runtime.main_turn import RouteAnalyzer
from agent_factory.dynamic_runtime.model_service import ResolvedRuntimePolicy
from agent_factory.runtime_kernel.model_operations import prepare_structured_output_invocation
from agent_factory.runtime_protocol import (
    CommandEnvelope,
    RouteDecision,
    SendMessagePayload,
)


class StructuredRouteAnalyzer(RouteAnalyzer):
    def __init__(self, system_prompt: str) -> None:
        prompt = str(system_prompt or "").strip()
        if not prompt:
            raise ValueError("route analyzer system prompt must not be empty")
        self._system_prompt = prompt

    @classmethod
    def from_file(cls, path: str | Path) -> "StructuredRouteAnalyzer":
        prompt_path = Path(path).expanduser().resolve()
        return cls(prompt_path.read_text(encoding="utf-8"))

    async def analyze(
        self,
        *,
        envelope: CommandEnvelope,
        payload: SendMessagePayload,
        policy: ResolvedRuntimePolicy,
    ) -> RouteDecision:
        attachment_lines = [
            f"- {item.attachment_id}@{item.revision} digest={item.content_digest}"
            for item in payload.attachments
        ]
        user_content = payload.content
        if attachment_lines:
            user_content += "\n\nAttachment references:\n" + "\n".join(attachment_lines)
        invocation = prepare_structured_output_invocation(
            model=policy.chat_model.model,
            output_model=RouteDecision,
            messages=[
                SystemMessage(content=self._system_prompt),
                HumanMessage(content=user_content),
            ],
            model_metadata=policy.chat_model.settings.metadata(),
            config_tags=["execution-routing"],
        )
        result = await invocation.model.ainvoke(
            list(invocation.messages),
            config={
                "metadata": {
                    "operation": "execution_routing",
                    "command_id": envelope.command_id,
                    "session_id": envelope.session_id,
                    "principal_id": envelope.principal_id,
                    "model_profile_id": policy.snapshot.model.profile_id,
                    "model_profile_revision": policy.snapshot.model.profile_revision,
                }
            },
        )
        decision = result if isinstance(result, RouteDecision) else RouteDecision.model_validate(result)
        if decision.decision_source != "auto":
            decision = decision.model_copy(update={"decision_source": "auto"})
        return decision
