from __future__ import annotations

import json
from typing import Any

from agent_factory.factory_runtime.context import FactoryRunContext
from agent_factory.factory_runtime.context_policy import FactoryContextPolicy
from agent_factory.factory_runtime.tool_policy import FactoryToolPolicy
from agent_factory.factory_runtime.redaction import redact_secrets


class FactoryContextBuilder:
    def __init__(self, policy: FactoryContextPolicy | None = None) -> None:
        self.policy = policy or FactoryContextPolicy()

    def build(self, context: FactoryRunContext, *, requirement: str) -> dict[str, Any]:
        payload: dict[str, Any] = {"requirement": requirement}
        if self.policy.include_workspace_summary:
            payload["workspace"] = {
                "workspace_path": str(context.workspace_path),
                "drafts_path": str(context.drafts_path),
                "memory_namespace": context.config.memory.namespace,
                "trace_enabled": context.config.trace.enabled,
            }
        if self.policy.include_tool_summary:
            payload["tool_policy"] = FactoryToolPolicy.from_registry(
                context.tool_registry
            ).model_dump(mode="json")
        if self.policy.include_recent_memory and self.policy.memory_limit > 0:
            payload["recent_factory_memory"] = [
                record.model_dump(mode="json")
                for record in context.memory_store.list_recent(self.policy.memory_limit)
            ]
        payload["forbidden_context"] = [
            ".env secrets",
            "provider API keys",
            "AgentInstance memory",
            "unredacted trace payloads",
        ]
        return redact_secrets(payload)

    def build_prompt_text(self, context: FactoryRunContext, *, requirement: str) -> str:
        return json.dumps(self.build(context, requirement=requirement), ensure_ascii=False, indent=2)
