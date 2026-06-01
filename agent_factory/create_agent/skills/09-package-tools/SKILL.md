---
name: 09-package-tools
description: Use only when a package-specific generated tool is required. Covers tool assets, ToolSpec, schemas, dependency declarations, Gateway execution, and binding verification.
metadata:
  system_boundary: package-tools
  load_when: package-generated-tool, tool-compile-error, binding-smoke
---

# Package Tools

Create package tool assets only for package-specific deterministic behavior.

Required shape:

- `tools/<tool_id>/manifest.json`
- `tools/<tool_id>/tool.py`
- JSON schemas for input and output
- dependency declarations in the dependencies contract

Rules:

- Do not hard-code external hosts, URLs, accounts, tokens, file paths, or user preferences.
- Read external values from declared resource selectors.
- Network, API, empty-result, and authentication failures must return schema-valid business failure payloads.
- Avoid shelling out unless the declared tool purpose strictly requires it and Gateway policy allows it.
- Python dependencies must be declared for runtime installation.

Verification:

- `tool.py` compiles.
- Entrypoint signature matches the package tool convention.
- ToolSpec schemas are valid JSON Schema.
- Binding smoke uses compiled ToolSpec and Gateway path.

Acceptance:

- Tool assets are referenced by the tools contract.
- Package validator can load and compile the tool.
