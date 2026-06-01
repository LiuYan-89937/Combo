---
name: 01-package-manifest
description: Use when creating or repairing AgentPackage root files and manifest references. Covers package identity, package-relative paths, required top-level files, and AgentPackageLoader acceptance.
metadata:
  system_boundary: package-manifest
  load_when: manifest-missing, package-load-failed, package-root-files
---

# Package Manifest

Materialize the AgentPackage identity and package-relative file map.

Required package files normally include:

- `agent_package.json`
- `assembly_spec.json`
- `resources.json`
- `render_manifest.json`
- `sandbox_contract.json`
- `contracts/*.json`
- `patterns/*.yaml`

Rules:

- All manifest paths must be package-relative and point inside the workspace.
- Every referenced file must exist.
- Package identity must be stable and descriptive.
- Do not write private user values, API keys, or secrets into package source files.
- Do not invent alternate manifest formats.

Acceptance:

- `AgentPackageLoader().load_path("agent_package.json")` can load the package.
- Every referenced file exists inside the create-agent workspace.
