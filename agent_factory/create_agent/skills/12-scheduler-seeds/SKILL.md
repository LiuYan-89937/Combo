---
name: 12-scheduler-seeds
description: Use when the agent needs recurring/scheduled jobs (daily push, periodic check). Covers scheduler_seed contract, cron syntax, target configuration, and slot binding.
metadata:
  system_boundary: scheduler-seed
  load_when: recurring-job, startup-schedule, scheduled-agent, semantic.scheduler_seed_missing
---

# Scheduler Seeds

## When to load

Load this skill when the user's request mentions timed/scheduled/daily/periodic behavior, or when validation reports `semantic.scheduler_seed_missing`.

## Hard Constraints

1. `contracts/scheduler_seed.json` must have `"type": "scheduler_seed"` and `"version": "scheduler_seed_contract.v0"`.
2. Each seed must have a unique `seed_id`.
3. `target.target_type = "graph_run"` requires `target.payload.message` (non-empty string).
4. `schedule_type` must be one of: `cron`, `interval`, `date`.
5. `source_slot_id` must match a `slot_id` in the pattern with `slot_type: "scheduler"`.
6. `scheduler_seed` contract must be added to `agent_package.json.contracts` (not auto-included by scaffold).

## Key Fields

```
SchedulerSeedPlan:
  seed_id: str              — unique identifier
  title: str                — human-readable name
  human_schedule: str       — natural language description (e.g. "每天早上9点")
  schedule_type: "cron" | "interval" | "date"
  schedule_expr: str        — cron: "0 9 * * *", interval: "3600" (seconds), date: ISO timestamp
  timezone: str             — default "Asia/Shanghai"
  target: SchedulerTarget
  task_content: str         — description of what the job does
  enabled_on_apply: bool    — default true
  source_slot_id: str       — links to pattern slot
  concurrency_policy: "skip" | "queue" | "replace"
  failure_policy: {action: "pause"|"continue"|"disable", enabled: bool, max_consecutive_failures: int}
  feedback: {enabled: bool, summary_model_role: "main"|"task", decision: "auto"|"manual"|"disabled"}

SchedulerTarget:
  target_type: "graph_run" | "script_run" | "tool_call"
  payload:
    For graph_run:
      message: str (required) — the user input to inject into the agent
      thread_policy: "new_thread_per_run" | "fixed_thread" | "inherit_agent_default"
      fixed_thread_id: str (required if thread_policy = "fixed_thread")
```

## Cron Expression Reference

Format: `minute hour day-of-month month day-of-week`

| Schedule | Cron |
|----------|------|
| Every day at 9:00 | `0 9 * * *` |
| Every day at 9:00 and 15:30 | Two seeds: `0 9 * * *` and `30 15 * * *` |
| Every Monday at 8:00 | `0 8 * * 1` |
| Every hour | `0 * * * *` |
| Every 30 minutes | `*/30 * * * *` |

## Minimal Working Example

```json
{
  "type": "scheduler_seed",
  "version": "scheduler_seed_contract.v0",
  "config": {
    "seeds": [
      {
        "seed_id": "daily_morning_report",
        "title": "Daily Morning Report",
        "human_schedule": "Every day at 9:00 AM Beijing time",
        "schedule_type": "cron",
        "schedule_expr": "0 9 * * *",
        "timezone": "Asia/Shanghai",
        "target": {
          "target_type": "graph_run",
          "payload": {
            "message": "Generate today's report based on the latest data.",
            "thread_policy": "new_thread_per_run"
          }
        },
        "task_content": "Generates a daily report using configured tools and data sources.",
        "enabled_on_apply": true,
        "source_slot_id": "recurring_report_request",
        "concurrency_policy": "skip",
        "failure_policy": {"action": "pause", "enabled": true, "max_consecutive_failures": 3},
        "feedback": {"enabled": false, "summary_model_role": "task", "decision": "disabled"}
      }
    ]
  }
}
```

## Integration Steps

1. Add `"scheduler_seed": "contracts/scheduler_seed.json"` to `agent_package.json.contracts`
2. Ensure `contracts/scheduler.json` has a valid config with `store_path` set
3. If using builtin `react_agent` pattern, the scheduler slot is already available as `recurring_report_request`
4. Set `source_slot_id` to match the pattern's scheduler slot

## Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `graph_run target payload requires message` | target.payload.message is empty | Add a meaningful message string |
| `duplicate scheduler seed_id` | Two seeds with same id | Use unique seed_ids |
| Contract not in agent_package.json | scheduler_seed not declared | Add to contracts map |
| `semantic.scheduler_seed_missing` | User requested scheduling but no seeds | Create this contract |

## Resources

- `references/scheduler_seed.schema.json` — SchedulerSeedContract schema
- `examples/scheduler_seed.minimal.json` — Minimal valid scheduler_seed
