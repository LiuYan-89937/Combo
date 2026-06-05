---
name: 03-context-contract
description: Use when configuring prompt context window management, compression, and retrieval injection policies.
metadata:
  system_boundary: context-contract
  load_when: context, compression, retrieval, prompt-assembly
---

# Context Contract

## When to load

Load when configuring context compression thresholds or retrieval injection policies.

## Hard Constraints

1. `contracts/context.json`: `"type": "context"`, `"version": "context_contract.v0"`
2. Context is NOT memory (cross-session) or knowledge (document store). It's model input preparation.

## Decision Rules

```
IF agent has long conversations (>10 turns):
  → Configure compression with appropriate token budget

IF agent is short-lived (scheduled reports, single-turn):
  → Keep default context contract (no compression needed)
```

## Minimal Example

```json
{
  "type": "context",
  "version": "context_contract.v0",
  "config": {}
}
```

## Resources

- `references/context_contract.schema.json`
- `examples/context_contract.minimal.json`
