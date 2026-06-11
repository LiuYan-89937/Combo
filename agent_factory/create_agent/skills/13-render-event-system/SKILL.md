---
name: 13-render-event-system
description: Guides render manifest and render contract updates for user-visible runtime experience.
metadata:
  system_id: render_event_system
  stage_order: 13
  load_when: render_event_system
---
# Render Event System

## Role
Guides render manifest and render contract updates for user-visible runtime experience.

## Baseline Package Assumption
- The workspace starts with a scaffolded empty AgentPackage: required files, required contracts, and package asset directories already exist.
- Do not compare scaffolded files against schema or minimal examples just to prove they are valid. The validator owns schema correctness.
- Treat focus files as suggested edit surfaces, not write locks. Edit cross-file references when one capability requires a coherent package change.
- Use examples to learn the smallest complete shape for a capability you are adding or repairing, not as a checklist for unchanged scaffold files.
- Use schema resources only when validator evidence or an example is insufficient for a concrete failed path.

## When To Use This Skill
- The package adds nodes, changes user-visible node labels/status text, or needs different render behavior.
- A custom pattern/node changes what should be visible to users.
- Validator reports render manifest or render contract issues.

## Focus Files
- `render_manifest.json`
- `contracts/render.json`

## Manufacturing Protocol
1. Inspect current focus and latest validation evidence with create_agent_stage(action="inspect") when the next action is unclear.
2. Read the current target package files before editing. Preserve unrelated valid scaffold content.
3. If the requested capability does not affect this focus, leave these files unchanged and move to the next useful focus yourself.
4. When adding a capability, update all required package surfaces in one coherent step, then stop tool calls so graph validation can run.
5. When validation fails, repair only the target files and paths indicated by validator evidence; do not start a broad schema audit.

## Capability Write Guidance
- Do not compare the default react_agent render_manifest.json with examples; the scaffold default is already valid.
- If the package still uses default react_agent nodes, leave render files unchanged.
- When new nodes are added, add only the corresponding render node specs and keep graph_id aligned with runtime pattern_id.

## Boundaries
- Do not hardcode secrets, API keys, account ids, external paths, URLs, schedules, delivery channels, or user data.
- Do not expose create-agent manufacturing tools, .factory files, traces, caches, or validation state as produced-agent runtime capability.
- Do not infer package schemas from project source code during manufacturing; use validator evidence and this skill's examples/resources.
- If required information is missing and cannot be discovered from confirmed resources, ask the user in natural language through create_agent_control.

## Validation And Focus
- Validator evidence should guide repairs but must not automatically change focus.
- Only explicit create_agent_stage(action="set_focus", focus_id=..., reason=...) changes focus.
- Run final validation only from validation_publish after the package behavior is actually implemented.

## Resource Loading
- Prefer examples when adding or repairing this capability.
- Read repair hints or validator scope only when validation evidence points here.
- Read schema only for a concrete validator failure path or when examples do not define the needed object shape.

Examples:
- `examples/render_event_system.minimal.json`

Repair references:
- `references/render_event_system.repair_hints.md`
- `references/render_event_system.common_errors.md`
- `references/render_event_system.validator_scope.md`

Schema reference, last resort:
- `references/render_event_system.schema.json`
