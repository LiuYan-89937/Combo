---
name: 11-scheduler-contract
description: Use when an AgentPackage needs scheduler runtime services or scheduler tool access. Clarifies scheduler runtime contract versus scheduler seed contract.
metadata:
  system_boundary: scheduler-contract
  load_when: scheduler, scheduler-tool, recurring-runtime
---

# Scheduler Contract

Scheduler contract provides runtime scheduling services and scheduler tool access.

Rules:

- Include scheduler when the package needs to create, inspect, pause, resume, or execute scheduled jobs at runtime.
- Do not write scheduler job store rows during manufacturing.
- Use scheduler seed for startup-prepared recurring jobs; load `12-scheduler-seeds`.
- Scheduler runtime is a live object and must not be placed in serializable runtime resources.
- Scheduler tool calls must go through Gateway.

Acceptance:

- Scheduler contract builds scheduler runtime services.
- Tools contract exposes scheduler tool only when runtime management is needed.
