---
name: 12-scheduler-seeds
description: Use when a produced agent should prepare recurring jobs on startup. Covers scheduler_seed contract, user confirmation, cron/timezone validation, and idempotent runtime application.
metadata:
  system_boundary: scheduler-seed
  load_when: recurring-job, startup-schedule, scheduled-agent
---

# Scheduler Seeds

Scheduler seed expresses deployment-time scheduling intent. Runtime startup applies it to the real scheduler store.

Rules:

- Use `scheduler_seed` contract for package seed intent.
- Runtime startup applies confirmed seeds idempotently.
- Do not create scheduler SQLite rows during manufacturing.
- If time, timezone, or cadence is unclear, ask the user in natural language.
- Natural language schedule decisions must be represented as validated seed fields.
- Prefer target `graph_run` unless tool or script run is explicitly required.

Acceptance:

- `contracts/scheduler_seed.json` exists only when scheduling is needed.
- Seeds have deterministic ids, human schedule, schedule expression, timezone, target, and failure policy.
- Scheduler contract is included when scheduler seeds exist.
