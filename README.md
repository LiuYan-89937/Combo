# FastAgentFactory

FastAgentFactory 是面向私有 AI Agent 开发与本地部署的工作台。项目将 Agent 制造、运行、知识库、RAG、工具调用、多轮记忆、权限审批、运行 Trace 与性能 Benchmark 集成在同一套 Web 界面中。

`AMD-Hackson` 分支用于 **2026 AMD AI DevMaster 黑客松赛道二**：

- 本机运行 FastAgentFactory 前端、后端、Agent 工作流与 Docker 隔离运行时。
- RadeonCloud 运行 llama.cpp ROCm Chat 推理、PyTorch ROCm Embedding 和 GPU 遥测。
- 本机通过 SSH 隧道访问远端服务，不向公网暴露模型端口。
- Chat 使用 GGUF；Embedding 使用 SentenceTransformers + PyTorch HIP。
- llama.cpp 源码同时保留在本机，便于后续 AMD 算子、Kernel 和推理参数优化。

![FastAgentFactory 闲聊工作台](readme-assets/images/chat.png)

## 文档导航

- [部署与验收指南](docs/Deployment.md)：从 SSH 配置到双端启动、模型下载、验收、更新与实例迁移。
- README 当前页面：项目定位、系统架构、主要功能、日常使用和开发入口。

## 系统架构

```text
本机
┌────────────────────────────────────────────────────────────┐
│ Browser :3000                                              │
│   │ HTTP + SSE                                             │
│ FastAgentFactory Backend :8000                             │
│   ├─ AgentPackage / RuntimeKernel / RAG / Memory / Tools    │
│   ├─ Model Pool / Benchmark / Trace / Workspace            │
│   └─ Docker Agent Runtime                                  │
│                                                            │
│ SSH Tunnel                                                 │
│   18003 -> remote 8003  Chat OpenAI API                    │
│   18002 -> remote 8002  Embedding API                      │
│   18004 -> remote 8004  Inference control + ROCm telemetry │
└──────────────────────────────┬─────────────────────────────┘
                               │ SSH key only
RadeonCloud                    ▼
┌────────────────────────────────────────────────────────────┐
│ FastAgentFactory Inference Node :8004                      │
│   ├─ llama-server ROCm :8003                               │
│   ├─ SentenceTransformers + PyTorch HIP :8002              │
│   └─ ROCm / VRAM / model runtime telemetry                 │
│                                                            │
│ /root/fastagentfactory-llama-sources  official + AMD source│
│ /root/.fastagentfactory/llama         builds + active link │
│ /root/models               GGUF + mmproj + bge-m3          │
│ /root/.fastagentfactory    registry + PID + logs + venv    │
└────────────────────────────────────────────────────────────┘
```

## 默认模型

首次部署使用以下组合，均可在 `deploy/deploy.env` 修改：

| 用途 | 模型 | 下载方式 | 默认配置 |
| --- | --- | --- | --- |
| Chat | `Qwen3.6-35B-A3B-APEX-I-Quality.gguf` | Hugging Face 国内镜像，断点续传并校验 SHA256 | 256K Context、Q8_0 KV、Flash Attention、单并发、GPU Layers 99 |
| Vision projector | 对应的 `mmproj-...-APEX-F16.gguf` | Hugging Face 国内镜像，断点续传并校验 SHA256 | 随 Chat Profile 加载 |
| Embedding | `BAAI/bge-m3` | ModelScope | 1024 维、归一化、PyTorch HIP |

Chat GGUF 约 23.5 GB，视觉投影器约 0.9 GB，另需 Embedding、llama.cpp 构建目录和运行状态空间。首次部署前请确认 RadeonCloud 持久盘容量充足。

## 环境要求

### 本机控制端

- macOS 或 Linux
- Git
- OpenSSH：`ssh`、`scp`
- `rsync`
- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- Node.js 18+ 与 npm
- Docker Engine 或 Docker Desktop

