---
name: 05-resources-system
description: Owns resource contract and confirmed resource facts.
metadata:
  system_id: resources_system
  stage_order: 5
  load_when: resources_system
---
# Resources System

## System Boundary
Owns resource contract and confirmed resource facts.

## Stage Order
5. This skill is used only when `active_system.system_id` is `resources_system`.

## Entry Conditions
Previous RuntimeKernel systems in stage order.

## Owned Files
- `contracts/resources.json`
- `resources.json`
- `.factory/resources.json`

## Read-Only Dependencies
Read prior system outputs only. Do not modify files outside Owned Files.

## Required Resources
Use confirmed resource facts from `.factory/resources.json`.
Before asking the user, check the Runtime Capability Inventory in the supervisor prompt.
Only ask for resources required by a confirmed runtime capability, inherited extension candidate, or verified package tool.
If the user asks for a capability that is not present in the inventory, describe it as not yet confirmed/supported instead of asking for its credentials.

## Allowed Decisions
Make decisions only inside this system boundary. Prefer existing RuntimeKernel contracts and existing Gateway tools over inventing new mechanisms.

## Forbidden Actions
- Do not hardcode business resources, URLs, account values, schedules, or secrets.
- Do not turn an unsupported or unconfirmed capability into a resource request.
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
- `references/resources_system.schema.json`
- `examples/resources_system.minimal.json`
- `references/resources_system.common_errors.md`
- `references/resources_system.repair_hints.md`
- `references/resources_system.validator_scope.md`
