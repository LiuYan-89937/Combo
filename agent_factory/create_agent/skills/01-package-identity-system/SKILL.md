---
name: 01-package-identity-system
description: Guides AgentPackage manifest identity and package-level references after scaffold creation.
metadata:
  system_id: package_identity
  stage_order: 1
  load_when: package_identity
---
# Package Identity System

## Role
Guides AgentPackage manifest identity and package-level references after scaffold creation.

## Baseline Package Assumption
- The workspace starts with a scaffolded empty AgentPackage: required files, required contracts, and package asset directories already exist.
- Do not compare scaffolded files against schema or minimal examples just to prove they are valid. The validator owns schema correctness.
- Treat focus files as suggested edit surfaces, not write locks. Edit cross-file references when one capability requires a coherent package change.
- Use examples to learn the smallest complete shape for a capability you are adding or repairing, not as a checklist for unchanged scaffold files.
- Use schema resources only when validator evidence or an example is insufficient for a concrete failed path.

## When To Use This Skill
- The user request changes agent id, name, description, version, runtime pattern, or manifest resource indexes.
- Validator reports missing or invalid manifest references.
- A new package file is intentionally introduced and must be indexed in the manifest.

## Focus Files
- `agent_package.json`

## Manufacturing Protocol
1. Inspect current focus and latest validation evidence with create_agent_stage(action="inspect") when the next action is unclear.
2. Read the current target package files before editing. Preserve unrelated valid scaffold content.
3. If the requested capability does not affect this focus, leave these files unchanged and move to the next useful focus yourself.
4. When adding a capability, update all required package surfaces in one coherent step, then stop tool calls so graph validation can run.
5. When validation fails, repair only the target files and paths indicated by validator evidence; do not start a broad schema audit.

## Capability Write Guidance
- Keep `factory_run_id` only at the top level of `agent_package.json`; do not put it inside `agent_package.json.agent` or `assembly_spec.json.agent`.
- Do not rewrite the scaffolded contracts list unless adding or repairing a real package reference.
- If manifest arrays such as prompts/tools/patterns stay empty, that is acceptable unless the package actually adds those assets.
- When an asset is added, index the package-relative path in the correct manifest field and ensure the file exists.

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
- `examples/package_identity.minimal.json`

Repair references:
- `references/package_identity.repair_hints.md`
- `references/package_identity.common_errors.md`
- `references/package_identity.validator_scope.md`

Schema reference, last resort:
- `references/package_identity.schema.json`
