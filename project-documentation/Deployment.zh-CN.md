[English](Deployment.md) | [简体中文](Deployment.zh-CN.md)

# FastAgentFactory 部署与验收指南

本文档说明 FastAgentFactory 的完整部署、复现和运行验收流程。系统支持两种推理节点拓扑：

- `DEPLOY_TARGET=local`：FastAgentFactory Web、Agent Runtime 与 AMD ROCm 推理节点位于同一台 Linux 主机。
- `DEPLOY_TARGET=ssh`：Web 与 Agent Runtime 位于控制端，AMD ROCm 推理节点位于独立主机，通过 SSH 隧道访问远端回环端口。

两种拓扑复用同一套模型 Profile、推理控制、Benchmark 和部署脚本。

项目入口和功能说明见 [中文 README](../README.zh-CN.md)。

## 1. 部署结果

完成本文档后应得到以下运行状态：

| 位置 | 服务或资源 | 默认地址或目录 |
| --- | --- | --- |
| 本机 | Web 前端 | `http://127.0.0.1:3000` |
| 本机 | Web 后端 | `http://127.0.0.1:8000` |
| 本机 | Chat SSH 转发 | `127.0.0.1:18003 -> remote:8003` |
| 本机 | Embedding SSH 转发 | `127.0.0.1:18002 -> remote:8002` |
| 本机 | Telemetry SSH 转发 | `127.0.0.1:18004 -> remote:8004` |
| 本机 | 官方 llama.cpp 源码 | `vendor/llama.cpp-official` |
| 本机 | AMD llama.cpp 源码 | `vendor/llama.cpp-amd` |
| 本机 | 共享算子追踪源码 | `vendor/llama.cpp-common` |
| 本机 | stable-diffusion.cpp 完整源码与递归子模块 | `vendor/stable-diffusion.cpp` |
| 远端 | llama-server ROCm | `127.0.0.1:8003` |
| 远端 | Embedding 服务 | `127.0.0.1:8002` |
| 远端 | 推理控制与遥测 | `127.0.0.1:8004` |
| 远端 | 最小推理 bundle | `/root/FastAgentFactory` |
| 远端 | 两套 llama.cpp 源码 | `/root/fastagentfactory-llama-sources` |
| 远端 | 两套构建与活动入口 | `/root/.fastagentfactory/llama` |
| 远端 | stable-diffusion.cpp 同步源码与构建产物 | `/root/stable-diffusion.cpp` |
| 远端 | 模型文件 | `/root/models` |
| 远端 | 推理状态与日志 | `/root/.fastagentfactory` |

推理节点路径均可在根目录 `.env` 覆盖。若运行环境提供持久卷，应优先改到持久卷挂载点。

## 2. 部署前检查

### 2.1 本机要求

确认以下命令可用：

```bash
git --version
ssh -V
rsync --version
python3 --version
uv --version
node --version
npm --version
docker info
```

最低要求：

- Python 3.11+
- Node.js 18+
- Docker Engine 或 Docker Desktop 已启动
- SSH 模式下，私钥或 ssh-agent 可以登录 AMD 推理主机
- 本机端口 `3000`、`8000`、`18002`、`18003`、`18004` 未被占用

Docker 仅用于本机 AgentPackage、MCP 和子 Agent 隔离，不承载远端模型推理。

### 2.2 AMD ROCm 推理节点要求

推理节点必须提供 Linux、AMD GPU、可用的 ROCm 驱动与用户态组件、`/dev/kfd` 访问权限，以及与 ROCm 版本兼容的 PyTorch HIP。SSH 模式还需要 sshd 和 Public Key 登录；主机或端口变化后，需要同步修改控制端部署配置。

在本机先验证：

```bash
ssh <SSH_USER>@<SSH_HOST> -p <SSH_PORT>
```

如果 SSH 本身无法登录，不要执行部署脚本。

### 2.3 容量要求

默认 Chat GGUF 约 23.5 GB，mmproj 约 0.9 GB，此外还需要：

