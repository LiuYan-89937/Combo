---
name: 00-todo-control
description: Use when planning or updating create-agent manufacturing work. Defines todo completion rules, gating requirements, and the plan→execute→verify cycle.
metadata:
  system_boundary: manufacturing-control
  load_when: start, after-validation, before-finalize
---

# Todo Control

## When to load

This skill is always relevant. It governs the manufacturing progress lifecycle.

## Hard Constraints

1. `todo_control_plan` can only be marked `done` AFTER at least 1 concrete write/verify todo has been added via `create_agent_todo`.
2. Validator-gated todos (package_manifest, runtime_contracts, assembly_and_patterns, state_resources_render, tools_nodes_extensions, validate_agent_package) cannot be manually marked done — only the validator auto-marks them when the corresponding scope passes.
3. Required todos must end as `done`. Never mark required work `skipped_by_user`.
4. If user input is needed, call `create_agent_control(action=ask_user)`. Do not guess secrets or preferences.

## Manufacturing Lifecycle

```
1. Load this skill + plan
2. Add concrete todos for the user's specific requirements
3. Mark todo_control_plan done (requires at least 1 added todo)
4. Execute todos: load relevant skill → write files → validate
5. Validator auto-marks gated todos as scopes pass
6. Full validation (semantic + smoke test) marks remaining todos
7. All required done + validation passed → manufacturing complete
```

## Decision Rules for Adding Todos

```
IF user needs scheduled behavior:
  → Add todo: "Configure scheduler_seed with cron jobs"

IF user needs custom tools (API calls, data fetching):
  → Add todo: "Create package tool for [specific purpose]"

IF user needs specific prompt/persona:
  → Add todo: "Configure assembly bindings with system prompt"

For ALL agents:
  → The initial 7 todos handle structure. Add todos only for user-specific customization.
```

## Common Mistake

DO NOT mark `todo_control_plan` done immediately after receiving user input. You must first add at least one specific manufacturing todo that addresses the user's actual requirements.

## Resources

- Managed through `create_agent_todo` tool (list/add/update/upsert)
- Status: pending → in_progress → done (or failed_needs_repair)
