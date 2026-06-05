---
name: 06-trace-contract
description: Use when configuring execution trace and observability. Covers trace storage, output mode, and what to record.
metadata:
  system_boundary: trace-contract
  load_when: trace, observability, debugging, monitoring
---

# Trace Contract

## When to load

Load when configuring observability or debugging capabilities for the agent.

## Hard Constraints

1. `contracts/trace.json`: `"type": "trace"`, `"version": "trace_contract.v0"`
2. Do not record secrets in plaintext in trace output.
3. Trace is append-only; it does not own business state.

## Decision Rules

```
IF agent is production-facing and needs debugging:
  → Enable trace with appropriate output_mode

IF agent is a simple utility:
  → Keep default trace contract
```

## Minimal Example

```json
{
  "type": "trace",
  "version": "trace_contract.v0",
  "config": {}
}
```

## Resources

- `references/trace_contract.schema.json`
- `examples/trace_contract.minimal.json`
