# FastAgentFactory

FastAgentFactory 是一个 CLI-first 的 Agent 工厂工程。它的目标不是一次性脚本生成，而是把用户需求逐步转成可校验、可编译、可在 sandbox 中运行、可返厂维修的 RuntimeKernel AgentPackage。

当前项目围绕一条统一链路建设：

```text
FactoryGraph 十阶段生产
  -> AgentAssemblySpec
  -> PackageMaterializationPlan
  -> AgentPackageManifest + RuntimeContracts
  -> RuntimeKernel compile
  -> Docker Agent Runtime Bridge
  -> JSONL runtime events
  -> TypeScript CLI render
```

旧 Python CLI 已移除。当前唯一交互入口是 TypeScript CLI。

## 当前进度

已完成并正在使用的主干能力：

- **FactoryGraph**：10 阶段 LangGraph 生产图，已接入标准运行事件、阶段 checkpoint、阶段级 `/rerun <stage_id>`。
- **TypeScript CLI**：Ink/React 前端，使用外部 `RuntimeStore` 和 selector 订阅事件状态，支持 chat、create-agent、agent-package 三种模式。
- **Runtime Bridge**：Python bridge 通过 JSONL over stdio 暴露标准事件与命令，CLI/WebUI 不再解析 LangGraph 原始 patch 作为主数据源。
- **统一工具系统**：Factory、生成 Agent、Package 工具、MCP、Skill 共用 `ToolSpec -> ToolRegistry -> ToolCompiler -> ToolExecutionGateway -> ToolNode`。
- **工具审批与风险策略**：工具分低/中/高风险，参数 schema 校验、硬规则风险校验、可选 llmRisk 和人工审批统一收口在 Gateway。
- **Skill 系统**：采用递进式披露，模型先通过内置 `skill` 工具读取 metadata，再按需 load `SKILL.md` 或 resource；脚本执行仍走 `bash` 与审批。
- **MCP 接入**：Factory 可直接加载 MCP；生成 Agent 通过 `/runtime/extensions` 与 Host MCP Gateway 使用宿主机 MCP server。
- **记忆系统**：会话内记忆使用 LangGraph `messages + checkpointer + thread_id`；跨会话记忆使用独立 BaseStore/SQLite，支持后台写入与语义召回。
- **定时任务系统**：Factory 与生成 Agent 共用 Scheduler Contract、SQLite job store、APScheduler trigger engine、ToolExecutionGateway 执行链路和 `scheduler_*` 标准事件。
- **Runtime Render Wrapper**：Factory 与生成 Agent 共用 `NodeRenderSpec` 和 `runtime_render_event`，节点生命周期由系统 wrapper 发出。
- **Contract/Builder 编译层**：AgentPackage 运行基础设施统一通过 `contracts/*.json` 和系统 Builder 注入 RuntimeContribution。
- **子 Agent 普通运行**：`/run-agent-package` 扫描 `.agentfactory/packages`，选择已生产 AgentPackage 后通过 Docker runtime container 执行真实 RuntimeKernel 链路。

仍未完成或仍在精修的边界：

- 第十阶段 `repair_or_finalize` 仍是空阶段。
- 第六阶段资源与 sandbox 准备已升级，但仍是当前重点精修区域。
- 定时任务系统已接入统一 Contract/Builder/ToolExecutionGateway 链路，仍需继续打磨运行体验与报表查询。
- 知识系统、Trace 系统、上下文管理系统尚未完成与工具/记忆同等级别的统一规范。
- Web UI 未实现；当前只保证 CLI-first。
- 当前不要求跑特化业务示例，验证以语法、静态、协议级、非业务单元测试为主。

## Factory 十阶段

当前阶段 ID 固定如下：

| # | stage_id | 当前状态 | 说明 |
| --- | --- | --- | --- |
| 1 | `requirement_capture` | 已实现，仍在精修 | 捕获需求、澄清边界、形成用户确认过的制造计划。 |
| 2 | `runtime_pattern_selection` | 已实现 | 基于 RuntimeKernel pattern metadata 选择运行模式。 |
| 3 | `graph_behavior_planning` | 已实现 | 规划节点职责、路由和运行行为。 |
| 4 | `node_strategy_planning` | 已实现 | 规划节点 wrapper、上下文、记忆、policy、tool visibility。 |
| 5 | `tool_capability_planning` | 已实现 | 规划工具能力契约和节点工具可见性，不生成工具代码。 |
| 6 | `resource_and_condition_planning` | 已实现，当前精修 | 准备资源键值、sandbox contract、资源报告，输出 sandbox 视角资源。 |
| 7 | `assembly_spec_generation` | 已实现 | 冻结 AssemblySpec、PackageMaterializationPlan、RenderManifest。 |
| 8 | `package_generation` | 已实现 | 按第七阶段计划物化 AgentPackage、contracts、真实工具代码草稿。 |
| 9 | `harness_generation_and_test` | 已实现，待系统验收 | 基于 package/sandbox contract 生成并执行 harness validation。 |
| 10 | `repair_or_finalize` | 待实现 | 后续读取 harness/report/trace 做返厂维修或最终出厂。 |

