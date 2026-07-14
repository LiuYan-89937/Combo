# FastAgentFactory

FastAgentFactory 是一个本地优先的 Agent 工厂工作台：从配置本地模型、知识库与工具，到制造、运行、进化和复盘 AgentPackage，都在同一套可观察的 Web 界面中完成。

本分支面向 **AMD AI DevMaster 2026（赛道二）** 的 Radeon GPU + ROCm 部署。对话推理由 llama.cpp ROCm 的 `llama-server` 提供，Embedding 由 PyTorch ROCm + SentenceTransformers 提供；模型文件和 Profile 均保留在本地，不依赖云端模型 API。

![FastAgentFactory 闲聊工作台](readme-assets/images/chat.png)

## 能力边界

| 能力 | 当前实现 |
| --- | --- |
| 本地对话模型 | 已支持。模型池管理 llama.cpp 可加载的本地模型文件，后端按 Profile 启动 `llama-server` ROCm。 |
| 工具调用与流式会话 | 已支持。Agent 运行 trace、工具审批和工作区产物可在 Web 工作台查看。 |
| Embedding、RAG 与记忆 | 已支持。Embedding 服务独立运行在 ROCm PyTorch 环境。 |
| AgentPackage 生命周期 | 已支持制造、发布、运行、进化、工作区、知识库、扩展和协作能力。 |
| GPU 与运行状态 | 已支持在“本地模型”查看 ROCm、PyTorch HIP、已加载 Profile 与模型加载状态。 |
| llama.cpp 模型服务 | 已纳入模型池，可在页面加载、卸载、重启并查看显存与日志。自动扫描覆盖 GGUF，其他本地文件由当前 llama-server 版本决定是否可加载。 |

## 用户使用流程

1. 在 RadeonCloud 或本地 Radeon 主机完成 ROCm 基础环境准备。
2. 下载模型文件到统一模型根目录，不将模型文件提交到 Git。
3. 启动 FastAgentFactory 后端与前端。
4. 进入“本地模型”，扫描模型目录，注册模型 Artifact 和推理 Profile。
5. 为 `main`、`task`、`compression`、`embedding` 指定默认 Profile。
6. 加载一个对话模型和一个 Embedding 模型；确认状态为 ready。
7. 使用“闲聊”验证对话与工具调用，再制造或运行 AgentPackage。

![本地模型池](readme-assets/images/model-pool.png)

## 架构与运行数据

```text
Browser
  │ HTTP + SSE
  ▼
FastAgentFactory Web Backend :8000
  ├─ AgentPackage / RuntimeKernel / tools / trace / workspace
  ├─ Model Pool registry and runtime manager
  ├─ llama-server ROCm :8003/v1 (one active chat profile per GPU slot)
  └─ Embedding ROCm :8002     (one active embedding profile per GPU slot)
```

运行状态默认写入以下目录，均不应提交到 Git：

```text
.agentfactory/     # 模型池 SQLite、知识库、记忆与服务状态
.agent_runtime/    # AgentPackage 工作区、trace、checkpoint 与产物
```

模型文件位置由 `AGENTFACTORY_MODEL_ROOT` 决定。RadeonCloud 建议使用挂载/持久盘目录，例如 `/root/models`，不要放入仓库。

## 环境要求

### 开发机

- Python 3.11+
- Node.js 18+
- npm 与 uv
- Docker Engine（仅 AgentPackage 隔离运行时需要）

### AMD ROCm 推理主机

- 已由镜像提供的 ROCm、PyTorch HIP 和 AMD GPU 驱动
- 对话模型：llama.cpp HIP/ROCm
- Embedding 模型：SentenceTransformers + PyTorch ROCm
- 足够的显存与磁盘空间

不要在部署脚本中升级或重装 ROCm、PyTorch，也不要让脚本隐式下载模型。llama.cpp 使用固定提交构建，确保交付可复现。

## RadeonCloud 部署

推荐工作空间：