- `BAAI/bge-m3` 模型与 ModelScope 缓存；
- llama.cpp Git 工作树和 ROCm 构建产物；
- Python 环境、日志、模型池与 Benchmark 数据。

部署前应通过主机管理界面或 `df -h` 确认模型目录所在文件系统空间充足。

## 3. 获取代码

在本机执行：

```bash
git clone https://github.com/LiuYan-89937/FastAgentFactory.git
cd FastAgentFactory
git status
git log -1 --oneline
```

已有工作树执行：

```bash
git pull --ff-only
```

部署脚本会从控制端同步当前工作树到推理节点，不需要在推理主机上手动 Clone 项目。

## 4. 选择推理节点并配置部署参数

创建私有配置：

```bash
cp .env.example .env
```

GPU 位于另一台机器时使用默认 SSH 目标：

```dotenv
DEPLOY_TARGET=ssh
SSH_HOST=<AMD-Inference-Host>
SSH_PORT=<SSH-Port>
SSH_USER=root
SSH_KEY=
```

`SSH_KEY` 的行为：

- 留空：由 ssh-agent 或 OpenSSH 自动选择私钥；
- 填写：使用绝对路径或 `~/.ssh/...` 指定私钥；
- 不允许填写密码，脚本只支持 Key 登录。

GPU 位于当前 Linux 主机时使用本机目标：

```dotenv
DEPLOY_TARGET=local
SSH_HOST=
SSH_USER=
SSH_KEY=
```

本机模式不建立 SSH 隧道。推理控制节点、Chat、Embedding 和 Image 服务仍使用与
SSH 模式完全相同的进程与接口，Web 端通过回环端口直接访问，因此 Official/AMD
切换、MTP、容量估算、QPS 与算子分析不分叉。请将所有 `REMOTE_*_ROOT`/`DIR`
配置为当前用户可写的本机绝对路径；这些字段名为兼容既有配置保留，实际表示推理节点路径。
本机必须是具有 `/dev/kfd` 和 AMD ROCm 驱动的 Linux 主机。

### 4.1 主要配置字段

