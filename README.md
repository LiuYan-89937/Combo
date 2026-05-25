# FastAgentFactory

FastAgentFactory 是一个 CLI-first 的 Agent 工厂。它把自然语言需求整理成可编译、可运行、可测试、可扩展的 AgentPackage，并让工厂自身与生产出来的 Agent 尽量使用同一套运行规范。

项目的核心目标：

- 用阶段化流程把需求转成 AgentPackage。
- 用 RuntimeKernel 编译和运行 AgentPackage。
- 用 RuntimeContracts 统一工具、记忆、知识、上下文、定时任务、Trace、Sandbox 等基础能力。
- 用 TypeScript CLI 渲染工厂和子 Agent 的同一套事件流。
- 让生成 Agent 默认在 Docker sandbox 中运行，避免宿主机环境污染。

## 架构概览

```text
User
  -> TypeScript CLI
  -> Python JSONL Bridge
  -> SystemPackage / AgentPackage
  -> RuntimeContracts
  -> RuntimeKernel
  -> Tools / Memory / Knowledge / Scheduler / Context / Trace
  -> Runtime Events
  -> CLI Render
```

工厂本身也是 SystemPackage：

```text
SystemPackage/factory_chat
SystemPackage/factory_create_agent
```

生产出来的 Agent 是普通 AgentPackage，默认放在：

```text
.agentfactory/packages/<factory_run_id>/
```

## 环境要求

- Python 3.11+
- Node.js / pnpm
- uv
- Docker Desktop 或可用 Docker daemon
- OpenAI-compatible Chat Completions 模型服务
- 可选：OpenAI-compatible embedding 模型服务

## 安装

安装 Python 依赖：

```bash
uv sync
```

安装 CLI 依赖：

```bash
pnpm --dir cli install
```

创建本地配置：

```bash
cp .env.example .env
```

## 基础配置

至少需要填写主模型：

```bash
AGENTFACTORY_OPENAI_BASE_URL=
AGENTFACTORY_OPENAI_API_KEY=
AGENTFACTORY_OPENAI_MODEL=
```

建议同时配置小任务模型、压缩模型和 embedding 模型：

```bash
AGENTFACTORY_TASK_MODEL=

AGENTFACTORY_COMPRESSION_BASE_URL=
AGENTFACTORY_COMPRESSION_API_KEY=
AGENTFACTORY_COMPRESSION_MODEL=

AGENTFACTORY_EMBEDDING_BASE_URL=
AGENTFACTORY_EMBEDDING_API_KEY=
AGENTFACTORY_EMBEDDING_MODEL=
AGENTFACTORY_EMBEDDING_DIMS=1536
```

常用运行配置：

```bash
AGENTFACTORY_SESSION_ROOT=.agentfactory/sessions
AGENTFACTORY_CHECKPOINTER_BACKEND=sqlite
AGENTFACTORY_CHECKPOINT_PATH=.agentfactory/checkpoints/factory.sqlite

AGENTFACTORY_MEMORY_STORE_BACKEND=sqlite
AGENTFACTORY_MEMORY_STORE_PATH=.agentfactory/memory/factory.sqlite
AGENTFACTORY_MEMORY_WRITE_INTERVAL_TURNS=3

AGENTFACTORY_TOOL_MAX_REVISIONS=5
AGENTFACTORY_TOOL_OUTPUT_MAX_MODEL_CHARS=12000

AGENTFACTORY_AGENT_RUNTIME_IDLE_TIMEOUT_SECONDS=1800
AGENTFACTORY_AGENT_RUNTIME_REQUEST_TIMEOUT_SECONDS=900
```

完整配置以 [.env.example](/Users/liuyan/Desktop/FastAgentFactory/.env.example) 为准。

## 启动

从仓库根目录启动 CLI：

```bash
pnpm factory
```

等价于：

```bash
pnpm --dir cli factory
```

CLI 会自动启动 Python bridge：

```bash
python -m agent_factory.factory_graph.frontend_bridge.stdio_server
```

正常使用时不需要手动启动 bridge。

## CLI 常用命令

```text
/chat
/create-agent
/run-agent-package
/agent-sessions
/sessions
/new-session
/resume <session_id>
/tools
/stages
/state on|off
/messages on|off
/tool-grep <query|off>
/stop <stage_id|off>
/exit
/quit
/help
```

说明：

- `/chat`：进入工厂自由对话模式，可用于测试工具、记忆、知识库、定时任务等基础能力。
- `/create-agent`：进入 Agent 生产流程。
- `/run-agent-package`：扫描 `.agentfactory/packages`，选择已生产 AgentPackage 并运行。
- `/agent-sessions`：选择当前 AgentPackage 的会话。
- `/sessions`：选择工厂会话。
- `/stop <stage_id|off>`：设置或关闭生产流程阶段断点。
- `/tool-grep <query|off>`：过滤工具活动展示。

