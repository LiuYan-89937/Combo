[English](README.md) | [简体中文](README.zh-CN.md)

# FastAgentFactory

FastAgentFactory is a fully local, manufacturable, and evolvable personal AI assistant platform. It unifies long-running conversations, cross-session memory, local knowledge bases, document workflows, web search, scheduling, email, image generation, and multi-agent collaboration in an auditable AgentPackage runtime. Users can manufacture, validate, publish, run, and evolve specialized agents from natural-language requirements.

The platform supports both local and split-host deployment. On a Linux workstation with an AMD Radeon GPU, the Web application and ROCm inference node can run on the same host. When the GPU is remote, the control host connects to loopback-only inference services through SSH tunnels. Chat inference uses GGUF models with llama.cpp on ROCm, embeddings use SentenceTransformers with PyTorch HIP, and AgentPackage, MCP, and sub-agent workloads run in isolated Docker environments.

![FastAgentFactory project poster](supplementary-materials/poster/fastagentfactory-project-poster.png)

## Submission Documents

- [Project specification](project-documentation/ProjectOverview.md)
- [Application scenarios](project-documentation/ApplicationScenarios.md)
- [Agent architecture](project-documentation/AgentArchitecture.md)
- [Core capabilities](project-documentation/CoreCapabilities.md)
- [Deployment and acceptance guide](project-documentation/Deployment.md)
- [AMD Radeon GPU inference optimizations](project-documentation/performance/ROCmOptimizations.md)
- [Supplementary materials and poster](SUPPLEMENTARY_MATERIALS.md)

## Application: A Private Personal AI Assistant

FastAgentFactory treats a personal assistant as a long-running local system that understands user preferences, invokes real tools, and produces verifiable deliverables—not as a chat interface that only generates text.

- **Personal knowledge and task assistant:** searches local material, processes attachments, preserves reports and images, and carries relevant preferences across sessions.
- **Office automation assistant:** combines web search, files, schedules, email, and approval-aware tools to deliver reports and recurring briefs.
- **Multi-agent research assistant:** decomposes a goal, delegates evidence collection to specialized agents, semantically reviews their deliverables, and produces a unified result.
- **Manufacturable specialist assistant:** lets users create and evolve AgentPackages with dedicated models, tools, skills, knowledge, resources, and runtime patterns.

### Built-in A-share Research Example

| Agent | Responsibility | Typical deliverable |
| --- | --- | --- |
| A-share Market Radar | Market breadth, turnover, sectors, and leading stocks | Market brief, anomaly notes, Markdown report, authorized email |
| A-share Listed-company Researcher | Price history, financials, trend, and user-provided evidence | Time-stamped company research report with sources |
| A-share Portfolio Risk Guard | Concentration, volatility, drawdown, correlation, and stress scenarios | Portfolio risk report and scenario analysis |

The main assistant can coordinate all three agents—for example, research the overall market, Kweichow Moutai, CATL, and Ping An, then evaluate a simulated portfolio under 5% and 10% market drawdowns. Financial output is for research and system demonstration only and is not investment advice.

## Architecture

```text
Control host
┌────────────────────────────────────────────────────────────┐
│ Browser :3000                                              │
│   │ HTTP + SSE                                             │
│ FastAgentFactory Backend :8000                             │
│   ├─ AgentPackage / RuntimeKernel / RAG / Memory / Tools    │
│   ├─ Model Pool / Benchmark / Trace / Workspace            │
│   └─ Docker Agent Runtime                                  │
│                                                            │
│ Direct loopback or SSH tunnels                             │
│   18003 -> inference :8003  Chat API                       │
│   18002 -> inference :8002  Embedding API                  │
│   18004 -> inference :8004  Control + ROCm telemetry       │
└──────────────────────────────┬─────────────────────────────┘
                               │
AMD ROCm inference host        ▼
┌────────────────────────────────────────────────────────────┐
│ Inference control node :8004                               │
│   ├─ llama-server ROCm :8003                               │
│   ├─ SentenceTransformers + PyTorch HIP :8002              │
│   └─ ROCm telemetry, model lifecycle, and benchmarks       │
│                                                            │
│ official + AMD llama.cpp builds / models / runtime state   │
└────────────────────────────────────────────────────────────┘
```

