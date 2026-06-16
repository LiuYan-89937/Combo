---
name: 02-model-system
description: Guides model, dependency, and sandbox runtime contract changes for produced agents.
metadata:
  system_id: model_system
  stage_order: 2
  load_when: model_system
---
# Model System

## Role
Guides model, dependency, and sandbox runtime contract changes for produced agents.

## Baseline Package Assumption
- The workspace starts with a scaffolded empty AgentPackage: required files, required contracts, and package asset directories already exist.
- Do not compare scaffolded files against schema or capability examples just to prove they are valid. The validator owns schema correctness.
- Treat focus files as suggested edit surfaces, not write locks. Edit cross-file references when one capability requires a coherent package change.
- Use examples to learn the smallest complete shape for a capability you are adding or repairing, not as a checklist for baseline scaffold files.
- Use schema resources only when validator evidence or an example is insufficient for a concrete failed path.

## When To Use This Skill
- The agent needs a non-default model role, output behavior, dependency declaration, or sandbox resource boundary.
- A package tool/node introduces runtime dependencies or sandbox resource requirements.
- Validator reports model/dependency/sandbox contract issues.

## Focus Files
- `contracts/model.json`
- `contracts/dependencies.json`
- `contracts/sandbox.json`
- `sandbox_contract.json`

## Manufacturing Protocol
1. Inspect current focus and latest validation evidence with create_agent_stage(action="inspect") when the next action is unclear.
2. Read the current target package files before editing. Preserve unrelated valid scaffold content.
3. If the requested capability does not affect this focus, leave these files as-is and move to the next useful focus yourself.
4. When adding a capability, update all required package surfaces in one coherent step, then call create_agent_validate with the appropriate scope.
5. When validation fails, repair only the target files and paths indicated by validator evidence; do not start a broad schema audit.

## Capability Write Guidance
- Leave default model/dependency/sandbox contracts as-is when the request does not require changes.
- Do not invent provider credentials, account ids, API keys, endpoints, or local paths.
- Declare dependencies and sandbox resources only for capabilities that are actually implemented in package files.
- If an external resource is required but not confirmed, ask the user before writing concrete config.

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
- `references/model_system.repair_hints.md`
- `references/model_system.common_errors.md`
- `references/model_system.validator_scope.md`

Schema reference, last resort:
- `references/model_system.schema.json`
