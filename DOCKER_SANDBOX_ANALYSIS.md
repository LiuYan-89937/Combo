# FastAgentFactory Docker 沙箱与环境隔离分析

**分析日期**: 2026-07-25  
**目标**: 探明当前 Docker 使用情况、子 Agent 环境隔离、依赖池机制，为跨平台改造做准备

---

## 一、整体架构概览

FastAgentFactory 是一个 **Web 前后端 + Docker 沙箱运行时** 的混合架构：

```
┌─────────────────────────────────────────────────────────────────┐
│                        Web 前端 (Vue 3)                          │
│                      localhost:3000                              │
└────────────────────────┬────────────────────────────────────────┘
                         │ HTTP/SSE
┌────────────────────────▼────────────────────────────────────────┐
│                   Web 后端 (FastAPI)                             │
│                      localhost:8000                              │
│  - event_api_server.py                                           │
│  - RuntimeBridge: 管理运行时事件流                                │
│  - FactoryRuntimeAdapter: 协调 Agent 生命周期                     │
└────────────────────────┬────────────────────────────────────────┘
                         │
        ┌────────────────┴────────────────┐
        │                                 │
┌───────▼──────────────┐       ┌──────────▼──────────────────┐
│  SystemPackage       │       │  AgentPackage               │
│  (进程内运行)         │       │  (Docker 容器隔离)           │
│  - factory_chat      │       │  - 用户制造的 Agent          │
│  - 内置 Agent        │       │  - 独立沙箱环境              │
│  PackageRuntimeCore  │       │  stdio_server.py (桥接)      │
└──────────────────────┘       └─────────────────────────────┘
```

---

## 二、Docker 使用情况详解

### 2.1 运行时镜像

**基础镜像构建**:
- **Dockerfile 位置**: `docker/agent-runtime/Dockerfile`
- **默认镜像名**: `agentfactory-runtime-python:3.12`
- **基础镜像**: `python:3.12-slim`
- **启动检查**: `start.sh` → `web_ensure_runtime_image()` 自动构建

**镜像内容**:
```dockerfile
# 系统依赖
- bash, curl, findutils, grep, awk
- nodejs, npm
- procps, ca-certificates

# Python 依赖管理
- uv (依赖锁定和安装)
- pyproject.toml + uv.lock (从 host 复制)
- agent_factory 包 (以编辑模式安装)

# 入口点
CMD ["python", "-m", "agent_factory.agent_runtime_bridge.stdio_server"]
```

### 2.2 容器启动机制

**启动流程** (host 端):
1. `DockerAgentRuntimeLauncher.prepare()` 构建 docker run 命令
2. `AgentRuntimeContainerHandle` 使用 `subprocess.Popen()` 启动容器
3. 容器以 **stdin/stdout 作为 JSON-RPC 通信管道**
4. 等待 `runtime_ready` 事件 (30秒超时)

**关键代码路径**:
```python
# 文件: agent_factory/factory_graph/frontend_bridge/agent_runtime_launcher.py
DockerAgentRuntimeLauncher.prepare()
  → 构建 docker run 命令
  → 挂载卷:
    - /package (AgentPackage 目录, ro)
    - /artifacts (运行产物, rw)
    - /workdir (工作区, rw)
    - /runtime (运行时状态, rw)
    - /dependency_pool (共享依赖池, ro)
    - /collaboration (协作工作区, rw)

# 文件: agent_factory/factory_graph/frontend_bridge/container_runtime_handle.py
AgentRuntimeContainerHandle.__init__()
  → subprocess.Popen(command, stdin=PIPE, stdout=PIPE)
  → _read_stdout() 线程持续读取容器输出
  → send(command) 通过 stdin 发送 JSON 命令
```

### 2.3 两种隔离模式

系统支持两种容器隔离策略 (通过 `AGENTFACTORY_CONTAINER_ISOLATION` 环境变量控制):

#### 模式 1: **logical** (逻辑隔离, 默认)
- **共享一个长期运行的容器** (`_SharedDockerRuntime`)
- 每个 AgentPackage 通过 `docker exec -i` 在共享容器中启动独立的 stdio_server 进程
- 优点: 启动快速, 资源占用低
- 限制: 所有 Package 必须使用相同的基础镜像和网络配置