The detailed component model and isolation boundaries are documented in [Agent Architecture](project-documentation/AgentArchitecture.md).

## Default Model Stack

| Role | Default model | Runtime |
| --- | --- | --- |
| Chat | Qwen3.6-35B-A3B APEX GGUF | llama.cpp + ROCm/HIP |
| Vision projector | Matching APEX F16 mmproj | llama.cpp multimodal path |
| Embedding | BAAI/bge-m3 | SentenceTransformers + PyTorch HIP |
| Image generation | FLUX.1-dev Q4_0 | stable-diffusion.cpp + HIPBLAS |

Model profiles describe context size, YaRN capability, output limit, slot concurrency, KV cache types, Flash Attention, MTP, GPU layers, and VRAM estimates. Model files are downloaded at deployment time and are not stored in this repository.

The default deployment activates FLUX together with Chat and Embedding, waits for all enabled runtimes to become ready, and configures image generation at 1024×1024 with eager loading enabled.

## Requirements

### Control Host

- macOS or Linux
- Git and OpenSSH
- `rsync`
- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- Node.js 18+ and npm
- Docker Engine or Docker Desktop

### AMD ROCm Inference Host

- Linux with an AMD Radeon GPU
- A working ROCm user-space runtime and access to `/dev/kfd`
- PyTorch HIP compatible with the installed ROCm version
- Sufficient storage for model files and two llama.cpp builds
- SSH key access when using split-host deployment

The deployment scripts may install missing user-space build tools. They do not replace the host GPU driver.

## Quick Start

### 1. Clone and configure

```bash
git clone https://github.com/LiuYan-89937/FastAgentFactory.git
cd FastAgentFactory
cp .env.example .env
```

For a remote GPU host:

```dotenv
DEPLOY_TARGET=ssh
SSH_HOST=<AMD-Inference-Host>
SSH_PORT=<SSH-Port>
SSH_USER=root
SSH_KEY=
```

For a local AMD GPU host:

```dotenv
DEPLOY_TARGET=local
SSH_HOST=
SSH_PORT=22
SSH_USER=
SSH_KEY=
```

Override runtime or model directories in `.env` only when the defaults in `deploy/defaults.env` do not fit the target host. Existing `REMOTE_*` names mean “inference-node path” in both modes.

### 2. Deploy and start

```bash
./deploy.sh up
```

The command validates the target, prepares the ROCm build environment, synchronizes the bundled native inference sources, builds Official and AMD llama.cpp implementations, downloads and validates configured models, creates model profiles, starts the inference services, prepares local Python/frontend/Docker dependencies, and launches the Web application.

Open:

```text
http://localhost:3000
```

### 3. Initialize Agents before first use

After the first deployment, open **Published Agents** and initialize the built-in Agent packages you plan to use. Initialize **Factory Chat** before starting a regular chat; initialize the three built-in A-share research Agents before running the corresponding multi-agent example. Initialization prepares the package runtime, tools, and dependencies, so the first startup may take longer than later messages.

If the first chat message is sent before Factory Chat is ready, the application starts initialization automatically and displays **Initializing runtime…**. Wait until it changes to the normal Assistant reasoning state before expecting streamed output.

After a successful bootstrap, the regular local startup path is:

```bash
./start.sh
```

`start.sh` reconnects the configured endpoints, validates dependencies, checks the Docker runtime, and starts the frontend and backend. It does not rebuild llama.cpp or redownload models.

## Deployment Commands

