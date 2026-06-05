---
name: 07-state-resources-contract
description: Use when configuring agent state namespaces and runtime resources. State is graph-owned data; resources are external configuration handles.
metadata:
  system_boundary: state-resources-contract
  load_when: state, resources, missing-resource, user-config
---

# State And Resources Contract

## When to load

Load when configuring `contracts/state.json` or `contracts/resources.json`, or when the agent needs runtime configuration values.

## Core Distinction

- **State** (`contracts/state.json`): Graph-internal data owned by the execution engine. Nodes read/write state sections.
- **Resources** (`contracts/resources.json`): External configuration the agent needs at runtime (API URLs, user preferences, file paths).

## Hard Constraints

1. `state.json`: `"type": "state"`, `"version": "state_contract.v0"`
2. `resources.json`: `"type": "resources"`, `"version": "resources_contract.v0"`
3. Secret values (API keys, tokens) MUST NOT be written into package source files.
4. If a required resource is unknown, ask the user via `create_agent_control(action=ask_user)`.

## Decision Rules

```
IF the agent needs to persist data between nodes within a run:
  → Define state namespaces in state contract

IF the agent needs external config (API URLs, user preferences):
  → Declare in resources contract
  → If the value is a secret, mark it and ask the user

IF the value can be discovered via public tools at runtime:
  → Do NOT hardcode it. Let the agent fetch it at runtime.
```

## Minimal State Contract

```json
{
  "type": "state",
  "version": "state_contract.v0",
  "config": {
    "namespaces": []
  }
}
```

## Minimal Resources Contract

```json
{
  "type": "resources",
  "version": "resources_contract.v0",
  "config": {
    "resources": {}
  }
}
```

## Resources

- `references/state_contract.schema.json`
- `references/resources_contract.schema.json`
- `examples/state_contract.minimal.json`
- `examples/resources_contract.minimal.json`
