[简体中文](README.md) | [English](README.en.md)

# FastAgentFactory

FastAgentFactory is a fully local, manufacturable, and evolvable personal AI assistant platform. It unifies long-running conversations, cross-session memory, local knowledge bases, document workflows, web search, scheduling, email, image generation, and multi-agent collaboration in an auditable AgentPackage runtime. Users can manufacture, validate, publish, run, and evolve specialized agents from natural-language requirements.

The platform supports both local and split-host deployment. On a Linux workstation with an AMD Radeon GPU, the Web application and ROCm inference node can run on the same host. When the GPU is remote, the control host connects to loopback-only inference services through SSH tunnels. Chat inference uses GGUF models with llama.cpp on ROCm, embeddings use SentenceTransformers with PyTorch HIP, and AgentPackage sessions run as supervised native subprocesses with isolated workspaces and shared immutable dependency pools.

![FastAgentFactory project poster](supplementary-materials/poster/fastagentfactory-project-poster.png)

## Submission Documents

- [Project specification](project-documentation/ProjectOverview.md)
- [Application scenarios](project-documentation/ApplicationScenarios.md)
- [Agent architecture](project-documentation/AgentArchitecture.md)
- [Core capabilities](project-documentation/CoreCapabilities.md)
- [Deployment and acceptance guide](project-documentation/Deployment.md)
- [AMD Radeon GPU inference optimizations](project-documentation/performance/ROCmOptimizations.md)
- [Demo video](FastAgentFactory-Demo.mp4)
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
│   └─ Native Agent Runtime / isolated session workspaces    │
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

- macOS, Linux, or Windows 10/11
- Git and OpenSSH
- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- Node.js 18+ and npm

Remote SSH deployment prefers `rsync` on macOS/Linux. Windows does not require
`rsync`; the shared deployment core uses OpenSSH, SCP, and compressed archives
for the same synchronization boundary. Only local Linux ROCm deployment
requires `rsync`.

### AMD ROCm Inference Host

- Linux with an AMD Radeon GPU
- A working ROCm user-space runtime and access to `/dev/kfd`
- PyTorch HIP compatible with the installed ROCm version
- Sufficient storage for model files and two llama.cpp builds
- SSH key access when using split-host deployment

The deployment scripts may install missing user-space build tools. They do not replace the host GPU driver.

> **Server image tip:** When creating a RadeonCloud/AMD cloud inference server, select `ROCm vLLM-dev (Navi) (vllm-dev:rocm7.2.1_navi_ubuntu22.04_py3.10_pytorch_2.9_vllm_0.16.0)`. This image is the baseline for the project's remote ROCm inference node. If you choose another image, first verify ROCm, PyTorch HIP, `/dev/kfd`, and Python ABI compatibility.

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

