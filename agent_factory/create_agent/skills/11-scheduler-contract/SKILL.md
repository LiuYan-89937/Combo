---
name: 11-scheduler-contract
description: Use when configuring the scheduler runtime backend (SQLite store, timezone, failure policy). Required when using scheduler_seed or scheduler tool.
metadata:
  system_boundary: scheduler-contract
  load_when: scheduler, scheduler-tool, recurring-runtime, scheduler_seed
---

# Scheduler Contract

## When to load

Load this skill when the agent needs scheduling (defined by scheduler_seed) or runtime job management (scheduler tool).

## Hard Constraints

1. `contracts/scheduler.json` must have `"type": "scheduler"` and `"version": "scheduler_contract.v0"`.
2. If scheduler_seed exists, scheduler contract MUST have `config.store_path` set (non-empty).
3. `config.store_backend` must be `"sqlite"` (currently the only supported backend).

## Key Fields

```
SchedulerContract.config:
  store_backend: "sqlite"                       — only supported value
  store_path: str                               — e.g. ".agent_runtime/scheduler/scheduler.sqlite"
  timezone: str                                 — e.g. "Asia/Shanghai"
  default_timeout_seconds: int                  — job execution timeout (default 900)
  default_concurrency_policy: "skip"|"queue"|"replace"
  default_failure_policy:
    action: "pause"|"continue"|"disable"
    enabled: bool
    max_consecutive_failures: int
  unattended_policy: "deny_if_approval_required"|"allow"|"deny"
```

## Minimal Working Example

```json
{
  "type": "scheduler",
  "version": "scheduler_contract.v0",
  "config": {
    "store_backend": "sqlite",
    "store_path": ".agent_runtime/scheduler/scheduler.sqlite",
    "timezone": "Asia/Shanghai",
    "default_timeout_seconds": 900,
    "default_concurrency_policy": "skip",
    "default_failure_policy": {
      "action": "pause",
      "enabled": true,
      "max_consecutive_failures": 3
    },
    "unattended_policy": "deny_if_approval_required"
  }
}
```

## Relationship with Other Contracts

- **scheduler_seed** depends on scheduler: seeds reference the scheduler runtime to create jobs at startup
- **tools_contract**: when scheduler runtime is configured, the `scheduler` builtin tool is auto-injected (allows runtime job management via tool calls)

## Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| Scheduler tool not available | scheduler contract has no store_path | Set store_path |
| Seeds fail to apply | scheduler config missing or invalid | Ensure valid scheduler contract |
| SQLite error at runtime | store_path directory doesn't exist | Use `.agent_runtime/scheduler/` (runtime creates it) |

## Resources

- `references/scheduler_contract.schema.json` — SchedulerContract schema
- `examples/scheduler_contract.minimal.json` — Minimal valid scheduler contract