Docker 用于 AgentPackage、MCP 和子 Agent 的隔离运行，不用于 RadeonCloud 模型推理。

### RadeonCloud 推理节点

推荐工作空间：

- Image：`amd-oneclick-base:rocm7.2.1-py3.12-v20260416`
- Deploy Type：Notebook（Jupyter / OpenCode）
- GitHub Repo URL：留空
- Notebook Path：留空
- SSH Access：开启

一键脚本要求远端可以通过 SSH Key 登录，并具有 AMD GPU、ROCm 和 PyTorch HIP。脚本只会在缺失时安装 CMake、Ninja、curl、编译器等普通构建工具，**不会升级或重装 ROCm、GPU 驱动或 PyTorch**。

## 一键部署

### 1. 获取项目

```bash
git clone -b AMD-Hackson https://github.com/LiuYan-89937/FastAgentFactory.git
cd FastAgentFactory
```

### 2. 填写 SSH

```bash
cp deploy/deploy.env.example deploy/deploy.env
```

至少填写：

```dotenv
SSH_HOST=<RadeonCloud-IP>
SSH_PORT=<SSH-Port>
SSH_USER=root
SSH_KEY=
```

`SSH_KEY` 可填写私钥绝对路径或 `~/.ssh/...`；如果 ssh-agent 或 OpenSSH 已能自动选择正确密钥，可以留空。

先确认命令本身能登录：

```bash
ssh root@<RadeonCloud-IP> -p <SSH-Port>
```

### 3. 一键准备并启动

```bash
./deploy.sh up
```

首次执行会依次完成：

1. 校验本机配置和 SSH Key 登录。
2. 验证仓库内置的官方与 AMD 两套 llama.cpp 源码，不在线拉取 llama.cpp。
3. 准备缺失的普通构建工具并验证远端国内下载源的 HTTPS CA 信任链；仅在证书链缺失或损坏时重建并按需重装 `ca-certificates`。
4. 探查 RadeonCloud GPU、显存、磁盘、`/dev/kfd`、ROCm 用户态组件与 PyTorch HIP。
5. 仅在缺失时安装 ROCm 用户态构建组件和配置指定的 PyTorch HIP 包；云平台 GPU 驱动不会在工作空间内安装。
6. 仅同步推理控制、模型池所需的最小 Python bundle，以及三套完整原生推理源码到远端；Factory 前后端不上传。
7. 独立构建 `official` 与 `amd` 两个 ROCm llama-server，并从本机完整 vendor 源码构建 HIPBLAS `sd-server`；远端不访问 GitHub。
8. 从国内镜像断点续传 Chat GGUF 和 mmproj，并校验官方 SHA256。
9. 从 ModelScope 下载或复用 `BAAI/bge-m3`。
10. 从 ModelScope 国内直链断点续传并校验 FLUX.1-dev Q4_0、VAE、CLIP-L 与 T5XXL。
11. 幂等同步 Chat、Embedding、Image Generation 的远端本地 Profile 和本机 external Profile，并清理不属于当前部署清单的旧模型与推理配置。
12. 激活配置指定的 llama.cpp 实现并启动远端推理节点，等待 Chat 与 Embedding 都进入 `ready`。
13. 生成本机 `.env` 的 SSH 隧道配置与资源加密密钥。
14. 准备本机 Python/前端依赖和 Docker Agent Runtime，启动前后端。

模型下载支持续传。已校验文件会通过旁路校验标记直接复用，重复执行不会重新下载 20 GB 以上的 GGUF。

启动完成后访问：

```text
http://localhost:3000
```

`deploy.sh up` 在前台运行本机服务。按 `Ctrl+C` 会停止本机前后端和 SSH 隧道，但远端推理节点保持运行；需要释放远端显存时执行 `./deploy.sh down`。

## 部署命令