当前默认制造断点是：

```text
resource_and_condition_planning
```

也就是默认停在第六阶段，方便继续精修资源与 sandbox 准备链路。可以在 CLI 中用 `/stop <stage_id|off>` 修改断点。

## 安装与配置

安装 Python 运行层依赖：

```bash
uv sync
```

安装 TypeScript CLI 依赖：

```bash
pnpm --dir cli install
```

创建本地环境配置：

```bash
cp .env.example .env
```

至少填写主模型配置：

```bash
AGENTFACTORY_OPENAI_BASE_URL=
AGENTFACTORY_OPENAI_API_KEY=
AGENTFACTORY_OPENAI_MODEL=
```

建议同时填写小任务模型和 embedding 模型：

```bash
AGENTFACTORY_TASK_MODEL=
AGENTFACTORY_EMBEDDING_BASE_URL=
AGENTFACTORY_EMBEDDING_API_KEY=
AGENTFACTORY_EMBEDDING_MODEL=
AGENTFACTORY_EMBEDDING_DIMS=1536
```

主模型用于 Factory 制造流程和生成 Agent 普通回答。小任务模型用于轻量分类、llmRisk、记忆提取等。embedding 模型用于跨会话记忆语义召回。

## 启动 CLI

从仓库根目录启动：

```bash
pnpm factory
```

等价于：

```bash
pnpm --dir cli factory
```

常用命令：

```text
/chat
/create-agent
/run-agent-package
/agent-sessions
/sessions
/new-session
/resume <session_id>
/rerun <stage_id>
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

- `/chat`：Factory 自由对话/测试模式，走同一套工具系统、事件系统和记忆系统。
- `/create-agent`：进入 FactoryGraph 十阶段制造模式。
- `/run-agent-package`：扫描 `.agentfactory/packages`，选择已生产 AgentPackage 并进入子 Agent 对话。
- `/agent-sessions`：在当前 AgentPackage 下选择子 Agent session。
- `/sessions`：选择 Factory 会话。
- `/rerun <stage_id>`：基于 LangGraph checkpoint history 从指定阶段入口重跑。
- `/tool-grep <query|off>`：过滤工具活动展示。

## 运行时事件协议

Python bridge 会自动由 CLI 启动：

```bash
python -m agent_factory.factory_graph.frontend_bridge.stdio_server
```

协议是 JSONL over stdio。CLI 向 stdin 写 command，bridge 向 stdout 写 runtime event。

核心 command：

```text
start_session
list_sessions
switch_session
new_session
set_mode
send_message
resume_interrupt
rerun_from_stage
list_agent_packages
select_agent_package
delete_agent_package
list_agent_package_sessions
run_agent_package
set_options
shutdown
```

核心 event：

```text
runtime_ready
session_started
session_switched
sessions_listed
mode_changed
agent_packages_listed
agent_package_selected
agent_package_deleted
agent_package_sessions_listed
run_started
run_completed
run_failed
stage_started
stage_completed
stage_failed
node_started
node_progress
node_completed
node_failed
model_call_started
model_stream_delta
model_message_completed
model_call_failed
tool_call_proposed
tool_approval_requested
tool_approval_resolved
tool_call_started
tool_call_completed
tool_call_failed
tool_observation_available
interrupt_requested
runtime_paused
runtime_resumed
memory_write_queued
memory_write_queued_failed
memory_segment_prepared
memory_extraction_completed
memory_write_completed
memory_write_failed
memory_retrieval_completed
memory_injection_completed
trace_snapshot
debug_patch
error
```

统一事件 envelope：

```json
{
  "event_id": "...",
  "protocol_version": "factory_frontend.v1",
  "event_type": "model_stream_delta",
  "producer_type": "factory_runtime",
  "run_id": "...",
  "session_id": "...",
  "thread_id": "...",
  "mode": "create_agent",
  "graph_id": "factory_graph",
  "stage_id": "...",
  "node_id": "...",
  "span_id": "...",
  "parent_span_id": "...",
  "sequence": 1,
  "timestamp": "...",
  "severity": "info",
  "message": "...",
  "payload": {}
}
```

`debug_patch` 只进入调试面板，不能作为主 UI 数据源。

## 统一工具系统

工具链路：

```text
ToolProvider
  -> ToolSpec
  -> ToolRegistry
  -> ToolCompiler
  -> ToolExecutionGateway
  -> LangGraph ToolNode
  -> ToolMessage / Observation
