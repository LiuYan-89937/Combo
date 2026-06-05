---
name: 15-validation-repair
description: Use whenever validation reports failure. Guides the repair loop for all validation stages including semantic completeness and smoke test.
metadata:
  system_boundary: validation-repair
  load_when: validation-failed, repair-loop, before-finalize, semantic.pattern_logic, semantic.bindings_empty, semantic.scheduler_seed_missing, smoke_test
---

# Validation Repair

## When to load

Load when `.factory/validation.json` reports `status: "failed"`.

## Hard Constraints

1. Validator output is authoritative. Do not bypass or weaken validation.
2. Do not finalize while validation fails.
3. Each validation issue must be repaired by fixing the target files, not by changing the validator.

## Validation Stages (in order)

| Stage | What it checks | Common failure |
|-------|---------------|----------------|
| workspace_hygiene | JSON/YAML syntax | Trailing comma, malformed JSON |
| json_syntax | All critical JSON files parseable | Invalid JSON in contracts or state |
| package_shape | Manifest + 14 contracts + file existence | Missing contract files |
| runtime_contract_build | RuntimeBuildPlanner can build all contracts | Schema violations in contract config |
| assembly_compile | AgentAssemblyCompiler can compile | Unknown node impl, invalid bindings |
| semantic_completeness | Pattern has logic, bindings non-empty, scheduler configured | Empty scaffold defaults |
| smoke_test | Agent runs with task_model and produces output | Runtime crash, no final_answer |

## Repair Strategy by Error Type

```
IF "Unknown node impl: X":
  → Load skill 13. Use only builtin impls from references/builtin_impls.md.
  → Most likely fix: use "react_agent" builtin pattern instead of custom.

IF "semantic.pattern_logic":
  → Use builtin pattern (assembly_spec.runtime.pattern_id = "react_agent")
  → Set agent_package.json.patterns = []

IF "semantic.bindings_empty":
  → Usually resolved by using builtin pattern (it has default bindings)
  → If custom pattern, add service bindings (see skill 13)

IF "semantic.scheduler_seed_missing":
  → Load skill 12. Create contracts/scheduler_seed.json with cron jobs.
  → Add to agent_package.json.contracts.

IF "smoke_test" failure:
  → Check if tools are configured correctly (skill 08)
  → Verify assembly bindings reference correct node IDs
  → Ensure the pattern routes to cognitive.answer for user interaction

IF "json_syntax" or "workspace_hygiene.parse":
  → Read the target file, fix JSON syntax error, rewrite
```

## Repair Loop

1. Read validation report (from repair_context or .factory/validation.json)
2. Identify the first blocking issue
3. Load the `recommended_skill` from the issue
4. Read `recommended_resources` for schema/examples
5. Fix the target file
6. Run `create_agent_validate(scope="full_static")`
7. If still failing, repeat from step 2

## Resources

- `references/validation_report.schema.json`
- `examples/validation_report.minimal.json`