## Agent 生产流程

`/create-agent` 会运行工厂的十阶段生产流程：

| # | stage_id | 职责 |
| --- | --- | --- |
| 1 | `requirement_capture` | 捕获需求、澄清边界、形成用户确认过的制造计划。 |
| 2 | `runtime_pattern_selection` | 选择 RuntimeKernel pattern。 |
| 3 | `graph_behavior_planning` | 规划节点职责、路由和运行行为。 |
| 4 | `node_strategy_planning` | 规划节点 wrapper、上下文、记忆、policy、tool visibility。 |
| 5 | `tool_capability_planning` | 规划工具能力契约和节点工具可见性。 |
| 6 | `resource_and_condition_planning` | 准备资源键值、sandbox contract 和资源报告。 |
| 7 | `assembly_spec_generation` | 冻结 AssemblySpec、PackageMaterializationPlan、RenderManifest。 |
| 8 | `package_generation` | 物化 AgentPackage、contracts、工具代码草稿和 package report。 |
| 9 | `harness_generation_and_test` | 生成并执行 package validation harness。 |
| 10 | `repair_or_finalize` | 返厂维修或最终出厂。 |

默认阶段断点可通过 `/stop <stage_id|off>` 调整。

## AgentPackage 结构

一个 AgentPackage 的主要文件：

```text
agent_package.json
assembly_spec.json
resources.json
sandbox_contract.json
render_manifest.json
package_report.json
contracts/
bindings/
prompts/
tools/
policies/
strategies/
formatters/
```

`agent_package.json` 只负责索引文件。运行能力由 `contracts/*.json` 声明，再由系统 Builder 注入 RuntimeKernel。

当前 AgentPackage 必须声明的 RuntimeContracts：

```text
artifact
context
dependencies
knowledge
model
node_provider
render
resources
sandbox
scheduler
session
state
tools
trace
```

原则：

- `AssemblySpec` 只描述 Agent 逻辑装配。
- Runtime 基础设施不写进 `AssemblySpec.metadata`。
- JSON 里不能声明自定义 Builder import path。
- Builder 只能由系统注册。
- 新增基础能力必须通过 contract、builder、contribution、package materialization 和编译校验接入。

## 子 Agent Docker 运行

普通 AgentPackage 默认通过 Docker sandbox 运行：

```text
AgentPackage
  -> agentfactory-runtime-python:3.12
  -> sandbox init
  -> agent_runtime_bridge
  -> RuntimeKernel compile/run
  -> JSONL events
  -> CLI render
```

构建 runtime image：

```bash
docker build -t agentfactory-runtime-python:3.12 -f docker/agent-runtime/Dockerfile .
```

如果 Docker Hub 拉取基础镜像超时，可以指定镜像源：

```bash
docker build -t agentfactory-runtime-python:3.12 \
  --build-arg PYTHON_BASE_IMAGE=<python-3.12-slim-mirror> \
  -f docker/agent-runtime/Dockerfile .
```

sandbox 挂载约定：

```text
/package                  read-only   AgentPackage
/resources/resources.json  read-only   resources.json
/artifacts                read-write  日志、报告、输出文件
/workdir                  read-write  临时工作区
/runtime                  read-write  session/checkpoint/memory/extensions/knowledge/trace
/runtime/extensions        read-write  用户后配置 MCP/Skill/扩展工具
/runtime/knowledge         read-write  用户后配置知识库
/volumes/*                configurable sandbox contract 授权挂载
```

Docker preflight 会检查：

- Docker CLI 是否存在。
- Docker daemon 是否可用。
- runtime image 是否存在。
- mounts / volumes / secrets / network 是否能按 sandbox contract 转成容器参数。

## 基础能力

### 工具系统

统一链路：

```text
ToolProvider
  -> ToolSpec
  -> ToolRegistry
  -> ToolCompiler
  -> ToolExecutionGateway
  -> LangGraph ToolNode
  -> ToolMessage / Observation
```

内置基础工具分组：

```text
filesystem:
  read
  write
  edit
  multi_edit
  glob
  grep
  ls

process:
  bash
  bash_status
  bash_stop

system:
  scheduler
  knowledge
  skill
  tool_output

network:
  web_fetch
  web_search
```

工具规则：

