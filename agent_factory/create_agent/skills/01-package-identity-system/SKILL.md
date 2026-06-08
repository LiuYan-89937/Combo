---
name: 01-package-identity-system
description: Owns package identity and manifest references.
metadata:
  system_id: package_identity
  stage_order: 1
  load_when: package_identity
---
# Package Identity System

## System Boundary
Owns package identity and manifest references.

## Stage Order
1. This skill is used only when `active_system.system_id` is `package_identity`.

## Entry Conditions
Previous RuntimeKernel systems in stage order.

## Owned Files
- `agent_package.json`

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
- `references/package_identity.schema.json`
- `examples/package_identity.minimal.json`
- `references/package_identity.common_errors.md`
- `references/package_identity.repair_hints.md`
- `references/package_identity.validator_scope.md`
