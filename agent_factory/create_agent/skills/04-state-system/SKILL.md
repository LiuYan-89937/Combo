---
name: 04-state-system
description: Owns state contract and package state files.
metadata:
  system_id: state_system
  stage_order: 4
  load_when: state_system
---
# State System

## System Boundary
Owns state contract and package state files.

## Stage Order
4. This skill is used only when `active_system.system_id` is `state_system`.

## Entry Conditions
Previous RuntimeKernel systems in stage order.

## Owned Files
- `contracts/state.json`
- `state/package.schema.json`
- `state/package.initial.json`

## Read-Only Dependencies
Read prior system outputs only. Do not modify files outside Owned Files.

## Required Resources
Use confirmed resource facts from `.factory/resources.json`. If required information is missing, ask the user through `create_agent_control(action=ask_user)` using natural language.

## Allowed Decisions
Make decisions only inside this system boundary. Prefer existing RuntimeKernel contracts and existing Gateway tools over inventing new mechanisms.

## Forbidden Actions
- Do not hardcode business resources, URLs, account values, schedules, or secrets.
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
- `references/state_system.schema.json`
- `examples/state_system.minimal.json`
- `references/state_system.common_errors.md`
- `references/state_system.repair_hints.md`
- `references/state_system.validator_scope.md`
