# Repair Hints

Keep pattern structure and assembly bindings synchronized. Resolve every impl id through builtin providers or package node manifests, and use contract-owned state/resource definitions instead of embedding values in graph files.

For `Unknown pattern` failures, first compare `assembly_spec.json.runtime.pattern_id` with the built-in pattern catalog and every package-local pattern id loaded from `agent_package.json.patterns[]`. Repair the id or manifest reference; do not move files or change file formats unless the manifest path or pattern file itself is invalid.
