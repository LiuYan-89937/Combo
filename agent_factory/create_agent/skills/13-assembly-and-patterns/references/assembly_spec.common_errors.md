# Common Errors

- Binding a node id that is not present in the pattern.
- Referencing a pattern file that does not exist.
- Setting `assembly_spec.runtime.pattern_id` to an id that is neither a built-in RuntimeKernel pattern nor a `pattern_id` loaded from `agent_package.json.patterns[]`.
- Assuming the package pattern filename is the runtime id when the file content declares a different `pattern_id`.
- Embedding resources or secrets in graph definitions.
- Inventing node implementation ids not provided by builtin or package node providers.