| 字段 | 含义 | 默认策略 |
| --- | --- | --- |
| `DEPLOY_TARGET` | 推理节点执行位置 | `ssh`；同机 AMD GPU 使用 `local` |
| `REMOTE_PROJECT_ROOT` | 远端最小推理 bundle 目录 | `/root/FastAgentFactory` |
| `REMOTE_STATE_ROOT` | venv、模型池、PID、日志 | `/root/.fastagentfactory` |
| `REMOTE_MODEL_ROOT` | 模型根目录 | `/root/models` |
| `REMOTE_LLAMA_SOURCE_ROOT` | 远端两套 llama.cpp 源码根目录 | `/root/fastagentfactory-llama-sources` |
| `REMOTE_LLAMA_RUNTIME_ROOT` | 两套构建、清单和活动软链接 | `/root/.fastagentfactory/llama` |
| `LOCAL_LLAMA_OFFICIAL_DIR` | 仓库内官方 Baseline 源码 | `vendor/llama.cpp-official` |
| `LOCAL_LLAMA_AMD_DIR` | 仓库内 AMD 优化源码 | `vendor/llama.cpp-amd` |
| `LOCAL_STABLE_DIFFUSION_CPP_DIR` | 仓库内完整图片推理源码 | `vendor/stable-diffusion.cpp` |
| `REMOTE_STABLE_DIFFUSION_CPP_DIR` | 远端 stable-diffusion.cpp 源码与构建 | `/root/stable-diffusion.cpp` |
| `STABLE_DIFFUSION_CPP_REVISION` | 本机 vendor 图片推理源码 revision | 固定 Commit SHA |
| `LLAMA_OFFICIAL_REVISION` | 官方 Baseline 来源 revision | 固定 Commit SHA |
| `LLAMA_OFFICIAL_BUILD_NUMBER` | 官方 Baseline 的上游构建序号 | 与固定 revision 对应的提交计数 |
| `LLAMA_AMD_BASE_REVISION` | AMD 版本基于的官方 revision | 与 Baseline 对齐 |
| `LLAMA_AMD_BASE_BUILD_NUMBER` | AMD 版本基线的上游构建序号 | 与 Baseline 对齐 |
| `LLAMA_DEFAULT_IMPLEMENTATION` | 一键部署后激活的实现 | `amd` |
| `PYPI_INDEX_URL` | 远端 Python 依赖源 | 清华 PyPI |
| `HF_ENDPOINT` | GGUF 下载源 | Hugging Face 国内镜像 |
| `CHAT_MODEL_*` | Chat GGUF 版本、文件、大小和 SHA256 | 固定并校验 |
| `CHAT_MMPROJ_*` | 视觉投影器版本、大小和 SHA256 | 固定并校验 |
| `CHAT_NATIVE_CONTEXT_TOKENS` | Chat 模型原生上下文 | `262144` |
| `CHAT_YARN_MAX_CONTEXT_TOKENS` | 模型声明支持的 YaRN 最大扩展上下文 | `1010000` |
| `EMBEDDING_MODEL_ID` | Embedding 模型 | `BAAI/bge-m3` |
| `IMAGE_*_URL/SHA256/SIZE_BYTES` | FLUX 四件套 ModelScope 国内直链与完整性信息 | 固定并校验 |
| `IMAGE_RESIDENCY_POLICY` | Chat 与 Image 显存共存策略 | `coexist_if_fit` |
| `IMAGE_EAGER_LOAD` | sd-server 启动时立即把图片模型参数加载到配置的计算后端 | `1` |
| `IMAGE_ENABLED` | 部署后启用并自动加载 FLUX 图片运行时 | `1` |
| `IMAGE_DEFAULT_WIDTH/HEIGHT` | 默认图片生成尺寸 | `1024 × 1024` |
| `CHAT_CONTEXT_SIZE` | 每并发槽位的目标上下文；超过原生值时自动计算 YaRN 因子 | `256000` |
| `CHAT_CACHE_TYPE_K/V` | KV Cache 类型 | `q8_0` |
| `CHAT_PARALLEL_SLOTS` | Chat 并发槽位 | `1` |
| `CHAT_FLASH_ATTENTION` | Flash Attention | `1`，开启 |
| `AGENTFACTORY_COLLABORATION_EVENT_COALESCE_WINDOW_SECONDS` | 子 Agent 事件触发主 Agent 恢复前的短聚合窗口 | `0.75` 秒 |
| `AGENTFACTORY_COLLABORATION_EVENT_BATCH_LIMIT` | 单次主 Agent 恢复最多合并的原始事件数 | `64` |
| `TAVILY_API_KEY` | 内置 `web_search` 的 Tavily Provider 密钥；只配置在本机 `.env`，由 MCP 子进程继承 | 留空时回退到 SearXNG/DuckDuckGo |
| `REMOTE_INSTALL_BUILD_TOOLS` | 缺少普通工具时允许 apt 安装 | `1` |
| `REMOTE_CA_BUNDLE` | curl、pip、Requests 和 ModelScope 共用的远端 CA bundle | `/etc/ssl/certs/ca-certificates.crt` |
| `REMOTE_REPAIR_CA_TRUST` | 证书链缺失或损坏时允许重建并按需重装 `ca-certificates` | `1` |
| `REMOTE_CA_PROBE_URL` | CA 探针使用的国内 HTTPS 地址 | 清华 PyPI |
| `REMOTE_INSTALL_ROCM_USERSPACE` | 缺失时安装 ROCm 用户态探查与 HIP 构建组件 | `1` |
| `ROCM_USERSPACE_PACKAGES` | 镜像对应的 ROCm 用户态、HIP 构建与分析工具 | `rocminfo rocm-hip-sdk rocprofiler-sdk` |
| `REMOTE_INSTALL_PYTORCH` | 缺失时允许安装配置指定的 PyTorch HIP | `1` |
| `PYTORCH_RUNTIME_PYTHON` | 镜像预装 HIP PyTorch 的 Python；以 `.pth` 接入项目 venv | `/opt/venv/bin/python` |
| `REMOTE_INFERENCE_PYTHON_PACKAGES` | 远端推理节点最小依赖，不安装主项目 | FastAPI、HTTP、模型加载和 GGUF 解析依赖 |
| `PYTORCH_INDEX_URL` | 预装运行时不可用时的 PyTorch HIP wheel 后备源 | 官方 ROCm 7.2 wheel 源 |
| `PYTORCH_PACKAGES` | 相互匹配的 Torch、TorchVision 与 TorchAudio 发布组 | ROCm 7.2 的 2.11/0.26/2.11 |

