---
name: 04-memory-contract
description: Use when the agent needs cross-session persistent memory. Covers store backends, write_enabled flag, and namespace isolation.
metadata:
  system_boundary: memory-contract
  load_when: memory, cross-session, long-term-facts
---

# Memory Contract

## When to load

Load when the agent should remember facts/preferences across sessions.

## Hard Constraints

1. `contracts/memory.json`: `"type": "memory"`, `"version": "memory_contract.v0"`
2. Do not store secrets or credentials as memory facts.

## Decision Rules

```
IF agent needs cross-session memory (user preferences, learned facts):
  → Set config.write_enabled = true
  → Configure store backend

IF agent is stateless (each run independent):
  → Keep default (write_enabled: false)
```

## Key Fields

```
config.memory_system:
  write_enabled: bool     — enables memory writes
  store:
    backend: "memory" | "sqlite" | "mongodb"
    path: str             — for sqlite: ".agent_runtime/memory/memory.sqlite"
    connection_uri: str   — for mongodb
```

## Minimal Example (memory disabled)

```json
{
  "type": "memory",
  "version": "memory_contract.v0",
  "config": {
    "memory_system": {
      "write_enabled": false,
      "store": {"backend": "memory"}
    }
  }
}
```

## Resources

- `references/memory_contract.schema.json`
- `examples/memory_contract.minimal.json`
