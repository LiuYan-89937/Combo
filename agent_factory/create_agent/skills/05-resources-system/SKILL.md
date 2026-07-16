---
name: 05-resources-system
description: Guides confirmed resource facts and runtime resource descriptors for produced agents.
metadata:
  system_id: resources_system
  stage_order: 5
  load_when: resources_system
---
# Resources System

## Role
Guides confirmed resource facts and runtime resource descriptors for produced agents.

## Baseline Package Assumption
- The workspace starts with a scaffolded empty AgentPackage: required files, required contracts, and package asset directories already exist.
- Do not compare scaffolded files against schema or capability examples just to prove they are valid. The validator owns schema correctness.
- Treat focus files as suggested edit surfaces, not write locks. Edit cross-file references when one capability requires a coherent package change.
- Use examples to learn the smallest complete shape for a capability you are adding or repairing, not as a checklist for baseline scaffold files.
- Use schema resources only when validator evidence or an example is insufficient for a concrete failed path.

## When To Use This Skill
- The agent needs user-confirmed resources, accounts, secrets, URLs, files, delivery channels, or external services.
- A capability cannot be implemented without a concrete resource fact.
- Validator or manufacturing state indicates pending user input for resources.

## Focus Files
- `contracts/resources.json`
- `.factory/resources.json`

## Manufacturing Protocol
1. Inspect current focus and latest validation evidence with create_agent_stage(action="inspect") when the next action is unclear.
2. Read the current target package files before editing. Preserve unrelated valid scaffold content.
3. If the requested capability does not affect this focus, leave these files as-is and move to the next useful focus yourself.
4. When a complete capability increment is ready, update all required package surfaces coherently, then call create_agent_validate with the appropriate scope.
5. When validation fails, repair only validator-indicated target files and paths; do not start a broad schema audit.

## Capability Write Guidance
- `contracts/resources.json` is the only published package resource surface; it declares resource descriptors and never stores user values.
- Use .factory/resources.json only as confirmed manufacturing facts; do not expose it as a produced-agent runtime tool.
- Write produced-agent resource descriptors with create_agent_authoring(action="upsert_resources", resources={}, resource_descriptors=[...]) instead of generic filesystem write.
- Before asking, check capability inventory and existing confirmed facts.
- Ask only for resources required by an implemented or confirmed capability, never for unsupported capability guesses.

## Boundaries
- Do not hardcode secrets, API keys, account ids, external paths, URLs, schedules, delivery channels, user data, or runtime resource values. Runtime values are collected after publication through the package resource form.
- Do not expose create-agent manufacturing tools, .factory files, traces, caches, or validation state as produced-agent runtime capability.
- Do not infer package schemas from project source code during manufacturing; use validator evidence and this skill's examples/resources.
- If required information is missing and cannot be discovered from confirmed resources, ask the user in natural language through create_agent_control.

## Validation And Focus
- Validator evidence guides repairs; successful or failed deterministic authoring, probe, validation, and publish operations synchronize focus through the manufacturing state machine.
- Use `create_agent_stage(action="set_focus", focus_id=..., reason=...)` only to correct or intentionally redirect focus.
- Finalization requires `validation_publish` and a fresh passed `full_static` validation; `create_agent_control(action="finalize")` then publishes automatically.

## Resource Loading
- Use a listed capability example when this skill provides one; otherwise rely on current package files and validator evidence.
- Read repair hints or validator scope only when validation evidence points here.
- Read schema only for a concrete validator failure path or when examples do not define the needed object shape.

Repair references:
- `references/resources_system.repair_hints.md`
- `references/resources_system.common_errors.md`
- `references/resources_system.validator_scope.md`

Schema reference, last resort:
- `references/resources_system.schema.json`