协作调度器会读取 llama-server 的 `/slots` 与 `/metrics`，按实际空闲槽位、排队请求以及所有协作会话中正在运行的 worker 统一背压。遥测暂时不可用时，调度器使用当前已启用推理 Profile 的 `parallel_slots` 作为容量依据，不会回退到固定并发数。若需要主动限制协作 worker 数量，可在本机 `.env` 设置 `AGENTFACTORY_COLLABORATION_MAX_PARALLEL_WORKERS`；留空时自动跟随推理服务槽位。

Worker 租约以协作任务为唯一边界。同一个 AgentPackage 可以在不同协作任务、不同会话和各自独立工作区中并行运行；同一任务仍只能被一个 worker 领取。实际并发上限仍由上述推理容量背压统一控制，而不是由 Package ID 互斥。

多个 worker 几乎同时提交、阻塞、失败或取消时，每条协作事件仍会独立写入审计表；服务在 `AGENTFACTORY_COLLABORATION_EVENT_COALESCE_WINDOW_SECONDS` 指定的短窗口后，将当时待处理的事件批量领取并只恢复一次主 Agent。批次中的每条事件独立累计 attempts，并在同一事务中统一完成或失败。`AGENTFACTORY_COLLABORATION_EVENT_BATCH_LIMIT` 用于限制一次恢复输入的事件数量，超过限制的事件会进入后续批次。

部署脚本先探查并复用现有 ROCm 与 PyTorch HIP。若推理主机在 `/opt/venv` 提供预装 PyTorch，脚本会校验 Python ABI、HIP 和 GPU 可用性，再通过 `.pth` 接入项目隔离 venv，不重新下载或替换预装 Torch。只有预装运行时不可用时才安装后备 wheel。GPU 驱动和 `/dev/kfd` 必须由推理节点宿主环境提供；使用其他 ROCm 版本时，应覆盖预装 Python 路径，或同时覆盖 `PYTORCH_INDEX_URL` 和 `PYTORCH_PACKAGES`。

## 5. 首次一键部署

在项目根目录执行：

```bash
./deploy.sh up
```

脚本按照以下顺序运行：

1. 检查 Git、Python、uv、Node、npm、Docker 与 rsync；仅 SSH 目标检查 OpenSSH。
2. 验证部署目标与端口；SSH 目标额外验证 Key 登录。
3. 验证仓库自带的两套 llama.cpp、stable-diffusion.cpp 固定 revision 标记及递归子模块完整性。
4. 上传远端控制脚本，准备缺失的普通编译工具，验证并按需修复系统 CA 信任链。
5. 探查 GPU、显存、磁盘、ROCm 和 PyTorch HIP；仅在缺失时安装 ROCm 用户态组件和配置指定的 PyTorch HIP 包。
6. 将 FastAgentFactory 最小推理 bundle 放入推理节点目录；本机目录与当前仓库相同时直接复用。
7. 准备官方与 AMD 两套 llama.cpp，以及完整 stable-diffusion.cpp 源码；节点不访问 GitHub，直接为两套实现构建 ROCm `llama-server`、`llama-bench`，并构建 HIPBLAS `sd-server`。
8. 从国内镜像断点续传 Chat GGUF 和 mmproj。
9. 校验模型文件大小和 SHA256；损坏的完整文件不会被复用。
10. 从 ModelScope 下载或复用 `BAAI/bge-m3`。
11. 下载并校验 FLUX.1-dev Q4_0、VAE、CLIP-L 与 T5XXL。
12. 幂等同步 Chat、Embedding、Image Generation 的节点 Profile 与 Web external Profile，并清理不属于当前部署清单的旧模型与推理配置。
13. 设置 `main`、`task`、`compression` 和 `embedding` 默认 Profile。
14. 激活 `LLAMA_DEFAULT_IMPLEMENTATION`，启动推理节点并等待 Chat、Embedding 与已启用的 Image Generation 都进入 `ready`。
15. 从统一的 `.env` 派生运行时连接参数；SSH 目标建立隧道，本机目标直连节点，随后启动前后端；传入 `--no-web` 时跳过 Web 启动。

