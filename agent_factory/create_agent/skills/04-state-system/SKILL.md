---
name: 04-state-system
description: Guides package state contract and produced-agent state files.
metadata:
  system_id: state_system
  stage_order: 4
  load_when: state_system
---
# State System

## Role
Guides package state contract and produced-agent state files.

## Baseline Package Assumption
- The workspace starts with a scaffolded empty AgentPackage: required files, required contracts, and package asset directories already exist.
- Do not compare scaffolded files against schema or minimal examples just to prove they are valid. The validator owns schema correctness.
- Treat focus files as suggested edit surfaces, not write locks. Edit cross-file references when one capability requires a coherent package change.
- Use examples to learn the smallest complete shape for a capability you are adding or repairing, not as a checklist for unchanged scaffold files.
- Use schema resources only when validator evidence or an example is insufficient for a concrete failed path.

## When To Use This Skill
- The agent needs durable package state such as user preferences, watch lists, task queues, or settings.
- A tool or node reads/writes package state and the contract must describe that state.
- Validator reports state contract or state file issues.

## Focus Files
- `contracts/state.json`
- `state/package.schema.json`
- `state/package.initial.json`

## Manufacturing Protocol
1. Inspect current focus and latest validation evidence with create_agent_stage(action="inspect") when the next action is unclear.
2. Read the current target package files before editing. Preserve unrelated valid scaffold content.
3. If the requested capability does not affect this focus, leave these files unchanged and move to the next useful focus yourself.
4. When adding a capability, update all required package surfaces in one coherent step, then stop tool calls so graph validation can run.
5. When validation fails, repair only the target files and paths indicated by validator evidence; do not start a broad schema audit.

## Capability Write Guidance
- Create state files only when a real implemented capability needs package state.
- Define state shape from the capability, not from a business-specific hardcoded example.
- Keep initial state empty or user-confirmed; do not fabricate user data.
- When package tools mutate state, align their behavior with the state schema and initial file.

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
- `examples/state_system.minimal.json`

Repair references:
- `references/state_system.repair_hints.md`
- `references/state_system.common_errors.md`
- `references/state_system.validator_scope.md`

Schema reference, last resort:
- `references/state_system.schema.json`