| 命令 | 作用 |
| --- | --- |
| `./deploy.sh up` | 完成幂等部署，然后启动本机 Web 和 SSH 隧道。 |
| `./deploy.sh up --no-web` | 完成相同的远端部署，但不启动本机前后端。 |
| `./deploy.sh bootstrap` | 准备本机与远端、下载模型并启动远端推理，但不启动本机 Web。 |
| `./deploy.sh doctor` | 查看远端 GPU、显存、磁盘、ROCm、PyTorch HIP 和 llama.cpp。 |
| `./deploy.sh status` | 查看远端推理节点、Chat、Embedding 和软件版本状态。 |
| `./deploy.sh logs` | 查看远端推理节点最近 200 行日志。 |
| `./deploy.sh restart` | 重启远端推理节点并等待两个模型 ready。 |
| `./deploy.sh down` | 停止远端推理节点，同时卸载 Chat 与 Embedding、释放显存。 |
| `./deploy.sh models` | 续传/校验模型并更新远端 Profile；节点已运行时自动重启模型，不重装 ROCm。 |
| `./deploy.sh sync` | 同步最小推理 bundle 与本机 llama.cpp 工作树到远端。 |
| `./deploy.sh build-llama [official\|amd\|all]` | 独立增量构建指定 llama-server；省略参数时构建两者。 |
| `./deploy.sh switch-llama <official\|amd>` | 切换活动实现并使用相同 Profile 重载模型，失败时恢复原实现。 |
| `./deploy.sh list-llama-builds` | 查看两套构建的 revision、源码与二进制校验值及活动状态。 |
| `./deploy.sh rollback-llama` | 切回上一次活动实现。 |
| `./deploy.sh build-sd` | 在远端同步固定 revision 及完整子模块并增量构建 sd-server。 |

更换实例时只需修改 SSH Host 和 Port。持久盘路径变化时同时修改 `REMOTE_MODEL_ROOT`、`REMOTE_STATE_ROOT`、`REMOTE_LLAMA_SOURCE_ROOT`、`REMOTE_LLAMA_RUNTIME_ROOT` 和 `REMOTE_STABLE_DIFFUSION_CPP_DIR`。

## 日常启动

完成过 `bootstrap` 后，日常启动本机工作台也可直接运行：

```bash
./start.sh
```

`start.sh` 会：

- 读取 `.env`。
- 建立并验证 Chat、Embedding、Image、Telemetry 四条 SSH 转发。
- 使用 uv 同步本机 Python Web 依赖。
- 使用 npm 准备前端依赖。
- 检查并构建 Docker Agent Runtime。
- 启动后端 `:8000` 和前端 `:3000`。

它不会重新构建 llama.cpp 或下载模型；这些操作统一由 `deploy.sh` 管理。

## 使用指南

### 模型配置

进入“模型配置”页面可以：

- 查看远端 AMD GPU、ROCm、PyTorch HIP、显存占用和 GPU 利用率。
- 查看 Chat 与 Embedding 的加载阶段、日志和实际 Profile 参数。
- 加载、卸载、重启模型。
- 设置默认 `main`、`task`、`compression` 与 `embedding` Profile。
- 配置 stable-diffusion.cpp 生图 Profile、默认尺寸、Steps、CFG、Diffusion Flash Attention、CPU 文本编码器和显存驻留策略。
- 修改 Context、最大输出、压缩阈值、GPU Layers、KV Cache 类型、并发、Flash Attention 和图片输入能力。
- 根据 GGUF 元数据、上下文、并发和 KV Cache 类型查看预计显存占用及余量。

保存一个已经加载的 external Profile 后，本机后端会将配置透传到 RadeonCloud 并重启对应模型，新的 `--ctx-size`、KV Cache、Flash Attention 等参数会真正进入远端 llama-server 命令行。

### 本地图片生成

