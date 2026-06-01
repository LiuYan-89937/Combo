---
name: 05-knowledge-contract
description: Use when an AgentPackage needs runtime knowledge sources, cataloged documents, RAG, index-only sources, or the built-in knowledge tool. Defines source ownership and retrieval boundaries.
metadata:
  system_boundary: knowledge-contract
  load_when: knowledge, rag, documents, source-catalog
---

# Knowledge Contract

Knowledge manages external knowledge sources. Retrieval should enter through the `knowledge` tool unless the package has a specific runtime wrapper.

Build rules:

- Add knowledge only when the produced agent needs runtime knowledge sources.
- Use `index_only` for catalog plus keyword/FTS style lookup.
- Use `rag` only when chunking, embeddings, and semantic retrieval are needed.
- Keep source manifests and provenance explicit.
- Do not write user-private knowledge into package source files.
- Web sources should store URL, hash, metadata, and indexed text according to the knowledge system policy.
- Knowledge is not automatic every-turn context injection; context consumes selected knowledge results when requested.

Source handling:

- User-provided files become runtime-owned sources.
- MCP or managed remote sources remain referenced; do not copy remote implementation.
- Deleting a managed source should remove catalog/index facts and system-managed copies, not external originals.

Acceptance:

- Knowledge contract builds a runtime knowledge service.
- The tools contract exposes the `knowledge` system tool when retrieval is needed.
