---
name: 07-memory-system
description: Guides memory contract changes for produced agents.
metadata:
  system_id: memory_system
  stage_order: 7
  load_when: memory_system
---
# Memory System

## Role
Guides memory contract changes for produced agents.

## Baseline Package Assumption
- The workspace starts with a scaffolded empty AgentPackage: required files, required contracts, and package asset directories already exist.
- Do not compare scaffolded files against schema or capability examples just to prove they are valid. The validator owns schema correctness.
- Treat focus files as suggested edit surfaces, not write locks. Edit cross-file references when one capability requires a coherent package change.
- Use examples to learn the smallest complete shape for a capability you are adding or repairing, not as a checklist for baseline scaffold files.
- Use schema resources only when validator evidence or an example is insufficient for a concrete failed path.

## When To Use This Skill
- The baseline scaffold includes memory because RuntimeKernel treats cross-session memory as a built-in agent capability.
- The agent needs custom memory scope, retention, ranking, or store behavior beyond the default contract.
- Validator reports memory contract issues.

## Focus Files
- `contracts/memory.json`

## Manufacturing Protocol
1. Inspect current focus and latest validation evidence with create_agent_stage(action="inspect") when the next action is unclear.
2. Read the current target package files before editing. Preserve unrelated valid scaffold content.
3. If the requested capability does not affect this focus, leave these files as-is and move to the next useful focus yourself.
4. When a complete capability increment is ready, update all required package surfaces coherently, then call create_agent_validate with the appropriate scope.
5. When validation fails, repair only validator-indicated target files and paths; do not start a broad schema audit.

## Capability Write Guidance
- Keep the scaffolded memory contract enabled unless validator evidence shows it is malformed.
- Do not rewrite memory settings unless a user requirement or validator issue requires a concrete change.
- Do not store sensitive user data unless the user explicitly wants that behavior and the runtime supports it.
- Keep memory scope and retention clear in the contract.
- Do not hand-edit contracts/memory.json during normal production; scaffold defaults are the supported memory baseline.

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
- Use a listed capability example when this skill provides one; otherwise rely on current package files and validator evidence.
- Read repair hints or validator scope only when validation evidence points here.
- Read schema only for a concrete validator failure path or when examples do not define the needed object shape.

Repair references:
- `references/memory_system.repair_hints.md`
- `references/memory_system.common_errors.md`
- `references/memory_system.validator_scope.md`

Schema reference, last resort:
- `references/memory_system.schema.json`