For key generation, sshd validation, `authorized_keys`, ssh-agent, and
connection verification, see
[Configure SSH Key Authentication from Scratch](project-documentation/Deployment.md#41-configure-ssh-key-authentication-from-scratch).

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

On Windows PowerShell:

```powershell
Copy-Item .env.example .env
Set-ExecutionPolicy -Scope Process Bypass
.\deploy.ps1 up
```

The PowerShell entrypoint runs the same cross-platform Python deployment core
directly on Windows; WSL, Git Bash, and Docker are not required. The Web stack,
Agent runtime, and SSH tunnel remain on the Windows machine, while only
inference runs remotely. Linked workspaces use native paths such as
`C:\Users\<username>\Documents`.

The command validates the target, prepares the ROCm build environment, synchronizes the bundled native inference sources, builds Official and AMD llama.cpp implementations, downloads and validates configured models, creates model profiles, starts the inference services, prepares local Python/frontend/native runtime dependencies, and launches the Web application.

Open:

```text
http://localhost:3000
```

### 3. Initialize Agents before first use

After the first deployment, open **Published Agents** and initialize the built-in Agent packages you plan to use. Initialize **Factory Chat** before starting a regular chat; initialize the three built-in A-share research Agents before running the corresponding multi-agent example. Initialization prepares the package runtime, tools, and dependencies, so the first startup may take longer than later messages.

If the first chat message is sent before Factory Chat is ready, the application starts initialization automatically and displays **Initializing runtime…**. Wait until it changes to the normal Assistant reasoning state before expecting streamed output.

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
- Managed per-session workspaces and linked local folders shared by multiple sessions without copying source files
- Scheduled tasks, file artifacts, email delivery, and image generation
- Runtime traces, model usage, token accounting, KV-prefix reuse, GPU telemetry, QPS, and operator analysis

## Web Search MCP

The Hackson test deployment includes a Tavily Web Search MCP. `deploy.sh up`
installs it under `.agentfactory/mcp/web_search`, builds it, and registers it
with Tavily selected by default. No search configuration is required in `.env`.

The bundled shared key is intended only for competition demonstrations and
functional testing, and may be subject to shared quota limits. AgentPackage
artifacts retain only their MCP binding and do not embed this test MCP.

## AMD Radeon GPU Optimization

The repository carries two llama.cpp implementations built from the same baseline revision:

- `vendor/llama.cpp-official`: immutable comparison baseline
- `vendor/llama.cpp-amd`: AMD-oriented HIP kernel implementation
- `vendor/llama.cpp-common`: shared host dispatch tracing

The optimization work includes activation quantization reuse, fused Residual Add + RMSNorm + scale, native RDNA3 Q6_K × Q8_1 MatVec, dynamic Wave32/Wave64 dispatch experiments, and MTP speculative decoding. Official/AMD experiments use the same model, prompt, profile, cache policy, and sampling settings. Operator profiling is separated from normal service performance so profiler overhead is never reported as user-facing throughput.

Measured results are reported in two separate scopes:

- **Non-MTP single-token Decode:** the AMD implementation improved Decode throughput by `5.64%` over Official.
- **MTP enabled for both implementations:** Decode was effectively tied, while AMD improved Prompt throughput by `16.70%`, reduced model-compute TTFT by `14.31%`, and improved two-client QPS by `5.09%`.

The MTP scheduling gain is not attributed to AMD kernels. In the same MTP-enabled paired run, AMD also reduced mean request latency by `4.89%`.

Full design details and measured boundaries are in [AMD Radeon GPU Inference Optimizations](project-documentation/performance/ROCmOptimizations.md).

## Demo Video

<video
  controls
  preload="metadata"
  poster="supplementary-materials/poster/fastagentfactory-project-poster.png"
  width="100%"
>
  <source src="FastAgentFactory-Demo.mp4" type="video/mp4">
  This Markdown viewer does not support embedded video.
</video>

If the embedded player is unavailable, [open or download the MP4 demo directly](FastAgentFactory-Demo.mp4) (approximately 34 MB).

The demonstration intentionally avoids rerunning the full ten-round profiling suite and includes:

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
- AgentPackage sessions use supervised native subprocesses, per-session workspaces, and content-addressed dependency pools. This is logical runtime isolation, not a kernel security sandbox.
- Model files and benchmark runtime data remain outside the source tree.
- Never commit SSH keys, email authorization codes, API keys, or decrypted resources.

## Static Validation

```bash
python3 -m compileall agent_factory web_frontend/backend deploy
python3 -m compileall -q deploy
bash -n deploy.sh deploy/start_web.sh deploy/remote_runtime.sh
cd web_frontend/frontend && npm run type-check
```

## Third-party Components and Licenses

This section records the provenance and known license boundaries of project-owned source, vendored native source, runtime-downloaded model weights, and external data services as of the documentation date. Each third-party component remains governed by its own upstream license and terms. This inventory is not a license grant, a compliance warranty, or legal advice; the applicable upstream license, model card, and service terms take precedence.

### Vendored native source

| Component | Upstream | Pinned revision | License | License location |
| --- | --- | --- | --- | --- |
| llama.cpp Official | [ggml-org/llama.cpp](https://github.com/ggml-org/llama.cpp) | `f955e394bf94e01e5e36186d13c985727e5ef5b5` | MIT | `vendor/llama.cpp-official/LICENSE` |
| llama.cpp AMD implementation | Project-modified derivative of the pinned llama.cpp revision | Same as Official | Upstream MIT terms and notices remain applicable; project modifications do not relicense the upstream code | `vendor/llama.cpp-amd/LICENSE` |
| stable-diffusion.cpp | [leejet/stable-diffusion.cpp](https://github.com/leejet/stable-diffusion.cpp) | `833369da848e8e2f960fe1896a825e3a08ef9733` | MIT | `vendor/stable-diffusion.cpp/LICENSE` |
| libwebm | stable-diffusion.cpp submodule | Included in the pinned source tree | BSD 3-Clause | `vendor/stable-diffusion.cpp/thirdparty/libwebm/LICENSE.TXT` |
| libwebp | stable-diffusion.cpp submodule | Included in the pinned source tree | BSD 3-Clause | `vendor/stable-diffusion.cpp/thirdparty/libwebp/COPYING` |

Source or binary redistribution must preserve all applicable copyright, license, patent, and notice files. The AMD implementation is a project-modified derivative and retains the upstream attribution and license boundary; its modifications do not relicense or expand the rights in upstream code.

### Runtime-downloaded models

| Purpose | Model | License status and boundary |
| --- | --- | --- |
| Chat | [SC117/Qwen3.6-35B-A3B APEX GGUF](https://huggingface.co/SC117/Qwen3.6-35B-A3B-uncensored-heretic-Native-MTP-Preserved-APEX-GGUF) | The current model card states Apache-2.0. This is a third-party derived and quantized distribution; before redistribution, independently verify the base-model lineage, derivative permissions, model-card revision, and applicable notices. |
| Embedding | [BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3) | MIT; retain model provenance and citation information. |
| Image generation | [black-forest-labs/FLUX.1-dev](https://huggingface.co/black-forest-labs/FLUX.1-dev) | Subject to the FLUX.1-dev Non-Commercial License; this is not an unrestricted commercial-use or OSI-approved open-source license. |
| FLUX GGUF | [city96/FLUX.1-dev-gguf](https://modelscope.cn/models/city96/FLUX.1-dev-gguf) | The quantized distribution and download mirror do not replace, narrow, or broaden the upstream FLUX.1-dev license. |

Model weights are downloaded during deployment and are not distributed as repository source. A quantized or otherwise derived artifact, a hosting page, and a download mirror are provenance references rather than independent grants of rights; redistribution requires review of the applicable upstream and derivative terms.

### Language, web, data, and service dependencies

Python direct dependencies are declared in `pyproject.toml` and resolved in `uv.lock`; Web dependencies are declared in `web_frontend/frontend/package.json` and locked in `package-lock.json`. A binary, container, or offline bundle should ship a generated Software Bill of Materials and the corresponding third-party license archive rather than relying only on this summary.

The repository does not distribute a model-training dataset. Market data, web-search results, uploaded knowledge, email content, and other external material remain subject to their providers' and owners' terms. Public accessibility does not itself grant redistribution rights.

### Project-owned source

Project-owned source in this repository is licensed under the Apache License, Version 2.0, in the root [`LICENSE`](LICENSE). That license applies only to project-owned source and does not relicense vendored third-party source, model weights, external data, or online services; those materials remain subject to their own terms.
