---
name: 15-scheduler-seed-system
description: Owns confirmed scheduler seed contract.
metadata:
  system_id: scheduler_seed_system
  stage_order: 15
  load_when: scheduler_seed_system
---
# Scheduler Seed System

## System Boundary
Owns confirmed scheduler seed contract.

## Stage Order
15. This skill is used only when `active_system.system_id` is `scheduler_seed_system`.

## Entry Conditions
Previous RuntimeKernel systems in stage order.

## Owned Files
- `contracts/scheduler_seed.json`

## Read-Only Dependencies
Read prior system outputs only. Do not modify files outside Owned Files.

## Required Resources
Use confirmed resource facts from `.factory/resources.json`.
Use Scheduler capabilities from Runtime Capability Inventory as the source of truth.
This system schedules when and how the Agent graph/tool/script is triggered; it does not imply any external delivery or notification capability unless that capability is already confirmed elsewhere in the inventory.

## Allowed Decisions
Make decisions only inside this system boundary. Prefer existing RuntimeKernel contracts and existing Gateway tools over inventing new mechanisms.

## Forbidden Actions
- Do not hardcode business resources, URLs, account values, schedules, or secrets.
- Do not treat a schedule as proof that an external delivery channel exists.
- Do not modify files owned by later systems.
- Do not expose manufacturing-only file tools as produced-agent runtime tools.
- Do not infer schema from project source code; read listed resources.

## Manufacturing Steps
1. Read this skill's schema and minimal example resources.
2. Materialize only Owned Files needed for this system.
3. Stop tool calls after writing this system's owned files; the graph runs this system's scoped validation automatically.
4. Repair only this system's owned files until validation passes.

## Validation
Use the active system's `validation_scope`. Do not run `full_static` unless this is `final_validation`.

## Exit Conditions
The scoped validator passes and the system stage is marked done by the runtime, not by the model.

## Resources
- `references/scheduler_seed_system.schema.json`
- `examples/scheduler_seed_system.minimal.json`
- `references/scheduler_seed_system.common_errors.md`
- `references/scheduler_seed_system.repair_hints.md`
- `references/scheduler_seed_system.validator_scope.md`
