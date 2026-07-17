# FastAgentFactory 部署与验收指南

本文档是 `AMD-Hackson` 分支的正式部署说明，面向比赛交付、复现和现场验收。部署形态固定为：

- 本机运行 FastAgentFactory Web、Agent 工作流和 Docker Agent Runtime。
- RadeonCloud 运行 AMD ROCm 推理节点、llama.cpp Chat 和 PyTorch HIP Embedding。
- 本机通过 SSH 隧道访问远端三个回环端口。

项目入口和功能说明见 [README](../README.md)。

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
| 远端 | llama-server ROCm | `127.0.0.1:8003` |
| 远端 | Embedding 服务 | `127.0.0.1:8002` |
| 远端 | 推理控制与遥测 | `127.0.0.1:8004` |
| 远端 | 最小推理 bundle | `/root/FastAgentFactory` |
| 远端 | 两套 llama.cpp 源码 | `/root/fastagentfactory-llama-sources` |
| 远端 | 两套构建与活动入口 | `/root/.fastagentfactory/llama` |
| 远端 | stable-diffusion.cpp 完整 Git 源码与子模块 | `/root/stable-diffusion.cpp` |
| 远端 | 模型文件 | `/root/models` |
| 远端 | 推理状态与日志 | `/root/.fastagentfactory` |

远端路径均可在 `deploy/deploy.env` 修改。若 RadeonCloud 提供持久卷，应优先改到持久卷挂载点。

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
- SSH 私钥或 ssh-agent 可以登录 RadeonCloud
- 本机端口 `3000`、`8000`、`18002`、`18003`、`18004` 未被占用

Docker 仅用于本机 AgentPackage、MCP 和子 Agent 隔离，不承载远端模型推理。

### 2.2 RadeonCloud 要求

推荐工作空间：

| 设置 | 推荐值 |
| --- | --- |
| Image | `amd-oneclick-base:rocm7.2.1-py3.12-v20260416` |
| Deploy Type | Notebook（Jupyter / OpenCode） |
| GitHub Repo URL | 留空 |
| Notebook Path | 留空 |
| SSH Access | 开启 |

SSH 登录必须使用平台 Profile 中配置的 Public Key。平台提供的 Host 或 NodePort 变化后，需要同步修改本机部署配置。

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

部署前应通过 RadeonCloud 控制台或 `df -h` 确认模型目录所在文件系统空间充足。

## 3. 获取代码

在本机执行：

```bash
git clone -b AMD-Hackson https://github.com/LiuYan-89937/FastAgentFactory.git
cd FastAgentFactory
git status
git log -1 --oneline
```

已有工作树执行：

```bash
git switch AMD-Hackson
git pull --ff-only origin AMD-Hackson
```

部署脚本会从本机同步当前工作树到 RadeonCloud，不需要在服务器上手动 Clone 项目。

## 4. 配置 SSH 与部署参数

创建私有配置：

```bash
cp deploy/deploy.env.example deploy/deploy.env
```

首次部署只需要填写 SSH：

```dotenv
SSH_HOST=<RadeonCloud-IP>
SSH_PORT=<RadeonCloud-SSH-Port>
SSH_USER=root
SSH_KEY=
```

`SSH_KEY` 的行为：

- 留空：由 ssh-agent 或 OpenSSH 自动选择私钥；
- 填写：使用绝对路径或 `~/.ssh/...` 指定私钥；
- 不允许填写密码，脚本只支持 Key 登录。

### 4.1 主要配置字段