| Command | Purpose |
| --- | --- |
| `./deploy.sh up` | Idempotently deploy the inference node and start the Web stack |
| `./deploy.sh up --no-web` | Deploy inference without starting the frontend/backend |
| `./deploy.sh bootstrap` | Prepare models and inference services only |
| `./deploy.sh doctor` | Inspect GPU, ROCm, PyTorch HIP, disk, and llama.cpp |
| `./deploy.sh status` | Show inference service and model status |
| `./deploy.sh logs` | Show recent inference-node logs |
| `./deploy.sh restart` | Restart the inference node and wait for readiness |
| `./deploy.sh down` | Stop inference and unload models |
| `./deploy.sh models` | Resume/validate model downloads and refresh profiles |
| `./deploy.sh sync` | Synchronize the minimal runtime bundle and native sources |
| `./deploy.sh build-llama [official\|amd\|all]` | Incrementally build one or both llama.cpp implementations |
| `./deploy.sh switch-llama <official\|amd>` | Switch implementation and reload the same profile |

See [Deployment and Acceptance](project-documentation/Deployment.md) for complete configuration, lifecycle, validation, and troubleshooting instructions.

## Major Capabilities

- Natural-language AgentPackage manufacturing, validation, publication, and evolution
- `react_agent` and `plan_and_execute` runtime patterns
- Unified tool gateway for built-in tools, MCP, skills, package tools, and model tools
- Local knowledge ingestion, retrieval, opening, and citation
- Cross-session memory with package-level write interval configuration
- Encrypted per-package resources and explicit approval policies
- Multi-agent task decomposition, isolated workspaces, semantic acceptance, and active completion notifications
- Scheduled tasks, file artifacts, email delivery, and image generation
- Runtime traces, model usage, token accounting, KV-prefix reuse, GPU telemetry, QPS, and operator analysis

## Web Search MCP

The built-in Web Search MCP supports Tavily, SearXNG, and DuckDuckGo. Tavily is recommended:

```dotenv
TAVILY_API_KEY=<your-tavily-api-key>
```

The key is inherited only by the local MCP process and is not written into an AgentPackage. When Tavily is not configured, startup selects an available managed SearXNG or DuckDuckGo provider.

## AMD Radeon GPU Optimization

The repository carries two llama.cpp implementations built from the same baseline revision:

- `vendor/llama.cpp-official`: immutable comparison baseline
- `vendor/llama.cpp-amd`: AMD-oriented HIP kernel implementation
- `vendor/llama.cpp-common`: shared host dispatch tracing

The optimization work includes activation quantization reuse, fused Residual Add + RMSNorm + scale, native RDNA3 Q6_K × Q8_1 MatVec, dynamic Wave32/Wave64 dispatch experiments, and MTP speculative decoding. Official/AMD experiments use the same model, prompt, profile, cache policy, and sampling settings. Operator profiling is separated from normal service performance so profiler overhead is never reported as user-facing throughput.

Full design details and measured boundaries are in [AMD Radeon GPU Inference Optimizations](project-documentation/performance/ROCmOptimizations.md).

## Demo Video Scope

The 3–5 minute demonstration intentionally avoids rerunning the full ten-round profiling suite:

1. Show a few short personal-assistant conversations, including one `react_agent` tool loop and one `plan_and_execute` task with its visible plan and final deliverable.
2. Show the AMD Radeon inference node and model runtime as ready from the command line or GUI.
3. Run one short paired Official/AMD performance experiment with identical parameters.
4. Open the result view and show Decode/Prompt throughput, two-client QPS, and the custom-kernel hit table.

The pre-recorded ten-round paired results remain in the optimization document; the video run demonstrates the end-to-end workflow and responsiveness rather than replacing repeated measurement.

## Configuration and Runtime Data

`.env` is the only user-edited configuration file and is excluded from Git. `deploy/defaults.env` is a committed internal defaults table, not a second configuration file. Model weights, `.agentfactory/`, and local virtual environments are also excluded.

Important runtime boundaries:

- Model services bind to loopback addresses.
- Resource secrets are encrypted using `AGENTFACTORY_RESOURCE_MASTER_KEY`.
- Docker isolates AgentPackage, MCP, and sub-agent execution from the host.
- Model files and benchmark runtime data remain outside the source tree.
- Never commit SSH keys, email authorization codes, API keys, or decrypted resources.

## Static Validation

```bash
python3 -m compileall agent_factory web_frontend/backend deploy
bash -n start.sh deploy.sh deploy/remote_runtime.sh web_frontend/lib/runtime_env.sh
cd web_frontend/frontend && npm run type-check
```

## Third-party Components and Licenses

This section distinguishes project-owned source, vendored native source, runtime-downloaded model weights, and external data services. Each third-party component remains governed by its own license and terms. This inventory does not replace the complete upstream license text or constitute legal advice.

### Vendored native source

| Component | Upstream | Pinned revision | License | License location |
| --- | --- | --- | --- | --- |
| llama.cpp Official | [ggml-org/llama.cpp](https://github.com/ggml-org/llama.cpp) | `f955e394bf94e01e5e36186d13c985727e5ef5b5` | MIT | `vendor/llama.cpp-official/LICENSE` |
| llama.cpp AMD derivative | Based on the same llama.cpp revision | Same as Official | MIT; project modifications do not change the upstream notice | `vendor/llama.cpp-amd/LICENSE` |
| stable-diffusion.cpp | [leejet/stable-diffusion.cpp](https://github.com/leejet/stable-diffusion.cpp) | `833369da848e8e2f960fe1896a825e3a08ef9733` | MIT | `vendor/stable-diffusion.cpp/LICENSE` |
| libwebm | stable-diffusion.cpp submodule | Included in the pinned source tree | BSD 3-Clause | `vendor/stable-diffusion.cpp/thirdparty/libwebm/LICENSE.TXT` |
| libwebp | stable-diffusion.cpp submodule | Included in the pinned source tree | BSD 3-Clause | `vendor/stable-diffusion.cpp/thirdparty/libwebp/COPYING` |

Source or binary redistribution must preserve the applicable copyright, license, patent, and notice files. The AMD derivative retains upstream attribution; its modifications do not relicense upstream code.

### Runtime-downloaded models

| Purpose | Model | License status and boundary |
| --- | --- | --- |
| Chat | [SC117/Qwen3.6-35B-A3B APEX GGUF](https://huggingface.co/SC117/Qwen3.6-35B-A3B-uncensored-heretic-Native-MTP-Preserved-APEX-GGUF) | The current model card declares Apache-2.0. It is a third-party derivative and quantization; verify its base-model lineage and current card before redistribution. |
| Embedding | [BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3) | MIT; retain model provenance and citation information. |
| Image generation | [black-forest-labs/FLUX.1-dev](https://huggingface.co/black-forest-labs/FLUX.1-dev) | FLUX.1-dev Non-Commercial License. It is not an unrestricted OSI-approved commercial-use license. |
| FLUX GGUF | [city96/FLUX.1-dev-gguf](https://modelscope.cn/models/city96/FLUX.1-dev-gguf) | Quantization and the download mirror do not replace or broaden the upstream FLUX license. |

Model weights are downloaded during deployment and are not distributed as repository source. Mirrors and packaging repositories are not independent grants of rights.

### Language, web, data, and service dependencies

Python direct dependencies are declared in `pyproject.toml` and resolved in `uv.lock`; Web dependencies are declared in `web_frontend/frontend/package.json` and locked in `package-lock.json`. A binary, container, or offline bundle should ship a generated Software Bill of Materials and the corresponding third-party license archive rather than relying only on this summary.

The repository does not distribute a model-training dataset. Market data, web-search results, uploaded knowledge, email content, and other external material remain subject to their providers' and owners' terms. Public accessibility does not itself grant redistribution rights.

### Project-owned source

The repository root does not currently declare a single project-wide source-code license. Until the owner adds a root `LICENSE`, do not infer MIT, Apache-2.0, or another license for project-owned code from licenses present in third-party directories.