首次下载和编译时间取决于网络、磁盘和 Radeon GPU 主机 CPU。终端会直接显示 curl 与 ModelScope 下载进度。

### 5.1 FLUX.1-dev 与 13GB 显存

部署使用 `stable-diffusion.cpp + FLUX.1-dev Q4_0`，四个文件总计约 16.3GB，其中 T5XXL FP16 常驻 CPU 内存。默认参数为单并发、1024×1024、20 Steps、CFG 1.0、Euler、Diffusion Flash Attention、CLIP/T5 CPU 和 VAE Tiling。

Image Profile 在推理节点和 Web 端都默认启用并设为 active。部署会启动 `sd-server` 并等待 FLUX 进入 `ready`，因此完成后可以直接调用图片模型。图片运行配置默认启用 `eager_load`；默认 `coexist_if_fit` 允许 Chat 与 Image 在显存预算足够时同时驻留。模型工具复用 `main` 的 `image_output` 抽象，只把 `sd-server` 当作调用接口，图片产物由 ArtifactStore 保存到当前 Agent Workspace。

FLUX.1-dev 使用 Non-Commercial License，不等同于 Apache/MIT。比赛演示和提交前应保留模型来源、revision、SHA256 与许可证说明。

### 5.2 幂等与续传

重复运行 `./deploy.sh up` 的行为：

- 已校验的 GGUF 根据大小和 SHA256 标记复用；
- 部分 GGUF 使用 HTTP Range 继续下载；
- ModelScope 复用自身缓存；
- llama.cpp 使用 Ninja 增量构建；
- stable-diffusion.cpp 固定 revision 的完整 vendor 源码会幂等同步，并使用 Ninja 增量构建；
- 远端无需访问 GitHub；CA 探针只验证国内 Python/模型下载链路，DNS、路由或防火墙问题会原样报错；
- Profile 按固定 ID 更新，不重复创建随机记录；
- 部署生成的模型池以当前清单为准，旧主机、旧命名规则和已移除模型留下的 Profile 与 Artifact 会被清理；
- 本机 `.env` 保留已有 `AGENTFACTORY_RESOURCE_MASTER_KEY`，缺失时只生成一次。

## 6. 部署验收

### 6.1 环境验收

```bash
./deploy.sh doctor
```

输出至少应包含：

- AMD GPU Marketing Name；
- 总显存；
- ROCm/HIP 信息；
- `torch=<version>`；
- `gpu_available=True`；
- llama-server version；
- 模型目录所在文件系统剩余容量。

### 6.2 服务验收

```bash
./deploy.sh status
```

合格状态：

- Inference Node PID 存在；
- `chat.phase` 为 `ready`；
- `embedding.phase` 为 `ready`；
- Chat Profile 为 `Qwen3.6-35B-A3B-APEX-I-Quality`；
- Embedding Profile 为 `BAAI/bge-m3`。

启动本机 Web 后验证：

```bash
curl --fail http://127.0.0.1:8000/health
curl --fail http://127.0.0.1:18004/health
curl --fail http://127.0.0.1:18004/runtime/rocm
curl --fail http://127.0.0.1:18004/runtimes
curl --fail http://127.0.0.1:18003/v1/models
```

Embedding 由模型配置页面和后端运行状态共同验收，不需要把远端端口暴露公网。