**共享容器启动命令**:
```bash
docker run --rm -d \
  --network host \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --label agentfactory.runtime.isolation=logical \
  -v <project>:/agentfactory/project:ro \
  -v <runtime_parent>:<runtime_mount>:rw \
  -v <collaboration_root>:<collaboration_mount>:rw \
  -v <dependency_pool>:/dependency_pool:ro \
  <image> python -m agent_factory.agent_runtime_bridge.container_keeper
```

**Agent 运行命令** (在共享容器内):
```bash
docker exec -i -w /workdir \
  -e <各种环境变量> \
  <container_id> python -m agent_factory.agent_runtime_bridge.stdio_server
```

#### 模式 2: **dedicated** (专用隔离)
- 每个 AgentPackage 实例启动独立容器
- 完全隔离, 支持不同镜像和自定义挂载
- 适用于有特殊依赖或安全要求的场景

**专用容器启动命令**:
```bash
docker run --rm -i \
  --network host \
  --add-host host.docker.internal:host-gateway \
  --label agentfactory.runtime.managed=true \
  --label agentfactory.runtime.project=<project_path> \
  -v <package_root>:/package:ro \
  -v <artifacts>:/artifacts:rw \
  -v <workdir>:/workdir:rw \
  -v <runtime>:/runtime:rw \
  -v <collaboration>:/collaboration:rw \
  -v <dependency_pool>:/dependency_pool:ro \
  -e <环境变量> \
  <image> python -m agent_factory.agent_runtime_bridge.stdio_server
```

### 2.4 容器生命周期管理

**启动**:
- `AgentPackageRuntimeManager._ensure_container()` 懒初始化
- 首次运行消息时才启动容器

**空闲超时** (默认 1800 秒):
- `AgentRuntimeContainerHandle` 维护 `last_used` 时间戳
- 空闲超时后自动发送 `shutdown` 命令并关闭容器

**清理**:
- `start.sh` 的 `cleanup()` trap 会调用 `web_stop_managed_runtime_containers()`
- 通过 label 过滤停止所有托管容器

---

## 三、依赖池 (Dependency Pool) 架构

### 3.1 设计理念

**内容寻址 + 共享缓存**:
- 所有 AgentPackage 的依赖通过指纹 (fingerprint) 去重
- 依赖池位于 host 的 `.agentfactory/dependency_pool/`
- 容器以只读方式挂载到 `/dependency_pool`

**存储结构**:
```
.agentfactory/dependency_pool/
├── .pool.lock                    # 全局锁文件
├── profiles/                     # 依赖配置档案
│   └── <profile_key>.json        # 包含 python/system/npm entries
├── python/
│   ├── download_cache/           # pip 下载缓存
│   └── <hash>/
│       ├── wheels/               # wheel 包
│       └── site-packages/        # 解压后的包
├── system/
│   └── <hash>/
│       └── <package>.deb         # Debian 包缓存
├── npm/
│   └── <hash>/
│       └── node_modules/         # npm 包
└── runtime_compatibility/
    └── <cache_key>.json          # 运行时兼容性探测结果
```

### 3.2 依赖解析流程

**阶段 1: 环境锁定** (`EnvironmentResolver`):
```python
# 文件: agent_factory/environment_system/service.py
EnvironmentResolver.ensure(package_root)
  → 读取 package.dependencies.json 契约
  → 计算依赖请求指纹 (base_image + architecture + requirements)
  → 检查 environment.lock.json 是否可复用
  → 调用 DependencyPool.resolve() 解析依赖
  → 写入 environment.lock.json (包含 pool 引用)
```

**阶段 2: 依赖构建** (`DependencyPool`):
```python
# 文件: agent_factory/environment_system/pool.py
DependencyPool.resolve()
  → _resolve_python(): 
    - docker run <base_image> python -m pip wheel ...
    - 输出到 staging/wheels/
    - 解析 wheel 元数据, 计算哈希
    - 移动到 pool/python/<hash>/
  → _resolve_system():
    - docker run <base_image> apt-get download ...
    - 缓存 .deb 到 pool/system/<hash>/
  → _resolve_npm():
    - docker run <base_image> npm install ...
    - 缓存到 pool/npm/<hash>/
  → 返回 DependencyPoolResolution (包含所有 entry 路径)
```