FLUX.1-dev Q4_0 由远端 `sd-server` 提供 OpenAI-compatible Images API。Agent 沿用项目已有的 `image_output` 模型工具链，生成结果写入当前 Package Workspace 的 `images/`；模型上下文只接收路径和元数据，不注入 base64。

图片 Profile 默认启用 eager load，`sd-server` 启动后会立即将模型参数加载到配置的计算后端。可通过部署配置中的 `IMAGE_EAGER_LOAD=0` 恢复首次生图时再加载的行为。

Image Profile 默认允许在显存预算足够时与 Chat 同时驻留，模型配置页会展示实时显存预算和运行状态。FLUX.1-dev 受其 Non-Commercial License 约束，提交和演示前需确认使用范围。

![本地模型池](readme-assets/images/model-pool.png)

### 闲聊与 Tool Calling

进入“闲聊”后：

1. 确认 Chat Profile 为 `ready` 且已设为默认 `main`。
2. 发送普通消息验证流式输出。
3. 发送需要文件、知识库或 Workspace 的任务验证结构化 Tool Calling。
4. 在右侧状态栏查看 Thinking、工具调用、权限审批、Token 和 KV Cache 指标。

### 知识库与 RAG

1. 创建知识源并上传文档。
2. 等待文档切分和 Embedding 完成。
3. 将知识源挂载到当前 Agent 或 AgentPackage。
4. 提问内部资料、项目事实或要求引用来源的问题。
5. 在 Trace 中检查 `knowledge search/open/read` 与引用来源，查询无结果时不应伪造内容。

### Agent 制造与运行

在“Agent 制造”中描述目标、输入边界和交付标准。生成的 AgentPackage 保存模型 Profile 引用、工具权限、知识库和运行契约，不保存 GPU 绝对配置。

发布后可以为 Agent 创建独立运行实例。每个实例拥有独立会话、工作区、知识库、长期记忆、工具审批和 Trace。

![Agent 制造](readme-assets/images/agent-authoring.png)

### Benchmark

“性能测试”页面统一记录：

- TTFT
- Prompt Tokens/s
- Decode Tokens/s
- End-to-End Latency
- Peak VRAM
- Average / Peak GPU Usage
- Power
- KV Cache 命中相关指标

每次优化应使用相同 Prompt、输出上限、Context、并发和采样参数。Benchmark 会从远端自动记录活动 implementation、源码 revision、源码摘要和二进制 SHA256，不能手填实现身份。

## llama.cpp AMD 算子改造

仓库直接携带两套 llama.cpp 源码：

```text
vendor/llama.cpp-official/   固定官方 Baseline，不接受 AMD 算子修改
vendor/llama.cpp-amd/        AMD 优化承载目录
vendor/stable-diffusion.cpp/ 完整图片推理源码与递归子模块
```

当前 AMD 目录与官方基线计算实现相同，仅构建产物名称和实现元数据独立，状态会显示 `optimization_status=placeholder`。后续自定义算子只修改 AMD 目录：

```bash
cd vendor/llama.cpp-amd
# 修改 ggml HIP 分派和 AMD Kernel
```

修改 HIP Kernel 或 llama.cpp 实现后：

```bash
cd ../..
./deploy.sh sync
./deploy.sh build-llama amd
./deploy.sh switch-llama amd
```

官方和 AMD 使用相互独立的 CMake/Ninja 构建目录。切换实现不会改变模型 Profile；Performance Benchmark 自动识别当前活动二进制。实现 AMD Kernel 后必须把构建清单的 `custom_kernels` 和 `optimization_status` 更新为真实状态，并增加 Kernel 命中证据，不能只改显示名称。

## 配置与数据目录

### 本机

```text
.env                         本机运行与 SSH 隧道配置，不提交
deploy/deploy.env            一键部署配置，不提交
.agentfactory/               模型池、知识库、记忆与平台状态，不提交
.agent_runtime/              Agent 工作区、Trace 与 Checkpoint，不提交
vendor/llama.cpp-official/   随仓库提交的官方 Baseline 源码
vendor/llama.cpp-amd/        随仓库提交的 AMD 优化源码
vendor/stable-diffusion.cpp/ 随仓库提交的图片推理源码与递归子模块
```

