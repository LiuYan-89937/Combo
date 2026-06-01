---
name: 03-context-contract
description: Use when an AgentPackage needs context assembly, compression, retrieval injection, or model input policy. Defines context contract boundaries and what must not be handled by context.
metadata:
  system_boundary: context-contract
  load_when: context, compression, retrieval, prompt-assembly
---

# Context Contract

Context controls model input preparation. It is not a business memory store and not a tool-output cleanup system.

Build rules:

- Configure compression, retrieval, and assembly policies only when the package needs them.
- Keep compression thresholds explicit and contract-valid.
- Context retrieval consumes selected sources; it must not perform every-turn automatic knowledge recall unless the package explicitly needs it.
- Tool output summarization belongs to the tool system, not the context contract.
- Cross-session facts belong to memory, not context compression.

When to include:

- Long-running conversations need compression.
- A node needs controlled prompt assembly from state, memory, knowledge, or artifacts.
- The package needs retrieval results injected before cognitive nodes.

Acceptance:

- Context contract builds `services.context_system` through RuntimeBuildPlanner.
- Context policy does not duplicate memory or knowledge responsibilities.
