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

```text
read .factory/validation.json
call create_agent_todo list
identify failing file, contract, pattern, binding, state, or tool
edit package files through tools
run package validation
update todo statuses through create_agent_todo with evidence
continue until validation passes and required todos are done
```

Helper script:

```bash
python3 -m agent_factory.create_agent.scripts.validate_package <workspace> --out .factory/validation.json
```

Acceptance:

- Latest `.factory/validation.json` has `status: passed`.
- All required repair todos are `done`.
