---
name: 13-assembly-and-patterns
description: Use when creating or repairing assembly_spec.json, pattern YAML, node ids, impl ids, bindings, edges, and compiler-visible graph semantics.
metadata:
  system_boundary: assembly-patterns
  load_when: assembly, pattern, binding, graph-compile-error
---

# Assembly And Patterns

Define executable graph semantics using RuntimeKernel-compatible nodes, impl ids, bindings, and edges.

Rules:

- Assembly runtime pattern id must reference an existing pattern file.
- Pattern node ids must match binding and state declarations.
- Use built-in node impls when they satisfy behavior.
- Use package-local nodes only for deterministic logic that cannot be expressed by built-ins.
- Do not embed runtime resources, secrets, URLs, or credentials in graph definitions.
- Termination semantics must be owned by pattern shape and compiler rules.

Acceptance:

- `AgentAssemblyCompiler` can compile the assembly.
- Every node impl id resolves through built-in or package node providers.
- Every binding type and payload matches RuntimeKernel schema.
