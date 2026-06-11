---
name: 09-tools-system
description: Guides runtime tool provider decisions and tools contract.
metadata:
  system_id: tools_system
  stage_order: 9
  load_when: tools_system
---
# Tools System

## Focus Role
Guides runtime tool provider decisions and tools contract.

## Focus Use
9. Use this skill when it is relevant to the current manufacturing focus.

## Focus Context
Use when this knowledge helps the current manufacturing focus.

## Focus Files
- `contracts/tools.json`

## Cross-File Guidance
Focus files are suggested starting points. Cross-file package repairs are allowed when validator evidence requires them.

## Required Resources
Use confirmed resource facts from `.factory/resources.json`.
Use Runtime Capability Inventory as the source of truth for available manufacturing tools, runtime builtin candidates, inherited extension candidates, and verified package tools.
If a requested runtime capability is not present in the inventory, do not represent it as supported; either choose an available candidate, generate a package tool in the package tool system, or ask the user for a provider decision.

## Allowed Decisions
Make decisions using this skill's domain knowledge while respecting validator evidence and package safety boundaries. Prefer existing RuntimeKernel contracts and existing Gateway tools over inventing new mechanisms.
Decide which inventory candidates should be declared in `contracts/tools.json`; do not expose manufacturing-only tools by default.

## Forbidden Actions
- Do not hardcode business resources, URLs, account values, schedules, or secrets.
- Do not promise runtime support for a capability absent from the inventory.
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
- `references/tools_system.schema.json`
- `examples/tools_system.minimal.json`
- `references/tools_system.common_errors.md`
- `references/tools_system.repair_hints.md`
- `references/tools_system.validator_scope.md`
