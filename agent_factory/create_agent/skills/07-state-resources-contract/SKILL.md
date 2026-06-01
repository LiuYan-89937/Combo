---
name: 07-state-resources-contract
description: Use when defining package state schemas, initial state, runtime resource requirements, and external resource facts. Covers state/resource separation and user-question handoff.
metadata:
  system_boundary: state-resources-contract
  load_when: state, resources, missing-resource, user-config
---

# State And Resources Contract

State is graph-owned data. Resources are runtime configuration and external handles.

Rules:

- State schema describes model-visible or graph-owned state.
- Runtime resources describe configurable values the agent needs at run time.
- Secret values must not be written into package source files.
- User-provided facts outrank discovered public facts.
- Public facts may be discovered through bound tools; private credentials must be requested from the user.
- If a required resource is missing, call `create_agent_control(action=ask_user, message=...)` with a concise natural-language question.
- Do not use local semantic regex extraction for dynamic resources; let the model structure user answers, then validate schemas.

Acceptance:

- State contract validates initial state.
- Resource selectors used by tools or nodes resolve to declared resources.
- Missing required resources are represented as user questions, not guessed defaults.
