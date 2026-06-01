---
name: 00-todo-control
description: Use when planning or updating create-agent manufacturing work. Defines .factory/todo.json as the progress source, required todo completion rules, repair todo behavior, and user-question handoff.
metadata:
  system_boundary: manufacturing-control
  load_when: start, after-validation, before-finalize
---

# Todo Control

Use `create_agent_todo` as the controlled interface for the manufacturing progress source.

Rules:

- Add todos through `create_agent_todo` for concrete RuntimeKernel-verifiable work, not broad stages.
- Required todos must end as `done`; do not mark required work `skipped_by_user`.
- Mark a todo `done` through `create_agent_todo` only when its acceptance condition is directly true in the workspace.
- If user input is needed, call `create_agent_control` with `action=ask_user` and a concise natural-language question.
- Keep repair todos deduplicated by validation issue.

Recommended groups:

- package identity and manifest
- runtime contracts
- assembly and patterns
- state and resources
- tools and extensions
- package tools or package nodes, if needed
- scheduler seed, if needed
- render/events
- validation repair

Acceptance:

- `create_agent_todo list` returns the current todo state.
- No required todo is pending, in progress, blocked, failed, or skipped at finalization.
