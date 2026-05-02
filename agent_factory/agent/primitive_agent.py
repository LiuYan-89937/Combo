from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from agent_factory.model import (
    LLMMessage,
    LLMRequest,
    LLMResponse,
    MessageBuilder,
    MessageLike,
    ModelService,
    StructuredOutputResult,
    normalize_messages,
)
from agent_factory.package import PackageLoader, PackageValidator
from agent_factory.specs import AgentPackagePrimitives, OutputSpec


class PrimitiveAgentError(RuntimeError):
    """Raised when a primitive-backed Agent cannot be built or run."""


class AgentRunInput(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    user_message: str
    history: list[LLMMessage] = Field(default_factory=list)
    context_items: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request: LLMRequest
    response: LLMResponse
    structured_data: dict[str, Any] | list[Any] | None = None

    @property
    def ok(self) -> bool:
        return self.response.ok


class PrimitiveAgent:
    """Thin development runner for already-built Agent Building Primitives.

    This class is a bottom-layer smoke runner: it proves that primitives can be
    loaded, converted into a model request, and executed through ModelService.
    It is not the AgentFactory manufacturing path. The formal Factory output is
    a file-based AgentPackage that is validated, tested, approved, and then
    loaded by a runtime.
    """

    def __init__(self, primitives: AgentPackagePrimitives, model_service: ModelService):
        self.primitives = primitives
        self.model_service = model_service

    @classmethod
    def from_package(
        cls,
        root_path: str | Path,
        *,
        model_service: ModelService,
        loader: PackageLoader | None = None,
        validator: PackageValidator | None = None,
    ) -> "PrimitiveAgent":
        package_validator = validator or PackageValidator(loader=loader)
        report = package_validator.validate_primitives(root_path)
        if not report.ok:
            messages = "; ".join(issue.message for issue in report.issues)
            raise PrimitiveAgentError(f"Invalid AgentPackage primitives: {messages}")
        primitives = (loader or PackageLoader()).load_primitives(root_path)
        return cls(primitives=primitives, model_service=model_service)

    async def run(
        self,
        user_message: str,
        *,
        history: list[MessageLike] | None = None,
        context_items: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AgentRunResult:
        run_input = AgentRunInput(
            user_message=user_message,
            history=normalize_messages(history or []),
            context_items=context_items or [],
            metadata=metadata or {},
        )
        request = self.build_request(run_input)

        if self._needs_structured_output():
            structured = await self.model_service.generate_structured(request)
            return AgentRunResult(
                request=request,
                response=structured.response,
                structured_data=structured.data,
            )

        response = await self.model_service.generate(request)
        return AgentRunResult(request=request, response=response)

    def build_request(self, run_input: AgentRunInput) -> LLMRequest:
        builder = MessageBuilder.start().system(self._system_prompt())
        for message in self._trim_history(run_input.history):
            builder.add(message)
        if run_input.context_items:
            builder.system(self._context_prompt(run_input.context_items))
        builder.user(run_input.user_message)
        return builder.request(
            response_format=self._response_format(),
            metadata={
                "agent_name": self.primitives.instructions.metadata.name,
                "agent_version": self.primitives.instructions.metadata.version,
                "output_mode": self.primitives.output.output_mode,
                **run_input.metadata,
            },
        )

    def _trim_history(self, history: list[LLMMessage]) -> list[LLMMessage]:
        retained: list[LLMMessage] = []
        for message in history:
            if message.role == "system" and not self.primitives.conversation.retain_system_messages:
                continue
            if message.role == "tool" and not self.primitives.conversation.retain_tool_messages:
                continue
            retained.append(message)
        return retained[-self.primitives.conversation.history_window :]

    def _response_format(self) -> Literal["text", "json_object"]:
        if self.primitives.output.output_mode in {"json_object", "pydantic_model"}:
            return "json_object"
        return "text"

    def _needs_structured_output(self) -> bool:
        return self.primitives.output.output_mode in {"json_object", "json_array", "pydantic_model"}

    def _system_prompt(self) -> str:
        instructions = self.primitives.instructions
        sections = [
            f"Persona: {instructions.persona}",
            f"Goal: {instructions.goal}",
        ]
        if instructions.style:
            sections.append(f"Style: {instructions.style}")
        if instructions.boundaries:
            sections.append("Boundaries:\n" + "\n".join(f"- {item}" for item in instructions.boundaries))
        if instructions.principles:
            sections.append("Principles:\n" + "\n".join(f"- {item}" for item in instructions.principles))
        if instructions.few_shots:
            examples = []
            for example in instructions.few_shots:
                examples.append(f"User: {example.user}\nAssistant: {example.assistant}")
            sections.append("Few-shot examples:\n" + "\n\n".join(examples))

        sections.append(self._output_contract_prompt(self.primitives.output))
        toolset_prompt = self._toolset_prompt()
        if toolset_prompt:
            sections.append(toolset_prompt)
        knowledge_prompt = self._knowledge_prompt()
        if knowledge_prompt:
            sections.append(knowledge_prompt)
        guardrail_prompt = self._guardrail_prompt()
        if guardrail_prompt:
            sections.append(guardrail_prompt)
        handoff_prompt = self._handoff_prompt()
        if handoff_prompt:
            sections.append(handoff_prompt)
        return "\n\n".join(sections)

    def _output_contract_prompt(self, output: OutputSpec) -> str:
        if output.output_mode == "text":
            return "Output contract: return concise plain text."
        schema = json.dumps(output.schema_ or {}, ensure_ascii=False)
        return (
            f"Output contract: return valid {output.output_mode}. "
            f"Do not include markdown fences. Schema: {schema}"
        )

    def _toolset_prompt(self) -> str | None:
        if not self.primitives.toolsets.toolsets:
            return None
        lines = ["Toolsets are proposal-only. You may suggest tools, but do not execute them."]
        for toolset in self.primitives.toolsets.toolsets:
            exposed = ", ".join(toolset.exposed_tools) or "none"
            hidden = ", ".join(toolset.hidden_tools) or "none"
            lines.append(
                f"- {toolset.id}: exposed={exposed}; hidden={hidden}; "
                f"selection_strategy={toolset.selection_strategy}"
            )
        return "\n".join(lines)

    def _knowledge_prompt(self) -> str | None:
        if not self.primitives.knowledge.sources:
            return None
        lines = ["Knowledge sources available through managed context/retrieval:"]
        for source in self.primitives.knowledge.sources:
            citation = "citation_required" if source.citation_required else "citation_optional"
            lines.append(f"- {source.id}: type={source.type}; ref={source.ref}; {citation}")
        return "\n".join(lines)

    def _guardrail_prompt(self) -> str | None:
        if not self.primitives.guardrails.rules:
            return None
        lines = ["Guardrails:"]
        for rule in self.primitives.guardrails.rules:
            lines.append(
                f"- {rule.id}: stage={rule.stage}; action={rule.action}; risk={rule.risk_level}"
            )
        return "\n".join(lines)

    def _handoff_prompt(self) -> str | None:
        if not self.primitives.handoffs.targets:
            return None
        lines = ["Handoff targets:"]
        for target in self.primitives.handoffs.targets:
            lines.append(f"- {target.id}: type={target.type}; target={target.target_ref}")
        return "\n".join(lines)

    @staticmethod
    def _context_prompt(context_items: list[str]) -> str:
        return "Visible context:\n" + "\n".join(f"- {item}" for item in context_items)