| 字段 | 含义 | 默认策略 |
| --- | --- | --- |
| `REMOTE_PROJECT_ROOT` | 远端最小推理 bundle 目录 | `/root/FastAgentFactory` |
| `REMOTE_STATE_ROOT` | venv、模型池、PID、日志 | `/root/.fastagentfactory` |
| `REMOTE_MODEL_ROOT` | 模型根目录 | `/root/models` |
| `REMOTE_LLAMA_SOURCE_ROOT` | 远端两套 llama.cpp 源码根目录 | `/root/fastagentfactory-llama-sources` |
| `REMOTE_LLAMA_RUNTIME_ROOT` | 两套构建、清单和活动软链接 | `/root/.fastagentfactory/llama` |
| `LOCAL_LLAMA_OFFICIAL_DIR` | 仓库内官方 Baseline 源码 | `vendor/llama.cpp-official` |
| `LOCAL_LLAMA_AMD_DIR` | 仓库内 AMD 优化源码 | `vendor/llama.cpp-amd` |
| `REMOTE_STABLE_DIFFUSION_CPP_DIR` | 远端 stable-diffusion.cpp 源码与构建 | `/root/stable-diffusion.cpp` |
| `STABLE_DIFFUSION_CPP_REPOSITORY` | 远端获取图片推理源码的 Git 仓库 | stable-diffusion.cpp 官方仓库 |
| `STABLE_DIFFUSION_CPP_REVISION` | 远端图片推理源码 revision | 固定 Commit SHA |
| `LLAMA_OFFICIAL_REVISION` | 官方 Baseline 来源 revision | 固定 Commit SHA |
| `LLAMA_OFFICIAL_BUILD_NUMBER` | 官方 Baseline 的上游构建序号 | 与固定 revision 对应的提交计数 |
| `LLAMA_AMD_BASE_REVISION` | AMD 版本基于的官方 revision | 与 Baseline 对齐 |
| `LLAMA_AMD_BASE_BUILD_NUMBER` | AMD 版本基线的上游构建序号 | 与 Baseline 对齐 |
| `LLAMA_DEFAULT_IMPLEMENTATION` | 一键部署后激活的实现 | `amd` |
| `PYPI_INDEX_URL` | 远端 Python 依赖源 | 清华 PyPI |
| `HF_ENDPOINT` | GGUF 下载源 | Hugging Face 国内镜像 |
| `CHAT_MODEL_*` | Chat GGUF 版本、文件、大小和 SHA256 | 固定并校验 |
| `CHAT_MMPROJ_*` | 视觉投影器版本、大小和 SHA256 | 固定并校验 |
| `EMBEDDING_MODEL_ID` | Embedding 模型 | `BAAI/bge-m3` |
| `IMAGE_*_URL/SHA256/SIZE_BYTES` | FLUX 四件套 ModelScope 国内直链与完整性信息 | 固定并校验 |
| `IMAGE_RESIDENCY_POLICY` | Chat 与 Image 显存共存策略 | `coexist_if_fit` |
| `IMAGE_EAGER_LOAD` | sd-server 启动时立即把图片模型参数加载到配置的计算后端 | `1` |
| `CHAT_CONTEXT_SIZE` | llama-server Context | `256000` |
| `CHAT_CACHE_TYPE_K/V` | KV Cache 类型 | `q8_0` |
| `CHAT_PARALLEL_SLOTS` | Chat 并发槽位 | `1` |
| `CHAT_FLASH_ATTENTION` | Flash Attention | `1`，开启 |
| `AGENTFACTORY_COLLABORATION_EVENT_COALESCE_WINDOW_SECONDS` | 子 Agent 事件触发主 Agent 恢复前的短聚合窗口 | `0.75` 秒 |
| `AGENTFACTORY_COLLABORATION_EVENT_BATCH_LIMIT` | 单次主 Agent 恢复最多合并的原始事件数 | `64` |
| `TAVILY_API_KEY` | 内置 `web_search` 的 Tavily Provider 密钥；只配置在本机 `.env`，由 MCP 子进程继承 | 留空时回退到 SearXNG/DuckDuckGo |
| `REMOTE_INSTALL_BUILD_TOOLS` | 缺少普通工具时允许 apt 安装 | `1` |
| `REMOTE_CA_BUNDLE` | Git、curl、pip 和 ModelScope 共用的远端 CA bundle | `/etc/ssl/certs/ca-certificates.crt` |
| `REMOTE_REPAIR_CA_TRUST` | 证书链缺失或损坏时允许重建并按需重装 `ca-certificates` | `1` |
| `REMOTE_INSTALL_ROCM_USERSPACE` | 缺失时安装 ROCm 用户态探查与 HIP 构建组件 | `1` |
| `ROCM_USERSPACE_PACKAGES` | 镜像对应的 ROCm 用户态包列表 | `rocminfo rocm-hip-sdk` |
| `REMOTE_INSTALL_PYTORCH` | 缺失时允许安装配置指定的 PyTorch HIP | `1` |
| `PYTORCH_RUNTIME_PYTHON` | 镜像预装 HIP PyTorch 的 Python；以 `.pth` 接入项目 venv | `/opt/venv/bin/python` |
| `REMOTE_INFERENCE_PYTHON_PACKAGES` | 远端推理节点最小依赖，不安装主项目 | FastAPI、HTTP、模型加载和 GGUF 解析依赖 |
| `PYTORCH_INDEX_URL` | 预装运行时不可用时的 PyTorch HIP wheel 后备源 | 官方 ROCm 7.2 wheel 源 |
| `PYTORCH_PACKAGES` | 相互匹配的 Torch、TorchVision 与 TorchAudio 发布组 | ROCm 7.2 的 2.11/0.26/2.11 |

