---
name: 14-render-and-events
description: Use when creating or repairing render_manifest.json and runtime event semantics for CLI or WebUI rendering. Keeps UI semantic labels backend-owned.
metadata:
  system_boundary: render-events
  load_when: render, events, cli-ui, webui
---

# Render And Events

Render and events should be driven by package/runtime semantics, not frontend hardcoding.

Rules:

- `render_manifest.json` must reference actual graph nodes.
- Node labels should be clear and domain-neutral.
- Runtime events should carry semantic payload fields needed by UI.
- Do not rely on CLI-specific string parsing for business meaning.
- Long outputs should be artifact/report references when appropriate.

Acceptance:

- Render manifest can be loaded by package loader.
- Runtime events expose enough structure for CLI/WebUI to display progress without inferring business semantics.