**阶段 3: 运行时激活** (容器内):
```python
# 文件: agent_factory/environment_system/runtime.py
activate_runtime_dependencies()
  → 读取 /package/environment.lock.json
  → 将 pool/python/<hash>/site-packages 添加到 PYTHONPATH
  → 将 pool/npm/<hash>/node_modules 添加到 NODE_PATH
  → apt-get install --no-download <pool/system/<hash>/*.deb>
  → 验证二进制文件和命令可用性
```

### 3.3 多 Agent 依赖共享

- **场景 1**: 两个 Agent 使用相同的 `requests==2.31.0`
  - 只构建一次 wheel
  - 两个 Agent 的 environment.lock 引用同一个 pool entry
  
- **场景 2**: Agent A 升级依赖到 `requests==2.32.0`
  - 构建新 wheel, 新 hash
  - Agent A 和 Agent B 的 lock 引用不同 entry
  - 旧 entry 不会自动删除 (手动清理 pool)

---

## 四、子 Agent 环境隔离

### 4.1 单 Agent 运行时隔离

每个 AgentPackage 实例拥有独立的运行时目录:

**目录结构**:
```
.agentfactory/agent_runtime/<package_id>/
├── artifacts/              # 运行产物
├── workdirs/
│   └── <session_id>/       # 会话工作区
├── checkpoints/            # LangGraph checkpoints
├── sessions/               # 会话状态
├── memory/                 # 长期记忆索引
├── knowledge/              # 知识库索引
├── scheduler/              # 定时任务数据库
├── logs/                   # 运行日志
├── trace/                  # Trace 记录
└── extensions/             # MCP/Skill 扩展
```

**容器挂载隔离**:
- 每个 Package 的 runtime_root 挂载到容器的 `/runtime`
- 容器内只能看到自己的运行时目录
- 工作区文件通过挂载实现持久化

### 4.2 多 Agent 协作时的隔离

**主 Agent 和子 Agent 的关系** (待子 agent 完成后补充):
- 协作工作区: `.agentfactory/collaboration/<collaboration_id>/`
- 子 Agent 是否复用主 Agent 的容器? (待确认)
- 子 Agent 依赖池共享策略? (待确认)

---

## 五、SystemPackage 的特殊处理

**内置 Agent 不使用 Docker**:
- `SystemPackage/factory_chat/` 等内置包直接在 host 进程运行
- 使用 `SystemPackageRuntimeHandle` 而非容器
- 通过 `PackageRuntimeCore` 管理, 共享 host 的 Python 环境
- 优点: 无容器开销, 启动快
- 限制: 与 host 环境耦合, 不适合自定义依赖

**代码路径**:
```python
# 文件: agent_factory/factory_graph/frontend_bridge/system_package_runtime_handle.py
SystemPackageRuntimeHandle
  → 直接调用 PackageRuntimeCore.handle()
  → 在当前 Python 进程中运行 LangGraph
```

---

## 六、跨平台改造的关键问题

### 6.1 Docker 依赖点

| 功能模块 | Docker 使用方式 | 是否必须 Docker |
|---------|----------------|----------------|
| AgentPackage 运行时 | 容器隔离 | **是** (核心沙箱) |
| 依赖池构建 | `docker run` 临时构建 | **是** (跨平台构建) |
| 运行时镜像校验 | `docker image inspect` | **是** (镜像管理) |
| SystemPackage | 不使用 Docker | 否 |
| Web 前后端 | 不使用 Docker | 否 |

### 6.2 替代方案探讨

**目标平台**: Windows / macOS / Linux

**方案 A: 保持 Docker 依赖**
- 优点: 架构不变, 隔离性最强
- 缺点: 
  - Windows/Mac 需要 Docker Desktop (商业许可问题)
  - 非技术用户安装门槛高
  - 资源占用较大

