"""Bottom-layer smoke test for primitives and ModelService.

This example intentionally constructs primitives in memory so we can verify the
LLM/message/output plumbing quickly. It is not the AgentFactory manufacturing
flow. In the real flow, AgentFactory writes an AgentPackage directory, then an
Agent runtime loads that package from YAML and runs it.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_factory.agent import PrimitiveAgent
from agent_factory.model import ModelService
from agent_factory.specs import (
    AgentPackagePrimitives,
    ConversationSpec,
    GuardrailSpec,
    HandoffSpec,
    InstructionSpec,
    KnowledgeSpec,
    Metadata,
    ObservabilitySpec,
    OutputSpec,
    RunContextSpec,
    ToolsetSpec,
)


def build_smoke_sample_agent(model_service: ModelService) -> PrimitiveAgent:
    metadata = Metadata(name="smoke-sample-agent", version="0.1.0")
    primitives = AgentPackagePrimitives(
        instructions=InstructionSpec(
            schema_version="0.1",
            metadata=metadata,
            persona="温和、专业、克制的资料整理 Agent",
            goal="识别用户意图，并用简洁中文给出下一步。",
            style="简洁、准确、不要承诺已执行真实业务操作。",
            boundaries=[
                "不能声称已经完成处理、记录创建或支付操作。",
                "如果需要真实业务操作，只能说明需要后续确认或工具执行。",
            ],
        ),
        output=OutputSpec(
            schema_version="0.1",
            metadata=metadata,
            output_mode="json_object",
            schema={
                "type": "object",
                "properties": {
                    "intent": {"type": "string"},
                    "answer": {"type": "string"},
                    "requires_human": {"type": "boolean"},
                },
                "required": ["intent", "answer", "requires_human"],
            },
        ),
        conversation=ConversationSpec(
            schema_version="0.1",
            metadata=metadata,
            history_window=8,
            summarize_after=16,
        ),
        run_context=RunContextSpec(
            schema_version="0.1",
            metadata=metadata,
        ),
        toolsets=ToolsetSpec(
            schema_version="0.1",
            metadata=metadata,
            toolsets=[],
        ),
        knowledge=KnowledgeSpec(
            schema_version="0.1",
            metadata=metadata,
            sources=[],
            retrievers=[],
            inject_as="none",
        ),
        guardrails=GuardrailSpec(
            schema_version="0.1",
            metadata=metadata,
            rules=[],
        ),
        handoffs=HandoffSpec(
            schema_version="0.1",
            metadata=metadata,
            targets=[],
        ),
        observability=ObservabilitySpec(
            schema_version="0.1",
            metadata=metadata,
            record_content=False,
        ),
    )
    return PrimitiveAgent(primitives=primitives, model_service=model_service)


async def main() -> None:
    model_service = ModelService.from_env()
    agent = build_smoke_sample_agent(model_service)
    result = await agent.run(
        "我想处理，但是不知道要准备什么材料。",
        context_items=[
            "处理咨询只能提供流程说明，不能承诺已经处理。",
            "如果用户没有记录号，先提示准备记录号和处理原因。",
        ],
        metadata={"example": "bottom_layer_smoke"},
    )
    if result.response.error:
        print(json.dumps(result.response.error.model_dump(), ensure_ascii=False, indent=2))
        return
    if result.structured_data is not None:
        print(json.dumps(result.structured_data, ensure_ascii=False, indent=2))
    else:
        print(result.response.content)


if __name__ == "__main__":
    asyncio.run(main())