- Image：`amd-oneclick-base:rocm7.2.1-py3.12-v20260416`
- Deploy Type：Notebook（Jupyter / OpenCode）
- 开启 SSH Access
- GitHub Repo URL 与 Notebook Path 留空

连接工作空间后，先核验环境；这一步只读取状态，不会修改运行时：

```bash
rocminfo | grep "Marketing Name"
python3 -c 'import torch; print(torch.__version__); print(torch.version.hip); print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0)); print(torch.cuda.get_device_properties(0).total_memory / 1024**3)'
llama-server --version
df -h
```

随后拉取指定分支，并确认远端内容而非假设本地提交已推送：

```bash
git clone -b AMD-Hackson https://github.com/LiuYan-89937/FastAgentFactory.git
cd FastAgentFactory
git status
git log -1 --oneline
```

### 服务器私有配置

```bash
cp .env.example .env
```

`.env` 至少需要保留模型根目录和资源加密密钥：

```dotenv
AGENTFACTORY_MODEL_ROOT=/root/models
AGENTFACTORY_RESOURCE_MASTER_KEY=<stable-long-random-secret>
```

`AGENTFACTORY_RESOURCE_MASTER_KEY` 用于加密已保存的 AgentPackage 运行时资源；更换或丢失后，旧资源无法解密。模型选择、上下文窗口、输出上限、显存策略和工具能力应在“本地模型”的 Profile 中维护，而不是作为日常环境变量配置。

### 启动应用

当前根目录入口适用于本地开发和单机联调：

```bash
./start.sh
```

它会准备 Python/前端依赖、检查 AgentPackage 容器运行时，并启动：

- 前端：`http://<host>:3000`
- 后端：`http://<host>:8000`
- 健康检查：`http://<host>:8000/health`

RadeonCloud 对外访问时，请使用平台暴露的端口或 SSH 隧道，不要将推理端口 `8003`、`8002` 直接暴露到公网。模型服务应只监听回环地址，由后端统一访问。

## 模型池配置

模型池由两层组成：

- **Artifact**：已落盘的模型文件、版本与校验信息。Tokenizer 由 GGUF 或 Embedding 模型目录自身提供，不单独填写路径。
- **Profile**：该模型如何运行，包括 GPU 层数、并发槽位、KV Cache 类型、Flash Attention、上下文窗口、压缩阈值、最大输出及能力声明。

推荐初始组合：

| 角色 | 模型 | 引擎 | 建议 |
| --- | --- | --- | --- |
| Chat | llama.cpp 可加载的本地模型 | `llama_cpp_rocm` | 工具调用开启，按显存设置 GPU 层数、上下文和 KV Cache 类型。 |
| Embedding | `BAAI/bge-m3` | `transformers_rocm` | 设置向量维度与归一化策略。 |

在页面中加载模型后，模型权重会进入显存。卸载或重启模型会释放对应运行时占用；同一 GPU 的聊天槽位一次只应加载一个 Chat Profile。

### 模型下载约定

模型根目录下建议按来源组织：

```text
/root/models/
  modelscope/
  huggingface/
  gguf/
```

Transformers 模型可用项目统一入口下载并扫描：

```bash
python -m agent_factory.model_pool.download <namespace/model-name>
```

下载完成后回到“本地模型”刷新扫描结果，再注册 Artifact 与 Profile。下载前应先确认磁盘容量、模型许可与 SHA256；不要在一键启动脚本中下载大模型。

## Qwen3.6-35B-A3B 说明

当前使用 `APEX-I-Quality.gguf`，由模型池以 `llama_cpp_rocm` Profile 托管。启用 Profile 后，后端启动 `llama-server`；卸载或重启操作直接管理该进程，界面状态与显存占用一致。

## AgentPackage 使用

### 制造与发布

在“Agent 制造”中填写目标、输入边界和交付标准。生成的 AgentPackage 保存模型 `profile_id`、工具权限、知识库和运行契约，不保存模型绝对路径或 GPU 配置。

