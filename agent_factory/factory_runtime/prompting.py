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
10. Do not wrap JSON in markdown fences."""


class FactoryPromptBuilder:
    def __init__(self, context_builder: FactoryContextBuilder | None = None) -> None:
        self.context_builder = context_builder or FactoryContextBuilder()

    def build_primitives_request(
        self,
        context: FactoryRunContext,
        *,
        requirement: str,
        requirement_analysis: dict | None = None,
    ) -> LLMRequest:
        schema = AgentPackagePrimitives.model_json_schema(by_alias=True)
        factory_context = self.context_builder.build_prompt_text(context, requirement=requirement)
        user_prompt = (
            "Create an AgentPackagePrimitives JSON object for this requirement.\n\n"
            f"Requirement:\n{requirement}\n\n"
            "RequirementAnalysis, if available:\n"
            f"{json.dumps(requirement_analysis or {}, ensure_ascii=False)}\n\n"
            f"Factory context:\n{factory_context}\n\n"
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
        user_prompt = (
            "Repair the previous AgentPackagePrimitives JSON so it matches the schema.\n"
            "Only fix schema/validation problems. Do not expand the user's requirement.\n\n"
            f"Requirement:\n{requirement}\n\n"
            f"Validation errors:\n{validation_errors}\n\n"
            "Previous JSON:\n"
            f"{json.dumps(raw_model_data, ensure_ascii=False)}\n\n"
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
