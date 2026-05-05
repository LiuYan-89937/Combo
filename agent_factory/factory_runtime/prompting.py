from __future__ import annotations

import json

from agent_factory.factory_runtime.context import FactoryRunContext
from agent_factory.factory_runtime.context_builder import FactoryContextBuilder
from agent_factory.model import LLMRequest, MessageBuilder
from agent_factory.specs import AgentPackagePrimitives


FACTORY_SYSTEM_PROMPT = """You are AgentFactory, the control-plane agent builder.

Your job is to convert a user's natural language requirement into AgentPackagePrimitives.

Rules:
1. You are not the Agent being created.
2. Do not execute business tools or pretend external systems are integrated.
3. Do not expose or request secrets.
4. FactoryMemory and AgentInstance memory are completely isolated.
5. Output must be one valid JSON object matching AgentPackagePrimitives exactly.
6. Every required primitive must exist even when a capability is empty.
7. Toolsets are proposal-only; tools are declared, not executed.
8. If a real external API/MCP/tool is not provided, declare boundaries/stubs instead of inventing capability.
9. Prefer conservative, testable, traceable AgentPackage drafts.
10. Do not wrap json in markdown fences.
11. The first non-whitespace character of the final answer must be "{".
12. The last non-whitespace character of the final answer must be "}".
13. Never return a top-level JSON array/list.
14. Respect Context-first production artifacts: capability plans, resource contracts, readiness decisions, and implementation plans are stronger than guesses from the original wording."""


class FactoryPromptBuilder:
    def __init__(self, context_builder: FactoryContextBuilder | None = None) -> None:
        self.context_builder = context_builder or FactoryContextBuilder()

    def build_primitives_request(
        self,
        context: FactoryRunContext,
        *,
        requirement: str,
        requirement_analysis: dict | None = None,
        production_context: dict | None = None,
    ) -> LLMRequest:
        schema = AgentPackagePrimitives.model_json_schema(by_alias=True)
        example = _minimal_agent_package_example()
        factory_context = self.context_builder.build_prompt_text(context, requirement=requirement)
        user_prompt = (
            "Create an AgentPackagePrimitives json object for this requirement.\n"
            "Return exactly one JSON object. Never return a top-level JSON array/list.\n"
            "The top-level keys must be exactly: instructions, output, conversation, "
            "run_context, toolsets, knowledge, guardrails, handoffs, observability.\n\n"
            f"Requirement:\n{requirement}\n\n"
            "RequirementAnalysis, if available:\n"
            f"{json.dumps(requirement_analysis or {}, ensure_ascii=False)}\n\n"
            "Context-first production artifacts. These are confirmed decisions/evidence summaries. "
            "Use them as constraints; do not invent facts outside them:\n"
            f"{json.dumps(production_context or {}, ensure_ascii=False)}\n\n"
            f"Factory context:\n{factory_context}\n\n"
            "Minimal valid json object example:\n"
            f"{json.dumps(example, ensure_ascii=False)}\n\n"
            "AgentPackagePrimitives JSON Schema:\n"
            f"{json.dumps(schema, ensure_ascii=False)}"
        )
        return (
            MessageBuilder.start()
            .system(FACTORY_SYSTEM_PROMPT)
            .user(user_prompt)
            .request(
                response_format="json_schema",
                json_schema=schema,
                json_schema_name="AgentPackagePrimitives",
                json_schema_strict=True,
                metadata={
                    "factory_run_id": context.run_id,
                    "operation": "create_agent_primitives",
                },
            )
        )

    def build_repair_request(
        self,
        context: FactoryRunContext,
        *,
        requirement: str,
        raw_model_data: object,
        validation_errors: str,
    ) -> LLMRequest:
        schema = AgentPackagePrimitives.model_json_schema(by_alias=True)
        example = _minimal_agent_package_example()
        user_prompt = (
            "Repair the previous AgentPackagePrimitives json so it matches the schema.\n"
            "Only fix schema/validation problems. Do not expand the user's requirement.\n\n"
            "Return exactly one JSON object. Never return a top-level JSON array/list.\n"
            "If the previous value is a list, convert it into the required object shape.\n"
            "The top-level keys must be exactly: instructions, output, conversation, "
            "run_context, toolsets, knowledge, guardrails, handoffs, observability.\n\n"
            f"Requirement:\n{requirement}\n\n"
            f"Validation errors:\n{validation_errors}\n\n"
            "Previous JSON:\n"
            f"{json.dumps(raw_model_data, ensure_ascii=False)}\n\n"
            "Minimal valid json object example:\n"
            f"{json.dumps(example, ensure_ascii=False)}\n\n"
            "AgentPackagePrimitives JSON Schema:\n"
            f"{json.dumps(schema, ensure_ascii=False)}"
        )
        return (
            MessageBuilder.start()
            .system(FACTORY_SYSTEM_PROMPT)
            .user(user_prompt)
            .request(
                response_format="json_schema",
                json_schema=schema,
                json_schema_name="AgentPackagePrimitivesRepair",
                json_schema_strict=True,
                metadata={
                    "factory_run_id": context.run_id,
                    "operation": "repair_agent_primitives",
                },
            )
        )


def _minimal_agent_package_example() -> dict[str, object]:
    metadata = {
        "name": "example-agent",
        "version": "1.0.0",
        "description": "Example generated agent package primitives.",
    }
    return {
        "instructions": {
            "schema_version": "0.1",
            "kind": "InstructionSpec",
            "metadata": metadata,
            "persona": "A concise example assistant.",
            "goal": "Help the user with the requested task.",
            "style": "concise",
            "boundaries": [],
            "principles": [],
            "few_shots": [],
        },
        "output": {
            "schema_version": "0.1",
            "kind": "OutputSpec",
            "metadata": metadata,
            "output_mode": "text",
        },
        "conversation": {
            "schema_version": "0.1",
            "kind": "ConversationSpec",
            "metadata": metadata,
        },
        "run_context": {
            "schema_version": "0.1",
            "kind": "RunContextSpec",
            "metadata": metadata,
        },
        "toolsets": {
            "schema_version": "0.1",
            "kind": "ToolsetSpec",
            "metadata": metadata,
            "toolsets": [],
        },
        "knowledge": {
            "schema_version": "0.1",
            "kind": "KnowledgeSpec",
            "metadata": metadata,
            "sources": [],
            "retrievers": [],
            "inject_as": "none",
        },
        "guardrails": {
            "schema_version": "0.1",
            "kind": "GuardrailSpec",
            "metadata": metadata,
            "rules": [],
        },
        "handoffs": {
            "schema_version": "0.1",
            "kind": "HandoffSpec",
            "metadata": metadata,
            "targets": [],
        },
        "observability": {
            "schema_version": "0.1",
            "kind": "ObservabilitySpec",
            "metadata": metadata,
            "record_content": False,
        },
    }