### 6.3 Web 验收

访问：

```text
http://127.0.0.1:3000
```

在“模型配置”确认：

- GPU 型号、ROCm、PyTorch HIP 和显存数据来自远端节点；
- Chat 与 Embedding 状态为 ready；
- Chat 显示 256K Context、Q8_0 KV 和 Flash Attention；
- mmproj 已关联，Profile 允许图片输入；
- 显存预算显示预计占用、剩余显存和是否可加载。

## 7. 服务生命周期

| 命令 | 作用 |
| --- | --- |
| `./deploy.sh up` | 按 `DEPLOY_TARGET` 幂等部署推理节点并启动 Web；SSH 目标同时建立隧道。 |
| `./deploy.sh up --no-web` | 完成推理节点一键部署，不启动前后端。 |
| `./deploy.sh bootstrap` | 部署并启动推理节点，不启动 Web。 |
| `./start.sh` | 已部署环境中只启动 Web、Docker Runtime，并按连接模式直连节点或建立 SSH 隧道。 |
| `./deploy.sh status` | 查看推理节点软件、ROCm 和模型运行状态。 |
| `./deploy.sh logs` | 查看推理节点最近 200 行日志。 |
| `./deploy.sh restart` | 重启推理节点并等待模型 ready。 |
| `./deploy.sh down` | 停止推理节点、卸载模型并释放显存。 |
| `./deploy.sh models` | 续传/校验模型并刷新 Profile；运行中会自动重启。 |
| `./deploy.sh sync` | 同步 FastAgentFactory 和本机 llama.cpp 到远端。 |
| `./deploy.sh build-llama [official\|amd\|all]` | 独立增量构建指定实现；默认构建两套。 |
| `./deploy.sh switch-llama <official\|amd>` | 切换实现并用同一 Profile 重载模型。 |
| `./deploy.sh list-llama-builds` | 查看构建清单、SHA256 和活动实现。 |
| `./deploy.sh rollback-llama` | 恢复上一次活动实现。 |

按 `Ctrl+C` 只会停止前后端和 SSH 隧道（若有），推理节点模型继续运行。释放 Radeon GPU 显存必须执行：

```bash
./deploy.sh down
```

## 8. 更新项目

先确认本机工作树：

```bash
git status
git pull --ff-only
```

普通 FastAgentFactory 代码更新：

```bash
./deploy.sh sync
./deploy.sh restart
./start.sh
```

部署脚本、依赖或模型配置发生变化时，重新执行完整幂等部署：

```bash
./deploy.sh up
```

远端同步以本机工作树为代码源，只传输 inference node、model pool 及其必要公共模块，并使用 `rsync --delete-excluded` 清除 bundle 中不属于该边界的旧文件。Factory 前后端、制造系统、会话与知识库代码不会上传；原生推理源码分别通过独立 rsync 边界同步，远端模型、状态、venv 与构建目录不进入应用 bundle。

## 9. llama.cpp 算子开发与部署

仓库保留同一 llama.cpp revision 的 Official 与 AMD 两套源码。官方目录保持原样，自定义算子只进入 AMD 目录：

```bash
cd vendor/llama.cpp-amd
```

修改后执行：

```bash
cd ../..
./deploy.sh sync
./deploy.sh build-llama amd
./deploy.sh switch-llama amd
```

当前 AMD 目录暂时与官方计算实现一致，构建清单明确记录：

```json
{
  "implementation": "amd",
  "custom_kernels": false,
  "optimization_status": "placeholder"
}
```

部署构建会为每套实现同时生成 `llama-server` 与 `llama-bench`，并在 manifest 中分别记录二进制路径和 SHA256。完成算子实现后再把上述字段改为真实值。

Benchmark 页面中的“算子分析”使用活动构建的 `llama-bench`，按当前 Profile 的模型、GPU Layers、KV Cache 类型和 Flash Attention 参数分别运行 Prefill 与 Decode。每个阶段同时启用：

