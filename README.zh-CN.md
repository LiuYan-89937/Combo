[English](README.md) | [简体中文](README.zh-CN.md)

# FastAgentFactory

> 基于多 Agent 平台的智能协作助手。

FastAgentFactory 将对话、任务拆分、Agent 调度、工具执行、知识检索、长期记忆、工作区和结果交付统一到一个可审计的协作平台中。主 Agent 可以直接完成任务，也可以按需调用、制造或进化专业 Agent，再对多个执行链的结果进行验收与统一交付。

平台支持 Linux/ROCm 本机部署，也支持 macOS、Windows 或 Linux 控制端通过 SSH 连接远程 AMD Radeon 推理节点。AgentPackage 由宿主监督的 Native Runtime 子进程执行，通过独立工作区、独立运行目录和共享只读依赖池实现逻辑隔离，不依赖 Docker。

![FastAgentFactory 项目海报](supplementary-materials/poster/fastagentfactory-project-poster.png)

## 从这里开始

根据你的目标选择阅读路径：

| 我想…… | 建议先看 |
| --- | --- |
| 快速了解产品 | [平台定位](#平台定位) → [核心能力](#核心能力) → [演示视频](#演示视频) |
| 部署并运行 | [运行架构](#运行架构) → [环境要求](#环境要求) → [一键部署](#一键部署) |
| 使用 Agent | [首次使用](#首次使用) → [功能指南](#功能指南) |
| 查看 AMD 优化 | [AMD Radeon 推理优化](#amd-radeon-推理优化) → [Benchmark 与算子分析](#benchmark-与算子分析) |
| 开发或验收 | [项目目录](#项目目录) → [开发与静态检查](#开发与静态检查) → [详细文档](#详细文档) |

## 平台定位

FastAgentFactory 不是把多个聊天窗口拼在一起，也不是要求每个任务都必须分发给子 Agent。它以主 Agent 为统一入口，根据任务复杂度和当前资源做动态决策：

1. 简单任务由主 Agent 直接执行。
2. 已有专业 Agent 能处理时，主 Agent创建后台任务并委派。
3. 需要多领域协同时，多个 Agent 可以异步运行，主 Agent继续接收用户消息并调整任务。
4. 现有能力不足时，可以启动制造流程生成新的 AgentPackage。
5. 已发布 Agent 表现不理想时，可以进入进化流程修改能力并重新验证。

用户在一个会话中看到的是统一交互，而不是内部运行模式的割裂页面。任务链、参与 Agent、工具调用、审批、失败、暂停、外部等待和交付物都通过同一运行协议投影到前端。

## 核心能力

### 主 Agent 与异步多 Agent 协作

- 主 Agent 可以直接调用工具，也可以创建并调度子 Agent 任务。
- 多个 Agent 使用独立会话和运行状态，不共享未授权的上下文。
- 后台任务具有排队、容量准入、租约、心跳、取消、恢复和结果交付状态。
- 运行中发送的新消息进入队列，由主 Agent 在下一轮判断是补充、改向、停止还是继续。
- 多 Agent 协作使用独立任务工作区；Agent 群聊可以让多个成员以独立会话共享同一个本机目录。

### Agent 制造与进化

- 使用自然语言描述 Agent 的用途、边界和交付标准。
- 自动完成需求分析、Agent 身份、模型契约、工具、Skill、MCP、知识和运行 Pattern 配置。
- 工具实现必须经过真实 Probe；依赖初始化、标准输出、失败阶段和最终结果可观测。
- 完整静态校验通过后进入待发布状态，由用户在悬浮任务卡中确认发布。
- 进化链路复用制造的 authoring、probe、validation 和 publish 状态机。

### AgentPackage 运行体系

AgentPackage 是平台的可发布能力单元，描述：

- Agent 身份与运行 Pattern。
- 模型角色绑定和允许的覆盖项。
- 工具、风险等级、审批策略、并发语义和输出压缩策略。
- MCP、Skill 与知识库绑定关系。
- Context、跨会话记忆和压缩策略。
- Scheduler 默认时区、并发、超时、无人值守审批和失败暂停策略。

已发布包不保存用户模型凭据、Resource 密钥、聊天记录、附件和运行时 Checkpoint。下载外部 Agent 包后，需要在本地重新选择并绑定可用模型。

### 工作区与文件交付

- 新会话可以使用平台管理的独立工作区，也可以挂载本机已有目录。
- 挂载模式不复制原目录；用户可以随时解除挂载。
- 同一挂载工作区可以承载多个会话，每个 Agent仍保留独立会话状态。
- 输入附件、知识材料、图片和生成文件可以在工作区浏览和打开。
- 文件创建、修改、移动、复制和删除通过结构化工具或受控 Shell 执行，并保留工具记录。

### 扩展、知识与记忆

- MCP 和 Skill 在全局注册中心统一配置，再绑定到具体 Agent。
- MCP 支持 stdio 与网络传输、环境变量、Header、超时和工具风险默认值。
- Skill 可以包含 `SKILL.md`、脚本、模板和其他资源，而不是只有一段提示词。
- 知识库支持文件摄取、切分、Embedding、检索、打开和引用来源。
- 跨会话记忆区分工作区作用域和全局作用域，并按当前会话检索注入。
- Context 压缩阈值默认跟随模型配置，也可以由 AgentPackage 覆盖。

### 调度、审批与可观测性

- 定时任务支持时区、并发策略、超时、失败计数和自动暂停。
- 工具审批、用户问答、资源请求与发布确认统一进入悬浮任务卡。
- Auto 模式按照工具权限自动审批，并允许主 Agent自动与子 Agent交互。
- Trace 保留模型流、工具调用、阶段、Token、缓存、任务状态和错误摘要。
- 工具执行耗时动态更新；图片类工具结果可以在消息中直接展示。

## 典型使用场景

### 办公交付

用户提供主题、附件和风格要求，主 Agent 调用搜索、知识库与文件工具，必要时委派给文档或演示文稿 Agent，最终把可编辑文件写入当前工作区。

### 复杂研究

主 Agent 将一个目标拆成多个证据任务，调用不同专业 Agent并行执行。每个任务返回来源、时间和产物，主 Agent完成语义验收、冲突处理和最终汇总。

### 周期事务

Agent 创建一次性或周期 Scheduler 任务，在无人值守策略允许的范围内生成简报、提醒或文件。需要批准的外部操作不会绕过权限策略。

### A 股多 Agent 演示

仓库内置三个 A 股专业 Agent，用于展示真实数据工具、多 Agent 协作和交付：

| Agent | 负责内容 | 典型交付 |
| --- | --- | --- |
| A 股盘面雷达 | 市场宽度、成交额、板块和领涨个股 | 盘面简报、异常说明、Markdown 报告、经授权发送的邮件 |
| A 股上市公司研究员 | 行情、财务、趋势和用户材料 | 带来源与数据时间的公司研究报告 |
| A 股持仓风险管家 | 集中度、波动率、回撤、相关性和压力情景 | 组合风险报告与情景分析 |

主 Agent 可以同时研究市场与多家公司，再对模拟持仓进行 `5%`、`10%` 下跌压力评估并统一交付。所有金融输出仅用于研究和系统能力演示，不构成投资建议。

## 运行架构

```text
控制端（macOS / Windows / Linux）
┌────────────────────────────────────────────────────────────┐
│ Browser :3000                                              │
│   │ HTTP + SSE                                             │
│ FastAgentFactory Backend :8000                             │
│   ├─ 主 Agent / 后台任务 / 多 Agent 调度                  │
│   ├─ AgentPackage / RuntimeKernel / Tool Gateway           │
│   ├─ Model Pool / Knowledge / Memory / Scheduler           │
│   ├─ Workspace / Trace / Approval / Artifact               │
│   └─ Native Agent Runtime / 独立会话工作区                 │
│                                                            │
│ 本机回环或 SSH Tunnel                                      │
│   18003 -> inference 8003  llama.cpp 直连诊断             │
│   18002 -> inference 8002  Embedding API                   │
│   18004 -> inference 8004  准入、控制与 Telemetry          │
│   18005 -> inference 8005  Image Generation API            │
└──────────────────────────────┬─────────────────────────────┘
                               │ SSH Key only
AMD ROCm 推理节点              ▼
┌────────────────────────────────────────────────────────────┐
│ FastAgentFactory Inference Control :8004                   │
│   ├─ 跨会话公平调度 / 优先级 / 排队 / 取消                │
│   ├─ llama-server ROCm :8003                               │
│   ├─ SentenceTransformers + PyTorch HIP :8002              │
│   ├─ stable-diffusion.cpp HIPBLAS :8005                    │
│   └─ GPU / VRAM / Model Lifecycle / Benchmark Telemetry    │
│                                                            │
│ official + AMD llama.cpp source / build / active link      │
│ GGUF + mmproj + bge-m3 + FLUX model files                  │
└────────────────────────────────────────────────────────────┘
```

平台支持两种拓扑：

- `DEPLOY_TARGET=local`：Web、Agent Runtime 和 AMD 推理节点位于同一台 Linux/ROCm 主机，服务通过回环地址直连。
- `DEPLOY_TARGET=ssh`：Web 与 Agent Runtime 位于控制端，AMD 推理节点位于远程 Linux 主机，通过 SSH 隧道访问回环服务。

两种拓扑复用相同的模型 Profile、Agent 运行链路、容量调度、Official/AMD 切换和 Benchmark，不维护功能降级的远程分支。

## 默认模型

首次部署使用以下组合；需要覆盖时统一修改根目录 `.env` 或模型配置页面：

| 用途 | 模型 | 下载方式 | 默认配置 |
| --- | --- | --- | --- |
| Chat | `Qwen3.6-35B-A3B-APEX-I-Quality.gguf` | Hugging Face 国内镜像，断点续传并校验 SHA256 | 256K Context、Q8_0 KV、Flash Attention、3 Slots、公平准入调度、GPU Layers 99 |
| Vision projector | 对应 `mmproj-...-APEX-F16.gguf` | Hugging Face 国内镜像 | 随 Chat Profile 加载 |
| Embedding | `BAAI/bge-m3` | ModelScope | 1024 维、归一化、PyTorch HIP |
| Image | `FLUX.1-dev Q4_0` + VAE + CLIP-L + T5XXL | ModelScope 国内直链 | stable-diffusion.cpp HIPBLAS、1024×1024、20 Steps、eager load |

Chat GGUF 约 `23.5 GB`，视觉投影器约 `0.9 GB`，FLUX 相关文件约 `16.3 GB`。此外还需要 Embedding、原生构建和运行状态空间，部署前请确认推理节点磁盘容量。

## 环境要求

### 控制端

- macOS、Linux 或 Windows 10/11。
- Git。
- OpenSSH：`ssh`、`scp`。
- Python 3.11+。
- [uv](https://docs.astral.sh/uv/)。
- Node.js 18+ 与 npm。

SSH 远程部署在 macOS/Linux 上优先使用 `rsync` 增量同步。Windows 使用 OpenSSH、SCP 和压缩归档完成相同同步边界，不要求 WSL、Git Bash 或 Docker。只有 Linux 本机 ROCm 部署要求 `rsync`。

### AMD ROCm 推理节点

- Linux 与可用的 AMD Radeon GPU。
- ROCm 用户态运行和编译组件。
- `/dev/kfd` 访问权限。
- 与当前 ROCm 版本兼容的 PyTorch HIP。
- SSH 模式下支持 SSH Key 登录。

部署脚本只在缺失时准备 CMake、Ninja、curl、编译器等普通构建工具，不会升级或重装 GPU 驱动。

> **服务器镜像提示**：在 RadeonCloud/AMD 云平台创建推理服务器时，建议选择 `ROCm vLLM-dev (Navi) (vllm-dev:rocm7.2.1_navi_ubuntu22.04_py3.10_pytorch_2.9_vllm_0.16.0)`。使用其他镜像前需要确认 ROCm、PyTorch HIP、`/dev/kfd` 与 Python ABI 兼容。

## 一键部署

### 1. 获取项目

```bash
git clone https://github.com/LiuYan-89937/FastAgentFactory.git
cd FastAgentFactory
cp .env.example .env
```

Windows PowerShell 使用：

```powershell
Copy-Item .env.example .env
```

### 2. 配置远程 AMD 推理节点

在 `.env` 中填写：

```dotenv
DEPLOY_TARGET=ssh
SSH_HOST=<AMD-Inference-Host>
SSH_PORT=<SSH-Port>
SSH_USER=root
SSH_KEY=~/.ssh/<private-key>
```

`SSH_KEY` 可以是私钥绝对路径或 `~/.ssh/...`。如果 ssh-agent 或 OpenSSH 能自动选择正确密钥，可以留空。

先验证命令本身可以登录：

```bash
ssh root@<AMD-Inference-Host> -p <SSH-Port>
```

从密钥生成、服务器 sshd 检查、公钥安装到连接验证的完整步骤见[部署指南的 SSH Key 章节](project-documentation/Deployment.zh-CN.md#41-从零配置-ssh-key)。

### 3. 配置本机 AMD 推理节点

AMD GPU 位于当前 Linux 主机时：

```dotenv
DEPLOY_TARGET=local
SSH_HOST=
SSH_PORT=22
SSH_USER=
SSH_KEY=
```

将 `REMOTE_PROJECT_ROOT`、`REMOTE_STATE_ROOT`、`REMOTE_MODEL_ROOT`、`REMOTE_LLAMA_SOURCE_ROOT`、`REMOTE_LLAMA_RUNTIME_ROOT` 和 `REMOTE_STABLE_DIFFUSION_CPP_DIR` 设置为当前用户可写的本机绝对路径。字段名保留 `REMOTE_`，其统一含义是“推理节点路径”。

### 4. 启动

macOS 或 Linux：

```bash
./deploy.sh up
```

Windows PowerShell：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\deploy.ps1 up
```

启动完成后访问：

```text
http://localhost:3000
```

正常日志会依次显示 `Backend is ready`、`Frontend is ready` 和 `Application ready`。Web 后端固定使用 `8000`，前端开发服务固定使用 `3000` 并支持 HMR。

### 部署脚本会做什么

首次 `up` 会按照同一幂等流程：

1. 校验部署目标；SSH 模式验证 Key 登录，本机模式验证 Linux/ROCm 主机。
2. 验证仓库内置的 Official 与 AMD 两套 llama.cpp 源码，不在线拉取 llama.cpp。
3. 探查 GPU、显存、磁盘、`/dev/kfd`、ROCm 和 PyTorch HIP。
4. 仅在缺失且配置允许时准备普通构建工具与 ROCm 用户态组件。
5. 检查国内下载源的 HTTPS CA 信任链，并只在损坏时修复。
6. 同步最小推理控制 bundle 与三套完整原生推理源码；本机同路径时直接复用。
7. 独立构建 Official、AMD `llama-server` / `llama-bench` 和 HIPBLAS `sd-server`。
8. 断点续传 Chat GGUF 与 mmproj，并校验 SHA256。
9. 从 ModelScope 下载或复用 `BAAI/bge-m3`。
10. 下载并校验 FLUX、VAE、CLIP-L 与 T5XXL。
11. 幂等同步 Chat、Embedding、Image 的远端和控制端 Profile。
12. 启动推理节点，并等待所有已启用模型进入 `ready`。
13. SSH 模式建立回环隧道，本机模式直连回环端口。
14. 按 `uv.lock` 与 `package-lock.json` 准备控制端依赖并启动前后端。

模型下载支持续传；已校验的大文件不会在重复执行时重新下载。

## 部署命令

Windows PowerShell 使用 `.\deploy.ps1` 替代 `./deploy.sh`，参数保持一致。

| 命令 | 作用 |
| --- | --- |
| `./deploy.sh up` | 幂等部署推理节点并启动 Web；SSH 模式建立隧道 |
| `./deploy.sh up --no-web` | 完成推理节点部署，不启动前后端 |
| `./deploy.sh bootstrap` | 准备模型和推理服务，不启动 Web |
| `./deploy.sh doctor` | 检查 GPU、ROCm、PyTorch HIP、磁盘和 llama.cpp |
| `./deploy.sh status` | 查看节点、模型和软件版本状态 |
| `./deploy.sh logs` | 查看推理节点最近 200 行日志 |
| `./deploy.sh restart` | 重启推理节点并等待模型 Ready |
| `./deploy.sh down` | 停止推理服务并释放显存 |
| `./deploy.sh models` | 续传、校验模型并更新 Profile |
| `./deploy.sh sync` | 同步最小推理 bundle 与原生推理源码 |
| `./deploy.sh build-llama [official\|amd\|all]` | 增量构建指定实现 |
| `./deploy.sh switch-llama <official\|amd>` | 在相同 Profile 下切换活动实现 |
| `./deploy.sh list-llama-builds` | 查看源码 revision、摘要和二进制 SHA256 |
| `./deploy.sh rollback-llama` | 恢复上一次活动实现 |
| `./deploy.sh build-sd` | 同步并增量构建 stable-diffusion.cpp |

更换实例时修改 SSH Host 与 Port。持久盘变化时同步修改模型、状态、llama 源码、构建和 stable-diffusion.cpp 路径。

## 首次使用

1. 打开“模型配置”，确认 Chat、Embedding 和已启用的 Image Profile 为 `ready`。
2. 进入“已发布 Agent”，初始化需要使用的内置 Agent。
3. 普通对话至少需要初始化 `Factory Chat`。
4. 运行 A 股协作示例前初始化三个 A 股专业 Agent。
5. 新建会话时选择独立工作区或挂载本机目录。

初始化会准备 AgentPackage 环境、工具和依赖，所以第一次启动通常比后续会话更慢。如果 Factory Chat 尚未就绪就发送消息，系统会自动开始初始化，并在完成后进入正常流式输出。

`deploy.sh up` 在前台运行。按 `Ctrl+C` 会停止前后端与 SSH 隧道，但远程推理节点保持运行；需要释放显存时执行 `./deploy.sh down`。

## 功能指南

### 模型配置

模型配置页面可以：

- 查看 AMD GPU、ROCm、PyTorch HIP、显存与 GPU 利用率。
- 查看 Chat、Embedding 和 Image 的加载阶段、日志与实际 Profile 参数。
- 加载、卸载和重启模型。
- 设置默认 `main`、`task`、`compression` 和 `embedding` Profile。
- 配置 Context、最大输出、温度、压缩阈值、GPU Layers、KV Cache、并发和 Flash Attention。
- 声明原生上下文、YaRN 支持和最大扩展上下文。
- 根据 GGUF 元数据、上下文、并发和 KV Cache 估算显存。
- 配置 FLUX 尺寸、Steps、CFG、Diffusion Flash Attention、CPU 文本编码器和驻留策略。

保存已加载的 external Profile 后，控制端会将配置透传至推理节点并重启对应模型。超过原生 Context 时，只有声明支持 YaRN 且不超过扩展上限的配置才会进入 llama-server 命令行。

### 对话、工具与工作区

进入对话后可以验证：

1. 普通消息的流式输出。
2. 文件、Shell、知识库和 MCP 的结构化 Tool Calling。
3. 工具耗时、参数、输出和审批卡片。
4. 工作区文件的实时刷新、预览与打开。
5. Token、Context、压缩和 KV Prefix Cache 指标。

工具在工作区根目录执行，Shell 不需要每次手动 `cd`。运行期间可以继续发送消息，新消息进入队列，不会错误地切断其他会话。

### MCP 与 Skill

Hackson 测试部署内置 Tavily Web Search MCP。`deploy.sh up` 会把它安装在项目 `.agentfactory/mcp/web_search` 下，构建后统一注册，并绑定到内置 Agent。

仓库内置的是共享测试密钥，只用于比赛演示，可能受到公共额度限制。AgentPackage 只保存 MCP 绑定关系，不会把测试 MCP 的私密配置写入发布包。

用户可以在扩展页面统一注册 MCP 与 Skill，再将卡片拖动绑定到目标 Agent。Skill 支持完整文件夹，不限制为单个 `SKILL.md`。

### 知识库与 RAG

标准流程：

1. 在知识库入口创建知识源并上传文件。
2. 等待文档解析、切分与 Embedding 完成。
3. 将知识源绑定到目标 Agent。
4. 提问需要内部资料或来源引用的问题。
5. 在 Trace 中检查检索、打开、读取与引用来源。

对话工具也可以添加知识，并通过高级参数覆盖切分等配置。查询无结果时 Agent 不应伪造资料内容。

### 本地图片生成

FLUX.1-dev Q4_0 由远端 `sd-server` 提供 OpenAI-compatible Images API。生成结果进入当前工作区 `images/`，模型上下文只接收路径与元数据，不注入 base64。

Image Profile 默认启用并设为 Active。部署会等待 FLUX 真正进入 `ready` 才完成；可通过 `IMAGE_ENABLED=0` 禁用，或用 `IMAGE_EAGER_LOAD=0` 改为首次调用时加载。

FLUX.1-dev 受 Non-Commercial License 约束，使用和演示前需要确认许可范围。

### Agent 制造、发布与进化

制造时应描述用途、输入边界、目标任务和交付标准。制造 Agent 会：

1. 分析意图与任务。
2. 选择 React 或 Plan-and-Execute Pattern。
3. 生成 Agent 身份、模型契约和 Context。
4. 装配 MCP、Skill、知识、Resource 与 Scheduler。
5. 编写工具并进行真实 Probe。
6. 完成静态校验。
7. 在悬浮任务卡中等待用户确认发布。

发布后可以创建独立会话。需要继续修改时进入进化流程，复用相同校验和发布边界。

## AMD Radeon 推理优化

仓库直接携带两套基于同一 revision 的 llama.cpp：

```text
vendor/llama.cpp-official/   固定 Official Baseline，不接受项目算子修改
vendor/llama.cpp-amd/        AMD RDNA3 HIP Kernel 与融合实现
vendor/llama.cpp-common/     两套实现共享的 Host Trace 协议
```

### 最强算子级结果

Q8_0 × Q8_1 Native Wave32 MMVQ 在同一 AMD 二进制内与 Official Q8 路径做独立消融：

| Q8_0 普通 Decode 路径 | 调用次数 | Kernel 总耗时 | 相对 Official |
| --- | ---: | ---: | ---: |
| Official | 5,120 | 38.775 ms | — |
| Native Wave32 | 5,120 | 20.507 ms | **-47.11%** |
| Native Wave64 | 5,120 | 22.450 ms | -42.10% |

`-47.11%` 是算子 Profiler 口径，只说明该 Kernel 家族的累计执行耗时，不等同于端到端服务吞吐提升。

### 端到端结果

在 Qwen3.6-35B-A3B Q6_K、gfx1100、单并发、256K Context、Q8_0 KV、Flash Attention 开启且 MTP 关闭的归档条件下：

| 指标 | Official | AMD 整体实现 | 变化 |
| --- | ---: | ---: | ---: |
| Decode 平均吞吐 | 84.0867 tok/s | 88.8320 tok/s | **+5.64%** |
| Decode 标准差 | 0.1943 tok/s | 0.1718 tok/s | — |
| Prompt 平均耗时 | 482.680 ms | 478.321 ms | -0.90% |
| 每次输出 Token | 256 | 256 | 相同 |
| 输出哈希 | `6c7bf1…d473` | `6c7bf1…d473` | 相同 |

Official 与 AMD 均开启 MTP 时，Decode 基本持平；AMD Prompt 吞吐提升 `16.70%`、模型计算 TTFT 降低 `14.31%`、双客户端 QPS 提升 `5.09%`、平均请求延迟降低 `4.89%`。MTP 同时改变两套实现的 Decode 调度，因此不把 MTP 自身收益归因于 AMD Kernel。

### 已实现的优化

1. **Q8_1 激活量化复用**：在单次计算图中复用相同 F32 激活的 Q8_1 临时表示，Decode Q8_1 调用减少 `42.74%`。
2. **Residual RMSNorm 融合**：把 Residual Add、RMSNorm 和权重缩放合并成一个 RDNA3 HIP Kernel，减少启动和显存往返。
3. **Native Q6_K MMVQ**：使用一个 Wave32 计算一行，删除跨 Wave LDS 合并，并共享激活读取。
4. **Q8 Wave32/Wave64 动态分派**：根据 K、输出行、LDS、Occupancy 和物理 Wave 宽度选择变体。
5. **可验证命中**：通过 Kernel Catalog、Host Shape Trace、GGML 图与 `rocprofv3` 时间线证明分派命中，不根据名称猜测。

完整实现位置、逐轮数据、输出一致性和适用边界见 [AMD RDNA3 推理优化说明](project-documentation/performance/ROCmOptimizations.zh-CN.md)。以上数据只代表归档环境，不承诺在其他模型、Shape、ROCm 版本或 GPU 上获得相同收益。

### 修改与构建 AMD Kernel

只在 AMD 目录修改算子：

```bash
cd vendor/llama.cpp-amd
# 修改 ggml HIP 分派和 AMD Kernel
```

同步、构建并切换：

```bash
cd ../..
./deploy.sh sync
./deploy.sh build-llama amd
./deploy.sh switch-llama amd
```

Official 与 AMD 使用独立 CMake/Ninja 构建目录，同时生成 `llama-server` 和 `llama-bench`。新增 Kernel 需要更新 AMD Kernel Catalog 与构建清单，再通过算子分析证明真实命中。

## Benchmark 与算子分析

性能页面记录：

- TTFT、Prompt Tokens/s、Decode Tokens/s 与端到端延迟。
- Peak VRAM、平均/峰值 GPU 利用率与功耗。
- KV Prefix Cache 复用 Token、实际计算 Token 与加权复用率。
- MTP 候选 Token、接受 Token 与接受率。
- 并发 QPS、聚合输入/输出 TPS、错误率、TTFT P95 和请求延迟 P95。

每个实验组按轮交替运行 Official 与 AMD。两套实现使用同一模型文件和 Profile，控制节点互斥切换二进制，不会让两份 Chat 模型同时占用显存。Benchmark 自动记录 implementation、源码 revision、源码摘要和二进制 SHA256，不能手工填写实现身份。

### 普通性能测试

普通测试保留服务实际使用的 HIP Graph，结果用于端到端吞吐和延迟结论。每轮必须使用相同 Prompt、输出上限、Context、并发与采样参数。

### 算子分析

算子分析与普通性能测试分开执行：

1. 临时卸载 Chat 模型。
2. 使用同一 Profile 参数运行 `llama-bench` Prefill 与 Decode。
3. 通过 `GGML_CUDA_DISABLE_GRAPHS=1` 关闭分析子进程的 HIP Graph replay。
4. 使用 `GGML_SCHED_DEBUG=2` 记录 GGML 图算子和后端。
5. 使用 `rocprofv3` 汇总 Kernel 调用次数与耗时。
6. 按 Host 分派记录与 GPU Kernel 时间线严格配对。
7. 完成后自动恢复 Chat 模型。

只有 Host 记录数和 rocprof 事件数完全一致时才展示配对变体；数量不一致会告警，不进行推测。Profiler 耗时用于归因，真实吞吐以普通性能测试为准。

## 演示视频

<video
  controls
  preload="metadata"
  poster="supplementary-materials/poster/fastagentfactory-project-poster.png"
  width="100%"
>
  <source src="FastAgentFactory-Demo.mp4" type="video/mp4">
  当前 Markdown 阅读器不支持嵌入式视频。
</video>

如果页面未显示播放器，请[直接播放或下载 MP4 演示视频](FastAgentFactory-Demo.mp4)。

演示内容包括：

1. 主 Agent 对话、工具调用和工作区交付。
2. Agent 制造、异步后台任务与发布确认。
3. 多 Agent 协作和专业 Agent 结果汇总。
4. AMD Radeon 推理节点、模型运行时和容量状态。
5. Official/AMD 配对性能测试与算子命中结果。

视频中的短测用于展示操作流程，不替代性能文档中的重复实验结论。

## 项目目录

```text
agent_factory/                  Agent、RuntimeKernel、工具、知识、记忆与调度核心
web_frontend/backend/           FastAPI Web 后端
web_frontend/frontend/          Vue 3 前端
SystemPackage/                  内置 AgentPackage
deploy/                         跨平台部署与推理控制
vendor/llama.cpp-official/      Official Baseline 源码
vendor/llama.cpp-amd/           AMD 优化源码
vendor/llama.cpp-common/        共享 Trace 协议
vendor/stable-diffusion.cpp/    图片推理源码与子模块
project-documentation/          项目、架构、部署和性能文档
supplementary-materials/        海报与补充材料
```

## 配置与数据目录

### 控制端

```text
.env                         用户部署、SSH 与模型配置，不提交
deploy/defaults.env          版本化内部默认值，不作为用户配置编辑
.agentfactory/               模型池、扩展注册、知识、记忆与平台状态，不提交
.agent_runtime/              会话工作区、Trace、Checkpoint 与工具输出，不提交
```

### 默认远程推理节点

```text
/root/FastAgentFactory               最小推理 bundle
/root/.fastagentfactory              venv、模型池 SQLite、PID 与日志
/root/models                         GGUF、mmproj 与 ModelScope 模型
/root/fastagentfactory-llama-sources Official、AMD 与共享源码
/root/.fastagentfactory/llama        构建、清单和活动软链接
/root/stable-diffusion.cpp           图片推理源码与构建产物
```

`/root` 是否持久取决于实例类型。使用持久卷时，在 `.env` 覆盖模型、状态和构建目录；临时实例到期前需要备份 Benchmark、Profile、Trace 和算子改动。

## 安全边界

- SSH 使用 Key 登录，不在配置文件中保存服务器密码。
- `.env`、模型文件、Resource 密钥、会话和运行状态均排除 Git 提交。
- 远端 `8002`、`8003`、`8004`、`8005` 默认只监听 `127.0.0.1`。
- `AGENTFACTORY_RESOURCE_MASTER_KEY` 首次部署生成并写入本机 `.env`；丢失后旧加密资源无法恢复。
- AgentPackage 使用宿主子进程、独立工作区和共享依赖池；这是逻辑隔离，不是内核级安全沙箱。
- 部署脚本不会替用户安装或升级 GPU 驱动，`/dev/kfd` 必须由宿主环境提供。
- AgentHub 上传前展示 Skill 内容和 MCP JSON 供用户检查；聊天记录、附件、运行时状态与 Resource 值不进入公开包。

## 排障

### SSH 登录失败

```bash
ssh -vvv root@<host> -p <port>
```

确认服务器 sshd 正在运行、允许 Key 登录、主机端口正确，并且服务端公钥与本机私钥匹配。

`channel ... open failed: connect failed: Connection refused` 表示 SSH 已连接，但远端推理服务尚未监听。执行：

```bash
./deploy.sh status
./deploy.sh logs
./deploy.sh restart
```

### ReadTimeout

先确认超时 URL：

- `/models`：模型可能仍在首次解析或加载。
- `/v1/chat/completions`：检查模型 Loading、Context、GPU 计算和 Slot 队列。
- `18004`：检查 Telemetry 隧道与推理控制进程。

```bash
./deploy.sh status
./deploy.sh logs
```

### 模型下载中断

```bash
./deploy.sh models
```

GGUF 使用续传；完成后只有通过 SHA256 才会写入已验证标记。Embedding 与图片模型复用 ModelScope 缓存。

### 模型无法加载或显存不足

```bash
./deploy.sh doctor
./deploy.sh logs
```

在模型配置中降低 Context、并发、KV Cache 精度或 GPU Layers。保存已加载 Profile 会触发远端重启并应用新参数。

### Agent Runtime 初始化失败

检查控制端 Python、uv、包依赖声明、工作区权限和依赖池日志，然后重新执行 `./deploy.sh up`。Native Runtime 不依赖 Docker。

### 前端或后端未就绪

检查项目目录下：

```text
.agentfactory/logs/web-backend.log
.agentfactory/logs/web-frontend.log
```

端口变化的客户端连接是浏览器临时源端口，后端监听端口仍固定为 `8000`。

## 开发与静态检查

项目约定不通过提交脚本运行特化 Agent 业务示例，只做语法和静态检查：

```bash
python3 -m compileall -q agent_factory web_frontend/backend deploy
bash -n deploy.sh deploy/start_web.sh deploy/remote_runtime.sh
git diff --check
```

前端检查：

```bash
cd web_frontend/frontend
npm run type-check
```

算子修改使用独立构建和配对 Benchmark 验证，不用一次短测代替归档数据。

## 第三方组件与许可证

项目自有源码采用 [Apache License 2.0](LICENSE)。该许可证不重新许可随仓库分发的第三方源码、运行时模型、外部数据或在线服务。

### 随仓库分发的原生源码

| 组件 | 固定版本 | 许可证 | 位置 |
| --- | --- | --- | --- |
| llama.cpp Official | `f955e394bf94e01e5e36186d13c985727e5ef5b5` | MIT | `vendor/llama.cpp-official/` |
| llama.cpp AMD 派生实现 | 同一 revision | 上游 MIT 条款继续适用 | `vendor/llama.cpp-amd/` |
| stable-diffusion.cpp | `833369da848e8e2f960fe1896a825e3a08ef9733` | MIT | `vendor/stable-diffusion.cpp/` |
| libwebm | 随固定源码树 | BSD 3-Clause | stable-diffusion.cpp 子模块 |
| libwebp | 随固定源码树 | BSD 3-Clause | stable-diffusion.cpp 子模块 |

### 运行时模型

| 用途 | 模型 | 许可边界 |
| --- | --- | --- |
| Chat | SC117/Qwen3.6-35B-A3B APEX GGUF | 当前模型卡声明 Apache-2.0；需独立核验基础模型与派生谱系 |
| Embedding | BAAI/bge-m3 | MIT |
| Image | FLUX.1-dev | Non-Commercial License |
| FLUX GGUF | city96/FLUX.1-dev-gguf | 继续受 FLUX.1-dev 上游许可约束 |

模型由部署脚本下载，不属于仓库源码。完整第三方说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 详细文档

| 文档 | 内容 |
| --- | --- |
| [项目说明](project-documentation/ProjectOverview.zh-CN.md) | 比赛定位、架构、模型、能力与优化总览 |
| [应用场景](project-documentation/ApplicationScenarios.zh-CN.md) | 协作助手与金融研究示例 |
| [Agent 架构](project-documentation/AgentArchitecture.zh-CN.md) | AgentPackage、RuntimeKernel、工具网关与隔离边界 |
| [核心能力](project-documentation/CoreCapabilities.zh-CN.md) | 模型、工具、记忆、知识、调度和交付 |
| [部署与验收](project-documentation/Deployment.zh-CN.md) | SSH、本机部署、模型准备、实例迁移、排障与验收 |
| [AMD 推理优化](project-documentation/performance/ROCmOptimizations.zh-CN.md) | HIP Kernel、成对测试、算子证据与适用边界 |
| [补充材料](SUPPLEMENTARY_MATERIALS.zh-CN.md) | 海报、演示与比赛材料索引 |
