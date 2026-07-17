# Bundled inference sources

FastAgentFactory carries the two inference sources that are modified or benchmarked by this project:

- `llama.cpp-official`: unchanged baseline source at revision `f955e394bf94e01e5e36186d13c985727e5ef5b5`.
- `llama.cpp-amd`: AMD optimization source tree based on the same revision.

The AMD tree currently contains the same compute implementation as the official tree. It is built into a separately named binary and reported as `optimization_status=placeholder`. Future AMD/HIP kernel work belongs only in `llama.cpp-amd`; the official tree remains the reproducible benchmark baseline.

Both bundled source trees include llama.cpp's build-info templates but intentionally do not carry nested `.git` directories. Deployment passes the pinned upstream revision and build number to CMake explicitly, so `llama-server --version` remains deterministic after source synchronization.

Both source trees retain their upstream license and attribution files. Deployment synchronizes them to the inference host and builds them there.

Image inference is not an AMD kernel optimization target in this repository. The deployment controller clones `stable-diffusion.cpp` directly on the inference host at the pinned revision and initializes all recursive Git submodules before building `sd-server`. This keeps third-party sources complete without vendoring them into FastAgentFactory.
