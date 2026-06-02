---
name: 15-validation-repair
description: Use whenever .factory/validation.json reports failure. Converts validator failures into concrete repair todos and keeps the ReAct loop running until validation passes.
metadata:
  system_boundary: validation-repair
  load_when: validation-failed, repair-loop, before-finalize
---

# Validation Repair

Treat validator output as authoritative.

Rules:

- Do not hide, bypass, or weaken validation.
- Convert each issue into a repair todo through `create_agent_todo` if it is not already present.
- Repair the named file or contract through bound tools.
- Mark a repair todo `done` through `create_agent_todo` only after the specific failure is gone.
- Do not finalize while package validation fails or any required todo is incomplete.

Repair loop:

- Read `.factory/validation.json` through workspace file tools.
- Call `create_agent_todo list`.
- Use `recommended_skill` and `recommended_resources` from the validation report.
- Load the recommended skill, read the recommended resources, then repair target files.
- Run validation through `create_agent_validate` or finalize through `create_agent_control`.
- Update todo statuses through `create_agent_todo` with evidence.
- Continue until validation passes and required todos are done.

Resources:

- `references/validation_report.schema.json`
- `examples/validation_report.minimal.json`
- `references/validation_report.common_errors.md`
- `references/validation_report.repair_hints.md`

Acceptance:

- Latest `.factory/validation.json` has `status: passed`.
- All required repair todos are `done`.