- `GGML_SCHED_DEBUG=2`：记录 GGML 图算子及其 HIP/CPU 后端分配；
- `GGML_CUDA_DISABLE_GRAPHS=1`：仅在算子分析子进程关闭 HIP Graph replay，保证 Host 分派与实际 Kernel 一一对应；
- `rocprofv3 --kernel-trace --stats`：记录真实 HIP Kernel、调用次数、总耗时与耗时占比。

关闭 HIP Graph 后的阶段耗时只用于算子归因，不能作为生产吞吐结果。普通性能测试和 `llama-server` 不设置该变量，继续使用 HIP Graph；优化前后的 TTFT/TPS 结论必须来自普通性能测试。

每套构建都生成带 SHA256 的 `kernel-catalog.json`。公共 Catalog 描述 llama.cpp ROCm Kernel 的稳定 ID、显示名称、家族、作用说明和符号匹配器；Official/AMD 源码根目录下的 `.fastagentfactory-kernel-catalog.json` 只登记该实现新增的 Kernel。rocprof 原始符号由活动构建的 Catalog 归一化，未登记符号使用通用解析结果并明确标记为 `unregistered`，不在 Python 或前端维护 Kernel 名称规则。Benchmark 页面可悬浮 Kernel 名称查看当前语言的作用说明，并可展开核对原始符号。

`vendor/llama.cpp-common` 提供 Official 与 AMD 共用的 Host 分派追踪协议。仅在算子分析设置 `AGENTFACTORY_KERNEL_TRACE_OUTPUT` 时，MMVQ/MMQ 分派点才把权重量化类型、M/N/K Shape、MoE/融合信息以及 waves、tile、shared memory、stream-k 等实际配置暂存在进程内，并在进程退出时一次性写入 JSON。这里 M 表示输出行数，N 表示同次分派的目标列/Token 数，K 表示归约维度。Python 分析器将该序列与按开始时间排序的 rocprof Kernel Trace 配对；每条执行路径的两侧数量必须完全一致，否则该路径的变体耗时不会展示。修改共享追踪源码会进入两套实现的 source digest，并触发重新构建。

同一个 JSON 还保留 `kernels` 汇总区，供后续 AMD 自定义分派器记录 `selected_count`、`dispatch_count`、`fallback_count` 和回退原因。文件中的 `kernel_id` 必须存在于活动构建的 Kernel Catalog。该协议能区分“满足选择条件”和“真正命中 Kernel”，同时避免逐次磁盘写入污染性能数据。

普通性能测试不会启用 profiler，避免 TTFT/TPS 被采样开销污染。算子分析会临时卸载 Chat runtime 以释放显存，结束或失败后都尝试恢复原 Profile；分析期间 Chat API 暂时不可用。原始 stdout、stderr 和 rocprof CSV 保存在远端 `.agentfactory/benchmark/operator-analysis/<run_id>/`，前端只展示结构化 Top Kernel 与图算子摘要。

部署模板默认为当前 Qwen3.6 GGUF 开启 MTP 推测解码：`CHAT_MTP_ENABLED=1` 对应 llama.cpp 的 `--spec-type draft-mtp`，候选长度、最低候选概率和 Backend Sampling 分别由 `CHAT_MTP_MAX_DRAFT_TOKENS`、`CHAT_MTP_MIN_ACCEPTANCE_PROBABILITY` 与 `CHAT_MTP_BACKEND_SAMPLING` 控制。MTP 使用 GGUF 内保留的 NextN 层，不需要第二份 Draft Model。控制节点只有在所有 llama-server Slot 都报告 `speculative=true` 后才将模型标记为 Ready；若模型没有可用 NextN 层，加载会明确失败，不能静默退回普通 Decode。

实验组的并发测试使用固定数量的闭环 Worker：每个 Worker 完成一个请求后再发起下一个请求。`并发请求数` 是同时施加的客户端压力，既可以等于 llama-server Slot 数测满载吞吐，也可以大于 Slot 数观察排队。QPS 按成功请求数除以实测窗口时长计算；聚合输入/输出 TPS 按所有成功请求 Token 总数除以同一窗口计算；同时记录错误率、TTFT P95 和请求延迟 P95。预热请求不进入这些汇总值。