### RadeonCloud

默认目录：

```text
/root/FastAgentFactory       最小推理 bundle，不含 Factory 前后端
/root/.fastagentfactory      Python venv、模型池 SQLite、PID 与日志
/root/models                 GGUF、mmproj 与 ModelScope 模型
/root/fastagentfactory-llama-sources  两套同步源码
/root/.fastagentfactory/llama        两套构建、清单和活动软链接
/root/stable-diffusion.cpp           从本机 vendor 同步的完整源码与远端构建产物
```

`/root` 是否持久取决于实例类型。若平台提供持久卷，应在 `deploy/deploy.env` 将模型、状态和 llama.cpp 路径改到其挂载点；否则工作空间到期前必须备份 Benchmark、Profile、Trace、演示材料和 llama.cpp 改动。

## 安全边界

- SSH 必须使用 Key 登录，不在配置文件中保存密码。
- `deploy/deploy.env`、`.env`、模型文件和运行状态均已排除 Git 提交；两套 llama.cpp 和 stable-diffusion.cpp 完整源码属于交付内容。
- 远端 `8002`、`8003`、`8004` 只监听 `127.0.0.1`，不要直接暴露公网。
- `AGENTFACTORY_RESOURCE_MASTER_KEY` 首次部署自动生成并写入本机 `.env`；丢失后旧的加密资源无法恢复。
- 部署脚本先复用可用的 ROCm/PyTorch HIP 环境，仅在缺失且配置允许时安装用户态组件。GPU 驱动和 `/dev/kfd` 必须由 RadeonCloud 工作空间提供。

## 排障

### SSH 登录失败

```bash
ssh -vvv root@<host> -p <port>
```

确认 RadeonCloud 已开启 SSH Access、实例内 sshd 正在运行、平台端口已刷新，并且 Profile SSH Public Key 与本机私钥匹配。

`channel ... open failed: connect failed: Connection refused` 通常表示 SSH 本身已连接，但远端 `8002/8003/8004` 尚未启动。执行：

```bash
./deploy.sh status
./deploy.sh logs
./deploy.sh restart
```

### ReadTimeout

先看报错 URL：

- `/models` 超时：检查远端节点是否正在首次解析 GGUF、缓存是否预热、SSH 隧道是否稳定。
- `/v1/chat/completions` 超时：检查模型是否仍在 loading、Context 是否过大、GPU 是否在计算。
- `18004` 连接失败：检查 Telemetry SSH 转发和远端节点 PID。

```bash
./deploy.sh status
./deploy.sh logs
```

### 模型下载中断

直接重新执行：

```bash
./deploy.sh models
```

GGUF 使用 `curl --continue-at -` 续传；完成后必须通过 SHA256 才会写入已验证标记。Embedding 由 ModelScope 缓存复用。

### 模型无法加载或显存不足

检查：

```bash
./deploy.sh doctor
./deploy.sh logs
```

然后在模型配置中降低 Context、并发或 KV Cache 精度，或减少 GPU Layers。修改已加载 Profile 会触发远端重启并应用新参数。

### 本机 Docker 不可用

启动 Docker Desktop 或 Docker Engine后重新运行 `./start.sh`。模型推理仍在 RadeonCloud，但 MCP、AgentPackage 和子 Agent 的隔离运行依赖本机 Docker。

## 静态检查

项目开发约定不通过部署脚本运行 Agent 业务示例。提交前执行语法和静态检查：

```bash
bash -n deploy.sh deploy/remote_runtime.sh start.sh web_frontend/start_backend.sh
python3 -m compileall -q agent_factory web_frontend/backend deploy
git diff --check
```

前端类型检查：

```bash
cd web_frontend/frontend
npm run type-check
```
