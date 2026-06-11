---
name: 17-final-validation-repair
description: Guides final static validation and system-scoped repair routing.
metadata:
  system_id: final_validation
  stage_order: 17
  load_when: final_validation
---
# Final Validation Repair

## Focus Role
Guides final static validation and system-scoped repair routing.

## Focus Use
17. Use this skill when it is relevant to the current manufacturing focus.

## Focus Context
Use when this knowledge helps the current manufacturing focus.

## Focus Files
- No package files; validates whole package readiness.

## Cross-File Guidance
Focus files are suggested starting points. Cross-file package repairs are allowed when validator evidence requires them.

## Required Resources
Use confirmed resource facts from `.factory/resources.json`. If required information is missing, ask the user through `create_agent_control(action=ask_user)` using natural language.

## Allowed Decisions
Make decisions using this skill's domain knowledge while respecting validator evidence and package safety boundaries. Prefer existing RuntimeKernel contracts and existing Gateway tools over inventing new mechanisms.

## Forbidden Actions
- Do not hardcode business resources, URLs, account values, schedules, or secrets.
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
- `references/final_validation.schema.json`
- `examples/final_validation.minimal.json`
- `references/final_validation.common_errors.md`
- `references/final_validation.repair_hints.md`
- `references/final_validation.validator_scope.md`
