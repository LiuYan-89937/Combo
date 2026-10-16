from __future__ import annotations

from typing import Any

from combo.context_system.assembly import assemble_context_frame
from combo.context_system.memory_context import MEMORY_CONTEXT_KEY, MEMORY_CONTEXT_VERSION
from combo.context_system.schema import ContextPolicy, ContextQuery, CrossSessionMemoryPolicy
from combo.context_system.sources import memory_candidate
from combo.runtime_protocol import RuntimeExecutionIdentity
from combo.runtime_protocol.memory_operations import MemoryChangeSet, MemorySelector, memory_target
from combo.tooling.builtins.runtime_ports import MemoryRuntimePort
from combo.tooling.builtins.memory.specs import MEMORY_STORE_RESOURCE, RUNTIME_IDENTITY_RESOURCE
from combo.tooling.envelope import tool_envelope
from combo.tooling.targets import select_target


READ_ACTIONS = frozenset({"search", "list", "read"})
MUTATION_ACTIONS = frozenset({"write", "update", "merge", "delete"})


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    action = arguments.get("action")
    if action in READ_ACTIONS:
        return {"action": "allow", "risk_level": "low", "reasons": ["read-only scoped memory operation"]}
    resources = context.get("resources") or {}
    identity = resources.get(RUNTIME_IDENTITY_RESOURCE) or {}
    if action in MUTATION_ACTIONS and identity.get("runtime_role") == "main" and identity.get("memory_agent_write_enabled", True):
        return {"action": "allow", "risk_level": "medium", "reasons": ["enabled scoped memory management"]}
    return {"action": "deny", "risk_level": "medium", "reasons": ["memory mutation is unavailable in this runtime"]}


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    store = resources.get(MEMORY_STORE_RESOURCE)
    identity = resources.get(RUNTIME_IDENTITY_RESOURCE)
    if not isinstance(store, MemoryRuntimePort):
        raise RuntimeError("memory store is not configured")
    if not isinstance(identity, RuntimeExecutionIdentity):
        raise RuntimeError("memory tool requires an owned runtime execution identity")
    action = arguments["action"]
    owner = dict(principal_id=identity.principal_id, workspace_id=identity.workspace_id,
                 session_id=identity.session_id)
    policy = CrossSessionMemoryPolicy.model_validate(identity.memory_policy)
    if action == "search":
        query = ContextQuery(node_id="memory.search", components={"explicit_query": arguments["query"]},
                             limit=policy.max_candidates, min_relevance=policy.min_relevance)
        candidates = [memory_candidate(item, origin="explicit") for item in store.search(
            **owner, query=arguments["query"], limit=policy.max_candidates, min_relevance=policy.min_relevance,
            scope=arguments.get("scope"), kind=arguments.get("kind"),
        )]
        frame = assemble_context_frame(node_id=query.node_id, query=query, candidates=candidates,
                                       policy=ContextPolicy(cross_session_memory=policy).assembly_policy())
        output = {
            "action": action, "query": arguments["query"],
            MEMORY_CONTEXT_KEY: {"version": MEMORY_CONTEXT_VERSION,
                                 "runtime_instance_id": identity.runtime_instance_id,
                                 "items": [item.model_dump(mode="json") for item in frame.items]},
            "selection": frame.decisions,
        }
    elif action == "list":
        offset = arguments.get("offset", 0)
        items = store.list_active(**owner, scope=arguments.get("scope"), kind=arguments.get("kind"),
                                  offset=offset, limit=policy.max_candidates + 1)
        output = {"action": action, "memories": [memory_target(item) for item in items[:policy.max_candidates]],
                  "next_offset": offset + policy.max_candidates if len(items) > policy.max_candidates else None}
    elif action == "read":
        selector = MemorySelector.model_validate(arguments["memory"])
        selected = select_target(store.list_active(**owner, limit=None),
                                 selector=selector.model_dump(exclude_none=True),
                                 describe=memory_target, kind="memory")
        output = {"action": action, "memory": memory_target(selected)}
    elif action in MUTATION_ACTIONS:
        if identity.runtime_role != "main" or not identity.memory_agent_write_enabled:
            raise PermissionError("memory mutation is unavailable in this runtime")
        changes = MemoryChangeSet.model_validate({"operations": [arguments]})
        revisions = store.apply_changes(**owner, changes=changes, source_session_id=identity.session_id,
                                        source_turn_id=identity.turn_id,
                                        runtime_instance_id=identity.runtime_instance_id)
        output = {"action": action, "memories": [
            {**memory_target(item), "status": item.status} for item in revisions
        ]}
    else:
        raise ValueError("unsupported memory action")
    return tool_envelope(output, summary=f"memory {action} completed")
