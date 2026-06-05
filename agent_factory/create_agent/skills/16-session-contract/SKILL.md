---
name: 16-session-contract
description: Use when configuring session persistence (checkpointing, session storage). Controls whether agent state survives restarts.
metadata:
  system_boundary: session-contract
  load_when: session-contract, runtime-contract-build-failed, checkpoint
---

# Session Contract

## When to load

Load when configuring session persistence behavior.

## Hard Constraints

1. `contracts/session.json`: `"type": "session"`, `"version": "session_contract.v0"`
2. Paths must stay inside the runtime sandbox.

## Decision Rules

```
IF agent needs persistent sessions (multi-turn conversations):
  → Configure checkpointer with sqlite backend

IF agent is ephemeral (scheduled reports, single-shot):
  → Keep default (memory backend, no persistence)
```

## Minimal Example

```json
{
  "type": "session",
  "version": "session_contract.v0",
  "config": {}
}
```

## Resources

- `references/session_contract.schema.json`
- `examples/session_contract.minimal.json`
