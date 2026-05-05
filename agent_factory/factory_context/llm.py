from __future__ import annotations

import json

from agent_factory.factory_context.envelope import FactoryContextEnvelope
from agent_factory.model.messages import MessageFactory
from agent_factory.model.types import LLMRequest


def apply_context_envelope(
    request: LLMRequest,
    envelope: FactoryContextEnvelope | None,
) -> LLMRequest:
    """Attach a stage-specific Factory context envelope to an LLM request.

    The envelope is intentionally a compact contract, not raw state. It tells
    the model which artifacts it may rely on, which inputs are forbidden, and
    which tools are available in the current stage.
    """

    if envelope is None:
        return request
    context = envelope.safe_prompt_context()
    metadata = dict(request.metadata)
    metadata["factory_context_envelope"] = {
        "stage": envelope.stage,
        "prompt_template_id": envelope.prompt_template_id,
        "output_schema": envelope.output_schema,
        "allowed_inputs": envelope.allowed_inputs,
        "forbidden_inputs": envelope.forbidden_inputs,
        "available_tools": envelope.available_tools,
    }
    context_message = MessageFactory.system(
        "Factory Context Envelope for this model call:\n"
        f"{json.dumps(context, ensure_ascii=False, indent=2)}\n\n"
        "Use only the allowed inputs, decision refs, and safe evidence refs above. "
        "Do not rely on forbidden inputs, raw evidence, secrets, temporary reasoning, "
        "or unconfirmed guesses."
    )
    return request.model_copy(
        update={
            "messages": [context_message, *request.messages],
            "metadata": metadata,
        }
    )