Benchmark 页面提供 Official/AMD 实现切换器。切换由远端控制节点在 Chat 维护锁内完成：卸载当前模型、原子替换活动 `llama-server`、用同一 Profile 重新加载，并在失败时回滚原实现。两套实现不会同时驻留显存。rocprof 结果只从 Kernel stats 数据域计算总耗时，调度/API 汇总域不参与 Top Kernel 排名；原始模板符号按 Kernel 家族聚合后在前端展开查看。

## 10. 更换或重建 SSH 推理节点

新实例创建后：

1. 开启 SSH Access 并确认 sshd 可用；
2. 更新根目录 `.env` 的 `SSH_HOST` 与 `SSH_PORT`；
3. 如果持久卷挂载点变化，更新三个远端数据路径；
4. 执行 `./deploy.sh up`；
5. 执行本文档第 6 节验收。

若旧实例没有持久卷，模型、Profile 和远端日志不会自动迁移。一键脚本会重新构建并下载；本机 Agent 数据仍保留在 `.agentfactory` 和 `.agent_runtime`。

## 11. 故障定位

### 11.1 SSH 无法登录

```bash
ssh -vvv <SSH_USER>@<SSH_HOST> -p <SSH_PORT>
```

检查：

- 推理主机是否允许 SSH Key 登录；
- 实例内 sshd 是否运行；
- 平台 Host/Port 是否已更新；
- Profile Public Key 与本机私钥是否匹配。

### 11.2 SSH channel connection refused

SSH 已连接但远端转发目标未监听：

```bash
./deploy.sh status
./deploy.sh logs
./deploy.sh restart
```

### 11.3 ReadTimeout

根据 URL 判断：

- `18004/models`：远端目录扫描、GGUF 元数据或 Telemetry 隧道；
- `18003/v1/chat/completions`：Chat 仍在加载、Context 过大或 GPU 正在长时间计算；
- `18002`：Embedding 加载或隧道问题。
- `18005/v1/models`：sd-server 未加载、启动失败或 Image 隧道问题。

统一查看：

```bash
./deploy.sh status
./deploy.sh logs
```

### 11.4 模型下载中断

```bash
./deploy.sh models
```

部分 GGUF 会续传；完整但校验失败的文件会删除后重新下载。不要手工创建 `.sha256` 标记。

### 11.5 模型加载失败或显存不足

```bash
./deploy.sh doctor
./deploy.sh logs
```

在“模型配置”根据动态显存预算调整：

- Context；
- K/V Cache 类型；
- 并发槽位；
- GPU Layers；
- Flash Attention。

保存已加载 Profile 会将配置透传到推理节点并重启相应模型。

### 11.6 Docker 不可用

启动本机 Docker Desktop 或 Docker Engine，再执行：

```bash
./start.sh
```

远端模型服务不依赖 Docker，但 AgentPackage、MCP 和子 Agent 隔离运行依赖本机 Docker。

## 12. 部署与性能证据

部署验收时建议保存：

```text
gpu/rocm-smi-before.txt
gpu/rocm-smi-after.txt
gpu/gpu-monitor.png
benchmark/baseline.json
profile/rocprof-report/
profile/analysis.md
```

可使用以下命令生成基础文本证据：

```bash
./deploy.sh doctor > gpu/rocm-smi-before.txt
./deploy.sh status > gpu/runtime-status.txt
```

运行 Benchmark 后再次记录 GPU 状态。截图中应同时包含 GPU 型号、ROCm/HIP、显存、已加载模型和推理指标。

## 13. 静态检查

部署脚本不自动运行 Agent 业务示例。提交前执行：

```bash
bash -n deploy.sh deploy/remote_runtime.sh start.sh web_frontend/start_backend.sh
python3 -m compileall -q agent_factory web_frontend/backend deploy
git diff --check
```

这些检查验证语法和文件一致性，不替代 AMD ROCm 真机部署验收。
