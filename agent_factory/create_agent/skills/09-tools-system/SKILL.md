---
name: 09-tools-system
description: Owns runtime tool provider decisions and tools contract.
metadata:
  system_id: tools_system
  stage_order: 9
  load_when: tools_system
---
# Tools System

## System Boundary
Owns runtime tool provider decisions and tools contract.

## Stage Order
9. This skill is used only when `active_system.system_id` is `tools_system`.

## Entry Conditions
Previous RuntimeKernel systems in stage order.

## Owned Files
- `contracts/tools.json`

## Read-Only Dependencies
Read prior system outputs only. Do not modify files outside Owned Files.

## Required Resources
Use confirmed resource facts from `.factory/resources.json`.
Use Runtime Capability Inventory as the source of truth for available manufacturing tools, runtime builtin candidates, inherited extension candidates, and verified package tools.
If a requested runtime capability is not present in the inventory, do not represent it as supported; either choose an available candidate, generate a package tool in the package tool system, or ask the user for a provider decision.

## Allowed Decisions
Make decisions only inside this system boundary. Prefer existing RuntimeKernel contracts and existing Gateway tools over inventing new mechanisms.
Decide which inventory candidates should be declared in `contracts/tools.json`; do not expose manufacturing-only tools by default.

## Forbidden Actions
- Do not hardcode business resources, URLs, account values, schedules, or secrets.
- Do not promise runtime support for a capability absent from the inventory.
- Do not modify files owned by later systems.
- Do not expose manufacturing-only file tools as produced-agent runtime tools.
- Do not infer schema from project source code; read listed resources.

## Manufacturing Steps
1. Read this skill's schema and minimal example resources.
2. Materialize only Owned Files needed for this system.
3. Run `create_agent_validate` with this system's validation scope.
4. Repair only this system's owned files until validation passes.

## Validation
Use the active system's `validation_scope`. Do not run `full_static` unless this is `final_validation`.

## Exit Conditions
The scoped validator passes and the system stage is marked done by the runtime, not by the model.

## Resources
- `references/tools_system.schema.json`
- `examples/tools_system.minimal.json`
- `references/tools_system.common_errors.md`
- `references/tools_system.repair_hints.md`
- `references/tools_system.validator_scope.md`