![Agent 制造](readme-assets/images/agent-authoring.png)

### 运行与复盘

在“已发布 Agent”中初始化运行实例。每个实例拥有独立会话、工作区、知识库、记忆、扩展和 trace。完成后可从工作区查看文件产物，从 trace 复盘模型调用、工具调用与状态流转。

### 知识库、扩展与权限

- 知识库按 `factory_chat`、AgentPackage 和进化会话隔离。
- MCP、Skill 与工具权限按 AgentPackage 单独配置。
- 默认建议低/中风险工具自动放行，高风险工具要求确认。

## 交付版一键启动脚本：必须具备什么

交付脚本不应只是串联几个 `nohup`。它必须成为运行状态的唯一入口，并具备以下契约：

1. **显式命令**：至少提供 `up`、`down`、`restart`、`status`、`logs` 与 `doctor`，而不是只有不可恢复的 `start`。
2. **前置检查**：确认 Git 版本、`.env`、Python/Node 依赖、ROCm/HIP、GPU 可见性、端口可用性、磁盘余量与模型池数据库。
3. **不做隐式变更**：默认不升级 ROCm/PyTorch/llama.cpp、不下载模型、不自动修改 Profile；这些动作必须由单独显式命令完成。
4. **进程可管理**：每个服务都有 PID、日志和健康检查；停止时按进程组终止，避免遗留 llama-server 或 Embedding 服务占用显存。
5. **启动顺序**：后端初始化时恢复模型池中已激活的 llama.cpp Chat 与 Embedding Profile，再启动前端；任一健康检查失败时输出对应日志并退出非零。
6. **边界清晰**：Web 前端/后端、llama-server 与 Embedding 必须有独立端口和日志。
7. **可访问性**：默认仅监听安全地址；对外暴露由 RadeonCloud 端口映射或反向代理处理，而不是脚本开放所有端口。
8. **交付诊断**：`doctor` 输出 GPU 型号、显存、ROCm、PyTorch HIP、llama-server、模型池默认 Profile、运行中模型和剩余磁盘，方便验收留档。

现有 `./start.sh` 可以继续用于开发；交付版脚本应在完成上述进程、日志与健康检查约定后替换为正式入口。

## 常用检查与排障

```bash
# 后端健康检查
curl http://127.0.0.1:8000/health

# 模型池、ROCm 与运行状态
curl http://127.0.0.1:8000/api/model-pool/runtimes

# llama-server OpenAI 模型列表
curl http://127.0.0.1:8003/v1/models

# 当前 AMD GPU 显存占用
rocm-smi --showmemuse --showpids
```

常见问题：

- **扫描不到模型**：检查 `AGENTFACTORY_MODEL_ROOT` 是否指向实际模型根目录，并确认模型文件在该目录下。
- **启用模型后显存未变化**：确认 Profile 已真正处于 loading/ready，而非仅在注册表中 enabled；查看运行状态与服务日志。
- **模型加载失败**：核对 Profile 的 GPU 层数、上下文窗口、KV Cache 类型和当前 llama-server 对模型文件的兼容性；不要先升级基础运行时。
- **工具调用显示为文本**：检查模型 Profile 是否声明工具调用能力，以及推理服务是否返回 OpenAI 结构化 `tool_calls`。
- **网页无法从本机打开**：核对 RadeonCloud 暴露端口或 SSH 隧道；后端健康检查通过不代表前端端口已对外暴露。

## 开发检查

```bash
# Python 语法检查
python3 -m compileall -q agent_factory web_frontend/backend

# Shell 脚本语法检查
bash -n start.sh web_frontend/start_backend.sh

# 前端类型检查
cd web_frontend/frontend && npm run type-check
```

前端构建或类型检查受到本地 Node.js / `vue-tsc` 版本影响时，应先记录实际版本与报错，再决定是否调整工具链；不要把环境问题误报为业务代码通过或失败。
