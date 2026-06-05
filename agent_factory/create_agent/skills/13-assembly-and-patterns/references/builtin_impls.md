# Builtin Node Implementations

These are the ONLY valid `impl` values for pattern nodes (unless using a package node with `package.*` prefix).

- `cognitive.answer` (type: cognitive)
- `cognitive.clarify` (type: cognitive)
- `cognitive.plan` (type: cognitive)
- `cognitive.review` (type: cognitive)
- `cognitive.route` (type: cognitive)
- `cognitive.structured` (type: cognitive)
- `finalize` (type: reserved)
- `governance.approval_gate` (type: governance)
- `governance.postcheck` (type: governance)
- `governance.precheck` (type: governance)
- `governance.refusal_gate` (type: governance)
- `ingress` (type: reserved)
- `operational.resource_probe` (type: operational)
- `operational.tool_call` (type: operational)
- `terminal.close` (type: terminal)
- `terminal.commit` (type: terminal)

## Node Types

Valid values: `reserved`, `cognitive`, `operational`, `governance`, `terminal`, `sub_graph`

## Edge `when` Conditions

Extracted from builtin patterns:
- `always`
- `model.ready_to_answer`
- `model.requests_tool`
- `policy.approval_required`
- `policy.blocked`
- `subgraph.blocked`
- `subgraph.done`
- `subgraph.need_more_input`
- `tool.completed`
- `tool.failed`
- `tool.interrupted`

## Builtin Patterns

- `react_agent` — Standard conversational tool-using agent (default choice)
- `clarify_then_act` — Ask for missing info before entering action flow
- `clarification_loop_v1` — Embeddable subgraph for clarification (not selectable as main)