**方案 B: 虚拟环境隔离 (venv/conda)**
- 为每个 AgentPackage 创建独立 Python 环境
- 依赖池改为本地 virtualenv 缓存
- 问题:
  - 系统包 (apt/brew) 隔离困难
  - 进程隔离弱于容器
  - Windows/Mac/Linux 包管理器不统一

**方案 C: WebAssembly/Pyodide**
- 在浏览器沙箱中运行 Agent
- 问题:
  - 生态不成熟, 很多 Python 包不支持
  - 文件系统访问受限
  - 性能损失较大

**方案 D: 进程隔离 + 动态环境**
- 每个 Agent 独立进程, 动态修改 sys.path
- 依赖池改为本地 wheel 缓存
- 系统依赖通过 host 预装或打包分发
- 问题:
  - 隔离性比容器弱
  - 需要重构依赖池逻辑
  - 多版本 Python 共存问题

### 6.3 建议方案 (分阶段)

**Phase 1: 保留 Docker, 改进体验**
- 检测 Docker 不可用时, 降级到 SystemPackage 模式
- 提供一键安装脚本 (Docker Desktop / Podman / Colima)
- 优化镜像大小和启动速度

**Phase 2: 混合模式**
- 默认使用 Docker (如果可用)
- 提供 `--local` 模式, 使用 venv 隔离
- 限制 local 模式能力 (仅支持纯 Python 依赖)

**Phase 3: Electron/Tauri 桌面应用**
- 将 Web 前后端打包为桌面应用
- 内置轻量级容器运行时 (如 Lima)
- 或使用 Pyodide 作为沙箱

---

## 七、数据流总结

**用户发送消息 → Agent 执行 → 返回结果** 的完整链路:

```
1. Web 前端 (Vue)
   ↓ HTTP POST /api/runtime/send_message
2. FastAPI 后端 (event_api_server.py)
   ↓ RuntimeBridge._execute_command()
3. FactoryRuntimeAdapter
   ↓ 判断是 SystemPackage 还是 AgentPackage
4a. SystemPackage 路径:
    → SystemPackageRuntimeHandle
    → PackageRuntimeCore (进程内)
    → LangGraph.invoke()
4b. AgentPackage 路径:
    → AgentRuntimeContainerHandle.send()
    → JSON 命令通过 stdin 发送到容器
    → 容器内 stdio_server.py 接收
    → BridgeRuntimeState.handle()
    → _ensure_compiled() 编译 LangGraph
    → _run_message() 执行
    → 结果通过 stdout 返回 (JSON 流)
5. RuntimeEventPipeline 处理事件
   ↓ SSE 推送
6. Web 前端接收流式事件, 渲染消息
```

---

## 八、待确认问题 (子 agent 分析中)

以下问题等待子 agent 完成后补充:

1. **多 Agent 协作时的容器复用策略**
   - 子 Agent 是否在独立容器中运行?
   - 协作工作区如何共享?
   
2. **依赖池的完整缓存策略**
   - wheel 文件的 hash 算法细节
   - 依赖更新时的清理机制
   
3. **RuntimeKernel 的执行细节**
   - LangGraph checkpoint 存储格式
   - 会话状态持久化机制

4. **容器内外文件路径映射**
   - workdir 别名机制
   - 跨容器文件引用

---

## 九、附录: 关键文件清单

| 文件路径 | 功能 |
|---------|------|
| `agent_factory/environment_system/pool.py` | 依赖池核心逻辑 |
| `agent_factory/environment_system/runtime.py` | 容器内依赖激活 |
| `agent_factory/factory_graph/frontend_bridge/agent_runtime_launcher.py` | Docker 命令构建 |
| `agent_factory/factory_graph/frontend_bridge/container_runtime_handle.py` | 容器进程管理 |
| `agent_factory/agent_runtime_bridge/stdio_server.py` | 容器内桥接服务 |
| `docker/agent-runtime/Dockerfile` | 运行时镜像定义 |
| `start.sh` | 启动脚本 (镜像构建, 容器清理) |
| `.env.example` | 配置模板 (隔离模式等) |

---

**下一步**: 等待子 agent 完成对 collaboration_system, runtime_kernel, package_runtime 的深入分析后, 补充本文档的待确认部分。
