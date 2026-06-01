---
name: 08-tools-contract
description: Use when deciding tool inheritance and tools contract content. Covers built-in tools, MCP, Skill, Knowledge, Scheduler, and when to generate package-specific tools.
metadata:
  system_boundary: tools-contract
  load_when: tools, mcp, skill, builtin-tools, tool-inheritance
---

# Tools Contract

Tools contract exposes runtime callable capabilities.

Rules:

- Inherit built-in runtime tools that are safe and relevant.
- MCP and Skill capabilities may be inherited only when useful at produced-agent runtime.
- Manufacturing-only tools should not be copied into the produced package.
- Package-generated tools are only for package-specific deterministic behavior; load `09-package-tools` before creating them.
- Tool calls during manufacturing must go through bound tools and Gateway.
- Do not duplicate existing tool capabilities.

Decision output:

- capability id
- selected source: builtin, mcp, skill, knowledge, scheduler, package_generated, or none
- selected tool ids or extension references
- runtime inheritance decision
- reason tied to package behavior

Acceptance:

- `tools` contract exposes inherited runtime capabilities.
- Extension references are declarations, not copied implementations.