- 工具 manifest 使用统一 `ToolSpec`。
- 工具入口统一为 `run(arguments: dict, resources: dict) -> dict`。
- 风险评估入口统一为 `evaluate_risk(arguments: dict, context: dict) -> dict`。
- 参数先过 JSON Schema，再过风险策略，再执行 entrypoint。
- 工具分低、中、高风险；中高风险可触发审批。
- 长输出由 Gateway 归档完整结果，并把压缩预览写回模型。
- 模型可用 `tool_output` 按引用读取完整工具输出。

### Skill 与 MCP

- Skill 通过系统内置 `skill` 工具递进式披露。
- MCP 通过 provider 编译成统一 ToolSpec。
- 生成 Agent 不把用户本机 MCP/Skill 写死进 package。
- 用户后配置入口统一为 `/runtime/extensions`。

### 记忆系统

会话内记忆：

```text
LangGraph messages channel
  + checkpointer
  + thread_id
```

跨会话记忆：

```text
LangGraph BaseStore compatible store
  + namespace
  + background write jobs
  + retrieval / ranking / injection
```

Factory 与子 Agent 的 session、checkpoint、store 目录隔离。跨会话记忆写入不阻塞主对话。

### 知识系统

知识库通过系统工具 `knowledge` 管理和检索，不默认每轮自动召回。

支持的 source 类型：

```text
filesystem
codebase
web_snapshot
database
mcp
skill
artifact_report
manual_note
```

支持两种模式：

- `index_only`：catalog + SQLite FTS。
- `rag`：chunk + embedding + LangGraph BaseStore semantic search。

子 Agent 知识根目录映射到：

```text
/runtime/knowledge
```

### 上下文系统

ContextSystem 负责三件事：

- 同步阻断式压缩当前会话 messages。
- 从 ContextSource 检索候选上下文。
- 在 cognitive 节点调用模型前组装临时上下文。

上下文注入不写入 checkpoint messages；压缩后的摘要会进入 messages，并保持 tool call / ToolMessage 配对完整。

### 定时任务系统

SchedulerSystem 使用：

- SQLite job store 作为事实源。
- APScheduler 作为时间触发引擎。
- ToolExecutionGateway 执行 script/tool。
- RuntimeKernel 执行 graph_run。

任务类型：

```text
graph_run
script_run
tool_call
```

触发类型：

```text
cron
interval
date
```

### Trace 系统

TraceSystem 使用 JSONL Trace Fact Store。

每次运行写入：

```text
/runtime/trace/runs/<trace_id>/manifest.json
/runtime/trace/runs/<trace_id>/trace.jsonl
/runtime/trace/runs/<trace_id>/refs.jsonl
```

RuntimeKernel 会记录：

- run started / completed / failed
- node span started / finished
- model call span started / finished
- tool/context/memory/render/subgraph 相关事件

Trace 是持久事实源；CLI 实时渲染仍消费 runtime events。

## 运行产物目录

```text
.agentfactory/
  sessions/
  checkpoints/
  memory/
  scheduler/
  resources/
  assemblies/
  packages/
  harness/
  agent_runtime/
```

`.agentfactory/` 是本地运行产物目录，不进入 Git。

## 验证

本项目不要求自行跑特化业务示例。常规改动优先使用语法、静态和非业务测试。

Python 语法检查：

```bash
python3 -m compileall -q agent_factory tests
```

TypeScript：

```bash
pnpm --dir cli typecheck
pnpm --dir cli lint
pnpm --dir cli test
```

静态检查：

```bash
git diff --check
```

## 未完成边界

- 第十阶段 `repair_or_finalize` 还需要完成真实返厂维修与最终出厂流程。
- `/rerun <stage_id>` 需要基于持久 bookmark/checkpoint 完整恢复。
- `graph_run` 当前只向主链路 Graph 投递消息；动态 GraphPattern 选择仍需补齐。
- Web UI 还未实现；当前以 CLI-first 为准。
- Trace reader / projection / 可视化分析层还需要继续完善。

## 参考文档

- [docs/basic_capability_construction.md](/Users/liuyan/Desktop/FastAgentFactory/docs/basic_capability_construction.md)：基础能力系统与 Contract/Builder 规范。
- [docs/runtime_render_pipeline.md](/Users/liuyan/Desktop/FastAgentFactory/docs/runtime_render_pipeline.md)：Factory 与生成 Agent 共用渲染管线。
- [docs/trace_system_engineering.md](/Users/liuyan/Desktop/FastAgentFactory/docs/trace_system_engineering.md)：Trace 系统工程设计。
- [docs/factory_runtime_kernel_stages.md](/Users/liuyan/Desktop/FastAgentFactory/docs/factory_runtime_kernel_stages.md)：Factory 十阶段设计说明。
