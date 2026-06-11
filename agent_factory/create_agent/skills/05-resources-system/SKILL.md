---
name: 05-resources-system
description: Guides resource contract and confirmed resource facts.
metadata:
  system_id: resources_system
  stage_order: 5
  load_when: resources_system
---
# Resources System

## Focus Role
Guides resource contract and confirmed resource facts.

## Focus Use
5. Use this skill when it is relevant to the current manufacturing focus.

## Focus Context
Use when this knowledge helps the current manufacturing focus.

## Focus Files
- `contracts/resources.json`
- `resources.json`
- `.factory/resources.json`

## Cross-File Guidance
Focus files are suggested starting points. Cross-file package repairs are allowed when validator evidence requires them.

## Required Resources
Use confirmed resource facts from `.factory/resources.json`.
Before asking the user, check the Runtime Capability Inventory in the supervisor prompt.
Only ask for resources required by a confirmed runtime capability, inherited extension candidate, or verified package tool.
If the user asks for a capability that is not present in the inventory, describe it as not yet confirmed/supported instead of asking for its credentials.

## Allowed Decisions
Make decisions using this skill's domain knowledge while respecting validator evidence and package safety boundaries. Prefer existing RuntimeKernel contracts and existing Gateway tools over inventing new mechanisms.

## Forbidden Actions
- Do not hardcode business resources, URLs, account values, schedules, or secrets.
- Do not turn an unsupported or unconfirmed capability into a resource request.
- Prefer the current focus files, but repair cross-file references when validator evidence requires it.
- Do not expose manufacturing-only file tools as produced-agent runtime tools.
- Do not infer schema from project source code; read listed resources.

## Manufacturing Steps
1. Read this skill's schema and minimal example resources.
2. Update the focus files first, and cross-edit related package files when validation evidence requires it.
3. Stop tool calls after a coherent repair step; the graph runs validation automatically.
4. Repair the files indicated by validation evidence; focus files are guidance, not a write boundary.

## Validation
Use the active focus validation evidence. Run full validation only from the validation_publish focus when finalizing.

## Exit Conditions
Validator evidence should guide, not control, focus changes. Only explicit create_agent_stage set_focus calls change focus.

## Resources
- `references/resources_system.schema.json`
- `examples/resources_system.minimal.json`
- `references/resources_system.common_errors.md`
- `references/resources_system.repair_hints.md`
- `references/resources_system.validator_scope.md`
