---
name: 06-trace-contract
description: Use when an AgentPackage needs execution trace, debugging evidence, self-repair facts, or WebUI observability. Defines JSONL fact store and sensitive-output boundaries.
metadata:
  system_boundary: trace-contract
  load_when: trace, observability, self-repair, webui-monitoring
---

# Trace Contract

Trace records execution facts for observability and future repair. It must not own business state.

Build rules:

- Use append-only JSONL trace storage.
- Record run, node, model, tool, scheduler, artifact, and error correlation ids.
- Store summaries, counts, hashes, references, and report paths instead of large outputs.
- Do not record secrets in plaintext.
- Link tool outputs, artifacts, knowledge chunks, and reports by reference.
- Keep trace independent from graph execution semantics.

Acceptance:

- Trace contract contributes a runtime trace service.
- Failures are inspectable by trace reader or WebUI without parsing raw UI strings.
