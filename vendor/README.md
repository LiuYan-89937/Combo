# Bundled inference sources

FastAgentFactory carries two llama.cpp source trees so RadeonCloud deployment never needs to clone llama.cpp:

- `llama.cpp-official`: unchanged baseline source at revision `f955e394bf94e01e5e36186d13c985727e5ef5b5`.
- `llama.cpp-amd`: AMD optimization source tree based on the same revision.

The AMD tree currently contains the same compute implementation as the official tree. It is built into a separately named binary and reported as `optimization_status=placeholder`. Future AMD/HIP kernel work belongs only in `llama.cpp-amd`; the official tree remains the reproducible benchmark baseline.

Both trees retain the upstream llama.cpp license and attribution files.