```

当前基础工具：

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

network:
  web_fetch
  web_search
  当前保留 spec/框架，默认不作为已启用基础工具。
```

工具规范：

- 工具 manifest 使用统一 `ToolSpec`。
- 工具入口统一为 `run(arguments: dict, resources: dict) -> dict`。
- 工具风险入口统一为 `evaluate_risk(arguments: dict, context: dict) -> dict`。
- 参数先过 JSON Schema，再过风险策略，再进入 entrypoint。
- optional 参数缺省不会被误转成 `null` 触发 schema 失败。
- `medium/high` 工具可能触发审批；用户可 approve、deny、trust tool 或输入审查意见让模型重写工具调用。
- 一个 `AIMessage.tool_calls` 内按模型给出的顺序处理；允许并发的工具由 ToolSpec 的 `concurrent` 控制。

Skill 与 MCP：

- Skill 通过系统内置 `skill` 工具递进式披露。
- MCP 通过统一 provider 编译成 ToolSpec。
- 生成 Agent 不内置用户本机 MCP/Skill 内容，只保留 `/runtime/extensions` 后配置入口。

## 记忆系统

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
  + retrieval/ranking/injection
```

当前默认：

- Factory session、checkpoint、memory store 写入 `.agentfactory/`。
- 生成 Agent session、checkpoint、memory store 写入容器 `/runtime`，宿主侧挂载到 `.agentfactory/agent_runtime/<package_id>/`。
- Factory 与生成 Agent 的 session/checkpoint/store 目录隔离。
- 跨会话记忆写入不阻塞主对话。
- 默认每 3 轮成功对话触发一次 conversation segment 后台提取，由 `AGENTFACTORY_MEMORY_WRITE_INTERVAL_TURNS` 控制。
- 召回时按 query 检索、排序和硬限制注入，不写入 `messages`。

## Contract / Builder 编译层

AgentPackage 入口是 `agent_package.json`，它只索引文件，不直接构造服务。

Runtime 能力通过 `contracts/*.json` 声明，由系统内置 Builder 编译成 RuntimeContribution：

```text
AgentPackageManifest
  -> AssemblySpec
  -> RuntimeContracts
  -> ContractRegistry
  -> RuntimeContribution
  -> RuntimeKernel compile
```

当前 required contracts：

```text
contracts/dependencies.json
contracts/model.json
contracts/render.json
contracts/resources.json
contracts/sandbox.json
contracts/session.json
contracts/tools.json
```

可选 contract：

```text
contracts/memory.json
```

规则：

- `AssemblySpec` 只描述 Agent 逻辑装配，不承载 runtime 基础设施。
- 禁止通过 `AssemblySpec.metadata` 传递 runtime 能力。
- 禁止在 JSON 中写自定义 Builder import path。
- Builder 只能由系统注册。
- 新增基础能力必须提供 contract schema、内置 Builder、RuntimeContribution、Package 物化规则和编译校验规则。

## AgentPackage 产物

第六阶段资源与 sandbox 产物：

```text
.agentfactory/resources/<factory_run_id>/
  factory_resources.json
  sandbox_contract.json
  resource_preparation_report.json
```

第七阶段装配产物：

```text
.agentfactory/assemblies/<factory_run_id>/
  assembly_spec.json
  render_manifest.json
  package_materialization_plan.json
  assembly_validation_report.json
```

第八阶段 package draft：

```text
.agentfactory/packages/<factory_run_id>/
  agent_package.json
  assembly_spec.json
  resources.json
  sandbox_contract.json
  render_manifest.json
  package_report.json
  contracts/
    dependencies.json
    model.json
    render.json
    resources.json
    sandbox.json
    session.json
    tools.json
    memory.json
  bindings/
  prompts/
  tools/
    <tool_id>/
      tool.py
      manifest.json
      README.md
  policies/
  retrieval/
  strategies/
  formatters/
```

第九阶段 harness 产物：

```text
.agentfactory/harness/<factory_run_id>/
  runtime_environment_contract.json
  host_interaction_contract.json
  sandbox_dependency_plan.json
  harness_execution_plan.json
  harness_report.json
  artifacts/
```

`.agentfactory/` 是运行产物目录，不进入 Git。

## 子 Agent Docker 运行

普通运行和 harness 目标链路：

```text
AgentPackage
  -> agentfactory-runtime-python:3.12
  -> sandbox init dependency check/install
  -> python -m agent_factory.agent_runtime_bridge.stdio_server
  -> RuntimeKernel compile/run
  -> JSONL events
  -> CLI render
```

构建 runtime image：

```bash
docker build -t agentfactory-runtime-python:3.12 -f docker/agent-runtime/Dockerfile .
```

普通运行不再宿主机直跑 RuntimeKernel。`/run-agent-package` 会启动或复用长期 Docker runtime container，pending interrupt、工具审批和 session 恢复都通过同一个容器 bridge。

sandbox 挂载约定：

```text
/package                    read-only   AgentPackage
/resources/resources.json    read-only   resources.json
/artifacts                  read-write  日志、依赖报告、输出文件
/workdir                    read-write  临时工作区
/runtime                    read-write  session/checkpoint/memory/extensions
/runtime/extensions          read-write  用户后配置 MCP/Skill/扩展工具
/volumes/*                  configurable sandbox contract 挂载
```

Docker preflight 会检查：

- Docker CLI 是否存在。
- Docker daemon 是否可用。
- runtime image 是否存在。
- resources、mounts、volumes、secrets、network 是否能按 sandbox contract 转成容器参数。

镜像缺失时会返回结构化错误并提示构建命令，不自动构建。

## 环境变量

当前主要变量见 `.env.example`。

常用配置：

```bash
AGENTFACTORY_LLM_PROVIDER=openai_compatible_chat
AGENTFACTORY_OPENAI_BASE_URL=
AGENTFACTORY_OPENAI_API_KEY=
AGENTFACTORY_OPENAI_MODEL=
AGENTFACTORY_LLM_TIMEOUT_SECONDS=600
AGENTFACTORY_LLM_TEMPERATURE=0.2
AGENTFACTORY_LLM_MAX_OUTPUT_TOKENS=8192
AGENTFACTORY_LLM_THINKING=disabled

AGENTFACTORY_TASK_MODEL=
AGENTFACTORY_TASK_TEMPERATURE=0.1
AGENTFACTORY_TASK_MAX_OUTPUT_TOKENS=2048
AGENTFACTORY_TASK_THINKING=disabled

AGENTFACTORY_SESSION_ROOT=.agentfactory/sessions
AGENTFACTORY_CHECKPOINTER_BACKEND=sqlite
AGENTFACTORY_CHECKPOINT_PATH=.agentfactory/checkpoints/factory.sqlite

AGENTFACTORY_MEMORY_STORE_BACKEND=sqlite
AGENTFACTORY_MEMORY_STORE_PATH=.agentfactory/memory/factory.sqlite
AGENTFACTORY_MEMORY_WRITE_INTERVAL_TURNS=3
AGENTFACTORY_MEMORY_SEMANTIC_INDEX_ENABLED=true

AGENTFACTORY_EMBEDDING_PROVIDER=openai_compatible
AGENTFACTORY_EMBEDDING_BASE_URL=
AGENTFACTORY_EMBEDDING_API_KEY=
AGENTFACTORY_EMBEDDING_MODEL=
AGENTFACTORY_EMBEDDING_DIMS=1536

AGENTFACTORY_TOOL_MAX_REVISIONS=5
AGENTFACTORY_AGENT_RUNTIME_IDLE_TIMEOUT_SECONDS=1800
AGENTFACTORY_HOST_MCP_GATEWAY_BIND_HOST=127.0.0.1
AGENTFACTORY_HOST_MCP_GATEWAY_PORT=
```

本地环境配置和模型 secret 不进入 generated `resources.json`。

## 验证命令

本项目当前不要求自行跑特化业务示例。常规改动使用语法、静态和非业务单元测试。

Python：

```bash
python3 -m compileall -q agent_factory tests
```

相关单元测试示例：

```bash
python3 -m unittest \
  tests.factory_graph.test_frontend_event_normalizer \
  tests.tooling.test_factory_extensions \
  tests.tooling.test_tooling_core \
  tests.factory_graph.test_factory_chat_graph \
  tests.runtime_kernel.test_runtime_kernel -v
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

## 参考文档

- `docs/basic_capability_construction.md`：基础能力系统，包含工具、记忆、Contract/Builder、知识/定时/Trace/上下文占位。
- `docs/runtime_render_pipeline.md`：Factory 与生成 Agent 共用的事件渲染管线。
- `docs/factory_runtime_kernel_stages.md`：Factory 十阶段设计说明。该文档仍有历史记录痕迹，以当前代码和 README 的进度状态为准。