协作调度器会读取 llama-server 的 `/slots` 与 `/metrics`，按实际空闲槽位、排队请求以及所有协作会话中正在运行的 worker 统一背压。遥测暂时不可用时，调度器使用当前已启用推理 Profile 的 `parallel_slots` 作为容量依据，不会回退到固定并发数。若需要主动限制协作 worker 数量，可在本机 `.env` 设置 `AGENTFACTORY_COLLABORATION_MAX_PARALLEL_WORKERS`；留空时自动跟随推理服务槽位。

多个 worker 几乎同时提交、阻塞、失败或取消时，每条协作事件仍会独立写入审计表；服务在 `AGENTFACTORY_COLLABORATION_EVENT_COALESCE_WINDOW_SECONDS` 指定的短窗口后，将当时待处理的事件批量领取并只恢复一次主 Agent。批次中的每条事件独立累计 attempts，并在同一事务中统一完成或失败。`AGENTFACTORY_COLLABORATION_EVENT_BATCH_LIMIT` 用于限制一次恢复输入的事件数量，超过限制的事件会进入后续批次。

部署脚本先探查并复用现有 ROCm 与 PyTorch HIP。比赛镜像的 PyTorch 位于 `/opt/venv`，脚本会校验 Python ABI、HIP 和 GPU 可用性，再通过 `.pth` 接入项目隔离 venv，不重新下载或替换镜像 Torch。只有预装运行时不可用时才安装后备 wheel。GPU 驱动和 `/dev/kfd` 必须由 RadeonCloud 提供；使用其他 ROCm 版本时，应覆盖预装 Python 路径，或同时覆盖 `PYTORCH_INDEX_URL` 和 `PYTORCH_PACKAGES`。

## 5. 首次一键部署

在项目根目录执行：

```bash
./deploy.sh up
```

脚本按照以下顺序运行：

1. 检查本机 Git、Python、uv、Node、npm、Docker、SSH 与 rsync。
2. 验证 SSH Key 登录和端口配置。
3. 验证仓库自带的 `vendor/llama.cpp-official` 与 `vendor/llama.cpp-amd`；图片推理源码不进入仓库。
4. 上传远端控制脚本，准备缺失的普通编译工具，验证并按需修复系统 CA 信任链。
5. 探查 GPU、显存、磁盘、ROCm 和 PyTorch HIP；仅在缺失时安装 ROCm 用户态组件和配置指定的 PyTorch HIP 包。
6. 同步 FastAgentFactory 当前工作树到远端项目目录。
7. 同步官方与 AMD 两套 llama.cpp 源码并使用独立目录构建两个 ROCm llama-server；远端检出固定 stable-diffusion.cpp revision、递归初始化完整子模块并构建 HIPBLAS sd-server。
8. 从国内镜像断点续传 Chat GGUF 和 mmproj。
9. 校验模型文件大小和 SHA256；损坏的完整文件不会被复用。
10. 从 ModelScope 下载或复用 `BAAI/bge-m3`。
11. 下载并校验 FLUX.1-dev Q4_0、VAE、CLIP-L 与 T5XXL。
12. 幂等创建 Chat、Embedding、Image Generation 的远端本地 Profile 与本机 external Profile。
13. 设置 `main`、`task`、`compression` 和 `embedding` 默认 Profile。
14. 激活 `LLAMA_DEFAULT_IMPLEMENTATION`，启动远端推理节点并等待 Chat 与 Embedding 都进入 `ready`。
15. 生成本机 `.env`；默认建立 SSH 隧道并启动本机前后端，传入 `--no-web` 时跳过此步骤。

首次下载和编译时间取决于网络、磁盘和 Radeon GPU 主机 CPU。终端会直接显示 curl 与 ModelScope 下载进度。

### 5.1 FLUX.1-dev 与 13GB 显存

部署使用 `stable-diffusion.cpp + FLUX.1-dev Q4_0`，四个文件总计约 16.3GB，其中 T5XXL FP16 常驻 CPU 内存。默认参数为单并发、768×768、20 Steps、CFG 1.0、Euler、Diffusion Flash Attention、CLIP/T5 CPU 和 VAE Tiling。

Image Profile 在远端注册为 enabled，供控制节点识别；本机 external Profile 默认 disabled，因此首次启动不会占用显存。图片运行配置默认启用 `eager_load`，`sd-server` 启动后会立即将参数加载到配置的计算后端；默认 `coexist_if_fit` 允许 Chat 与 Image 在显存预算足够时同时驻留。模型工具复用 `main` 的 `image_output` 抽象，只把 `sd-server` 当作调用接口，图片产物由 ArtifactStore 保存到当前 Agent Workspace。

