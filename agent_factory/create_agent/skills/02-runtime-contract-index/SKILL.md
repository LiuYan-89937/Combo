---
name: 02-runtime-contract-index
description: Use when deciding which RuntimeContracts an AgentPackage needs. This is an index skill that routes to specific context, memory, knowledge, trace, state, tools, scheduler, and dependency contract skills.
metadata:
  system_boundary: runtime-contract-index
  load_when: contract-selection, runtime-build-failed
---

# Runtime Contract Index

Use RuntimeContracts for runtime capabilities instead of ad hoc package code.

Selection guide:

- Context behavior: load `03-context-contract`.
- Cross-session memory: load `04-memory-contract`.
- Runtime knowledge sources: load `05-knowledge-contract`.
- Execution trace and self-repair evidence: load `06-trace-contract`.
- State schemas and runtime resources: load `07-state-resources-contract`.
- Built-in, MCP, Skill, Scheduler, Knowledge, or generated tools: load `08-tools-contract`.
- Scheduler runtime configuration: load `11-scheduler-contract`.
- Startup recurring jobs: load `12-scheduler-seeds`.

Rules:

- Add a contract only when the package uses that capability.
- Use existing contract versions and schemas.
- Do not create one-off contract fields.
- Keep live runtime objects out of serializable resources.
- Repair schema failures; do not weaken validation.

Acceptance:

- `RuntimeBuildPlanner` can build all referenced contracts.
