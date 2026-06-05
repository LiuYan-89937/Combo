---
name: 01-package-manifest
description: Use when creating or repairing agent_package.json and top-level package references. Covers package identity, file paths, patterns field, and contracts field.
metadata:
  system_boundary: package-manifest
  load_when: manifest-missing, package-load-failed, package-root-files
---

# Package Manifest

## When to load

Load when working on `agent_package.json` or when validation reports missing manifest or file references.

## Hard Constraints

1. `agent_package.json` must be a valid `AgentPackageManifest` (see schema).
2. All paths in manifest must be package-relative and point to existing files inside the workspace.
3. `contracts` field must include ALL 14 required contract keys (see skill 02).
4. Do not write secrets into any package source file.

## Key Fields

```
agent_package.json:
  version: "agent_package.v0"
  factory_run_id: str
  agent: {id: str, name: str, description: str}
  assembly_spec_path: "assembly_spec.json"
  render_manifest_path: "render_manifest.json"
  resources_path: "resources.json"
  sandbox_contract_path: "sandbox_contract.json"
  contracts: {key: "contracts/key.json", ...}  — all 14 required
  patterns: []                                  — empty = use builtin pattern
  tools: []                                     — package tool manifest paths
  bindings: {}
```

## Decision Rules for `patterns` field

```
IF using builtin pattern (react_agent, clarify_then_act):
  → patterns: []
  → Do NOT create patterns/main.yaml (scaffold default is ignored)

IF using custom pattern:
  → patterns: ["patterns/main.yaml"]
  → The file must exist and contain a valid GraphPatternSpec
```

## Scaffold

`create_agent_scaffold(action=ensure_base_package)` generates all required files with valid defaults. Use it as the starting point, then customize contracts and assembly_spec.

## Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `missing required contracts` | Not all 14 keys in contracts field | Run scaffold or add missing keys |
| `package file not found` | Path in manifest points to non-existent file | Create the file or fix the path |
| `path escapes package root` | Absolute or `../` path used | Use package-relative paths only |

## Resources

- `references/agent_package.schema.json` — AgentPackageManifest schema
- `examples/agent_package.minimal.json` — Minimal valid manifest
