---
name: 10-package-nodes
description: Use when deterministic graph logic requires package-local nodes. Covers node provider contract, node manifests, NodeRuntimeContext, state write authorization, and Gateway-bound tool calls.
metadata:
  system_boundary: package-nodes
  load_when: package-node, node-provider, custom-node
---

# Package Nodes

Use package-local nodes for deterministic graph logic that is not a tool and not a built-in node.

Required shape:

- `nodes/<impl_id>/manifest.json`
- `nodes/<impl_id>/node.py`
- node input and output schemas
- readable and writable state sections
- required service declarations

Rules:

- Entrypoint must stay package-relative.
- Node code must use controlled `NodeRuntimeContext`.
- State writes must pass state contract validation.
- Tool calls from a node must go through controlled tool registry/Gateway.
- Do not expose raw RuntimeServices, raw LLM calls, or arbitrary subprocess execution.
- Use `cognitive.*` built-ins for model reasoning.

Acceptance:

- Node provider contract loads the package node.
- Assembly compiler resolves the impl id.
- State read/write sections are authorized.
