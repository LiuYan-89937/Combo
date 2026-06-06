---
name: 17-final-validation-repair
description: Owns final static validation and system-scoped repair routing.
metadata:
  system_id: final_validation
  stage_order: 17
  load_when: final_validation
---
# Final Validation Repair

## System Boundary
Owns final static validation and system-scoped repair routing.

## Stage Order
17. This skill is used only when `active_system.system_id` is `final_validation`.

## Entry Conditions
Previous RuntimeKernel systems in stage order.

## Owned Files
- No package files; validates whole package readiness.

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
3. Run `create_agent_validate` with this system's validation scope.
4. Repair only this system's owned files until validation passes.

## Validation
Use the active system's `validation_scope`. Do not run `full_static` unless this is `final_validation`.

## Exit Conditions
The scoped validator passes and the system stage is marked done by the runtime, not by the model.

## Resources
- `references/final_validation.schema.json`
- `examples/final_validation.minimal.json`
- `references/final_validation.common_errors.md`
- `references/final_validation.repair_hints.md`
- `references/final_validation.validator_scope.md`