FLUX.1-dev 使用 Non-Commercial License，不等同于 Apache/MIT。比赛演示和提交前应保留模型来源、revision、SHA256 与许可证说明。

### 5.2 幂等与续传

重复运行 `./deploy.sh up` 的行为：

- 已校验的 GGUF 根据大小和 SHA256 标记复用；
- 部分 GGUF 使用 HTTP Range 继续下载；
- ModelScope 复用自身缓存；
- llama.cpp 使用 Ninja 增量构建；
- stable-diffusion.cpp 固定 revision 的 Git 工作树和递归子模块会幂等复用，并使用 Ninja 增量构建；
- 远端会先验证 stable-diffusion.cpp 仓库的 TLS 信任链；仅在 curl 返回证书链错误时重建 CA，DNS、路由或防火墙问题会原样报错；
- Profile 按固定 ID 更新，不重复创建随机记录；
- 本机 `.env` 保留已有 `AGENTFACTORY_RESOURCE_MASTER_KEY`。

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
| `./deploy.sh up` | 幂等部署并启动远端模型、本机 Web 和 SSH 隧道。 |
| `./deploy.sh up --no-web` | 完成远端一键部署，不启动本机前后端。 |
| `./deploy.sh bootstrap` | 部署并启动远端模型，不启动本机 Web。 |
| `./start.sh` | 已部署环境中只启动本机 Web、Docker Runtime 和 SSH 隧道。 |
| `./deploy.sh status` | 查看远端软件、ROCm 和模型运行状态。 |
| `./deploy.sh logs` | 查看远端推理节点最近 200 行日志。 |
| `./deploy.sh restart` | 重启远端推理节点并等待模型 ready。 |
| `./deploy.sh down` | 停止远端推理节点、卸载模型并释放显存。 |
| `./deploy.sh models` | 续传/校验模型并刷新 Profile；运行中会自动重启。 |
| `./deploy.sh sync` | 同步 FastAgentFactory 和本机 llama.cpp 到远端。 |
| `./deploy.sh build-llama [official\|amd\|all]` | 独立增量构建指定实现；默认构建两套。 |
| `./deploy.sh switch-llama <official\|amd>` | 切换实现并用同一 Profile 重载模型。 |
| `./deploy.sh list-llama-builds` | 查看构建清单、SHA256 和活动实现。 |
| `./deploy.sh rollback-llama` | 恢复上一次活动实现。 |

按 `Ctrl+C` 只会停止本机前后端和 SSH 隧道，远端模型继续运行。释放 Radeon GPU 显存必须执行：

```bash
./deploy.sh down
```

## 8. 更新项目

先确认本机工作树：

```bash
git status
git pull --ff-only origin AMD-Hackson
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

远端同步以本机工作树为代码源，只传输 inference node、model pool 及其必要公共模块，并使用 `rsync --delete-excluded` 清除 bundle 中不属于该边界的旧文件。Factory 前后端、制造系统、会话与知识库代码不会上传；远端模型、状态、venv、llama.cpp build 和 stable-diffusion.cpp Git 工作树位于 bundle 之外，不在删除范围内。

## 9. llama.cpp 算子开发与部署

两套源码都属于 FastAgentFactory 黑客松分支。官方目录保持原样，自定义算子只进入 AMD 目录：

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

完成算子实现后再把这些字段改为真实值，并增加 Kernel 命中计数与 rocprofv3 证据。Benchmark 会自动读取活动构建的 source revision、源码摘要、二进制 SHA256 和构建参数，不接受手填实现名称。

## 10. 更换或重建 RadeonCloud 实例

新实例创建后：

1. 开启 SSH Access 并确认 sshd 可用；
2. 更新 `deploy/deploy.env` 的 `SSH_HOST` 与 `SSH_PORT`；
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

- RadeonCloud SSH Access 是否开启；
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

保存已加载 Profile 会将配置透传到 RadeonCloud 并重启相应模型。

### 11.6 Docker 不可用

启动本机 Docker Desktop 或 Docker Engine，再执行：

```bash
./start.sh
```

远端模型服务不依赖 Docker，但 AgentPackage、MCP 和子 Agent 隔离运行依赖本机 Docker。

## 12. 比赛提交证据

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

这些检查验证语法和文件一致性，不替代 RadeonCloud 真机部署验收。
