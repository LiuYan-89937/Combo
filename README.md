# FastAgentFactory

FastAgentFactory 是一个 CLI-first 的 AgentPackage 工厂。它把自然语言需求制造成可编译、可验证、可发布、可运行的 AgentPackage，并让工厂自身、聊天模式和生产出的子 Agent 尽量共享同一套 RuntimeKernel、工具、上下文、记忆、定时任务和事件流规范。

项目当前关注三件事：

- 生产 AgentPackage：用户在 `/create-agent` 描述需求，制造链路用 ReAct 模式读写包文件、调用 validator、probe package tool、确认后发布。
- 运行 AgentPackage：已发布包由 RuntimeKernel 编译和执行，默认通过 Docker sandbox 隔离运行。
- 统一前端事件：CLI 只消费标准 runtime events；后续网页端、移动端可以复用同一协议。

## 当前形态

```text
TypeScript CLI
  -> Python JSONL bridge
  -> Factory runtime adapter
  -> /chat SystemPackage runtime
  -> /create-agent ReAct manufacturing runtime
  -> /run-agent-package published AgentPackage runtime
```

核心运行链路：

```text
AgentPackage
  -> RuntimeContracts
  -> RuntimeBuildPlanner
  -> AgentAssemblyCompiler
  -> RuntimeKernel
  -> LangGraph pattern
  -> model / tools / memory / knowledge / scheduler / trace
  -> runtime events
  -> frontend render
```

## 目录结构

```text
agent_factory/
  create_agent/              create-agent ReAct 制造链路
  runtime_kernel/            RuntimeKernel、节点、pattern、状态、model operation
  runtime_contracts/         AgentPackage contract schema 与 build planner
  package_runtime/           宿主侧运行已发布 AgentPackage
  agent_runtime_bridge/      Docker 子进程内 JSONL runtime bridge
  factory_graph/             CLI bridge、frontend event normalizer、session adapter
  tooling/                   ToolSpec、ToolExecutionGateway、内置工具、skill、MCP provider
  context_system/            上下文检索、压缩、turn evidence
  memory_system/             跨会话 memory store 与后台写入
  knowledge_system/          知识源发现、索引与检索
  scheduler_system/          定时任务事实源与 APScheduler runtime
  trace_system/              JSONL trace fact store

SystemPackage/
  factory_chat/              工厂 chat 模式本身也是一个 AgentPackage
  extensions/                系统级 MCP / skill 配置

cli/
  src/                       Ink CLI、事件投影、命令、interrupt 渲染

docker/
  agent-runtime/             子 Agent runtime 镜像

docs/
  basic_capability_construction.md
  runtime_render_pipeline.md
```

`.agentfactory/` 和 `.agent_runtime/` 是本地运行产物目录，不进入 Git。

## 环境要求

- Python 3.11+
- Node.js 与 pnpm
- uv
- Docker Desktop 或可用 Docker daemon
- OpenAI-compatible Chat Completions 服务
- 可选：OpenAI-compatible embedding 服务，用于跨会话记忆语义检索

## 安装

从仓库根目录安装 Python 依赖：

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

`.env` 不进入 Git。模型、数据库、MCP、Docker 等本地配置都放在 `.env` 或 `.agentfactory/` 运行目录内。

## 基础配置

至少需要配置主模型：

```bash
AGENTFACTORY_LLM_PROVIDER=openai_compatible_chat
AGENTFACTORY_OPENAI_BASE_URL=
AGENTFACTORY_OPENAI_API_KEY=
AGENTFACTORY_OPENAI_MODEL=
```

建议配置小任务模型和压缩模型：

```bash
AGENTFACTORY_TASK_MODEL=
AGENTFACTORY_COMPRESSION_BASE_URL=
AGENTFACTORY_COMPRESSION_API_KEY=
AGENTFACTORY_COMPRESSION_MODEL=
AGENTFACTORY_CONTEXT_WINDOW_TOKENS=1000000
```

工具审批策略可按环境调整：

```bash
AGENTFACTORY_TOOL_APPROVAL_MODE=standard
AGENTFACTORY_TOOL_APPROVAL_LOW=
AGENTFACTORY_TOOL_APPROVAL_MEDIUM=
AGENTFACTORY_TOOL_APPROVAL_HIGH=
```

跨会话记忆语义检索需要 embedding：

```bash
AGENTFACTORY_MEMORY_SEMANTIC_INDEX_ENABLED=true
AGENTFACTORY_EMBEDDING_PROVIDER=openai_compatible
AGENTFACTORY_EMBEDDING_BASE_URL=
AGENTFACTORY_EMBEDDING_API_KEY=
AGENTFACTORY_EMBEDDING_MODEL=
AGENTFACTORY_EMBEDDING_DIMS=1536
```

常用本地运行目录：

```bash
AGENTFACTORY_SESSION_ROOT=.agentfactory/sessions
AGENTFACTORY_CHECKPOINTER_BACKEND=sqlite
AGENTFACTORY_CHECKPOINT_PATH=.agentfactory/checkpoints/factory.sqlite
AGENTFACTORY_MEMORY_STORE_BACKEND=sqlite
AGENTFACTORY_MEMORY_STORE_PATH=.agentfactory/memory/factory.sqlite
AGENTFACTORY_SCHEDULER_STORE_PATH=.agentfactory/scheduler/factory.sqlite
```

完整配置以 [.env.example](.env.example) 为准。

## 启动

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

正常使用时不需要手动运行 bridge。

## CLI 命令

```text
/chat                         进入 SystemPackage 聊天模式
/create-agent                 进入 Agent 制造模式
/run-agent-package            扫描正式产物目录并进入已发布 Agent
/agent-sessions               选择当前 AgentPackage 的会话
/scheduler <action>           管理定时任务与执行记录
/session                      显示当前会话
/sessions                     打开历史会话选择器
/new-session                  创建新会话
/resume <session_id>          按完整 id 切换会话
/tools                        显示工厂基础工具
/state on|off                 切换最终 state 展示
/messages on|off              切换最终 messages 展示
/tool-grep <query|off>        过滤工具执行与 observation 展示
/cancel                       取消当前正在运行的请求
/exit                         退出当前模式
/quit                         退出 CLI
/help                         显示命令帮助
```

## create-agent 制造链路

`/create-agent` 是宿主侧 ReAct 制造链路，不再使用独立 workflow 代替模型决策。系统负责安全边界、空包 scaffold、工具执行、validator、publish gate；模型负责理解需求、选择能力、编辑文件、显式切换 focus、显式调用 validation 和 publish。

当前制造流程：

```text
用户需求
  -> create-agent workspace
  -> 代码生成空 AgentPackage
  -> LLM 读取当前包文件和少量 capability example
  -> LLM 通过受控文件工具编辑包
  -> LLM 显式调用 create_agent_validate
  -> 如有 package tool，LLM 调用 create_agent_probe_tool 做真实工具 probe
  -> LLM 修复并再次 validate
  -> LLM 切换到 validation_publish
  -> full_static validation passed
  -> create_agent_control(action=finalize)
  -> 用户发布确认
  -> create_agent_publish
```

制造原则：

- 空 AgentPackage 是基础结构来源，模型不逐文件审计 scaffold。
- validator 是 evidence provider，不自动推进或回退 focus。
- 文件写入只受通用安全边界限制，不按阶段锁死 owned files。
- schema 是 repair 工具，不是正常生产路径的阅读材料。
- package tool 必须能被加载、真实 probe，并留下 observation。
- MCP candidate 由系统在 validation/publish 前按 `tool_access.allowed_tool_ids` 轻量继承。
- 发布前必须有最新 `full_static` validation passed，且包 fingerprint 未变化。

制造工作区位于：

```text
.agentfactory/create_agent_workspaces/<session_id>/
```

制造 trace 位于工作区内：

```text
.factory/manufacturing_trace.json
```

## AgentPackage

AgentPackage 是可发布运行单元。基础形状由 `package_scaffold` 生成，运行时由 `AgentPackageLoader + RuntimeBuildPlanner + AgentAssemblyCompiler` 装配。

典型结构：

```text
agent_package.json
assembly_spec.json
render_manifest.json
resources.json
sandbox_contract.json
contracts/
  artifact.json
  context.json
  dependencies.json
  knowledge.json
  memory.json
  model.json
  node_provider.json
  render.json
  resources.json
  sandbox.json
  scheduler.json
  session.json
  state.json
  tools.json
  trace.json
prompts/
tools/
policies/
strategies/
formatters/
extensions/
```

`agent_package.json` 只做索引。运行能力来自 `contracts/*.json`，业务装配来自 `assembly_spec.json`，对话体验来自 prompt binding 和 model operation binding。

正式发布目录：

```text
.agentfactory/published_agent_packages/
```

临时或开发包目录：

```text
.agentfactory/packages/
```

## RuntimeKernel 输入规范

RuntimeKernel 的模型请求由统一 builder 组装：

```text
stable system prompt
  + full conversation history
  + dynamic turn evidence
  + native tool surface
```

稳定前缀和动态尾部分离，以提高 provider prompt cache 命中率。运行时会记录：

```text
model_cache_metrics
stable_prefix_digest
dynamic_evidence_digest
tool_surface_digest
input_tokens
cached_input_tokens
hit_ratio
```

动态 evidence 只作为本轮内部上下文，不应该被直接展示给用户。

## 工具系统

统一工具链路：

```text
ToolProvider
  -> ToolSpec
  -> ToolRegistry
  -> ToolCompiler
  -> ToolExecutionGateway
  -> LangGraph ToolNode
  -> ToolObservation
```

工具入口统一返回 envelope：

```json
{
  "output": {},
  "evidence": {},
  "summary": ""
}
```

- `output` 只表达业务结果，并由 `ToolSpec.output_schema` 校验。
- `evidence` 记录风险、审批、fingerprint、focus、changed files 等运行证据。
- `summary` 用于面向模型和前端的短摘要。

内置工具包括 filesystem、process、scheduler、knowledge、resource_set、tool_output、network、skill 和 MCP provider 编译出的工具。中高风险工具可触发审批。

工具审批由 ToolGateway 的统一策略控制。`.env` 是全局默认；AgentPackage 只有在 `contracts/tools.json` 的 `config.approval_policy` 显式写出字段时才覆盖：

```json
{
  "mode": "custom",
  "low": "ask_on_risk",
  "medium": "allow",
  "high": "ask"
}
```

`standard` 等价于低风险 `ask_on_risk`、中风险 `ask_unless_allowed`、高风险 `ask`。
包内不写 `approval_policy` 时继承 `.env`；只写单个风险级时只覆盖该风险级。

策略值：

```text
allow                不审批，除非风险 evaluator 明确 deny
ask                  总是审批
ask_on_risk          evaluator 要求 ask/uncertain 时审批
ask_unless_allowed   evaluator 明确 allow 时不审批，否则审批
deny                 直接拒绝
```

本地调试时如果希望所有非 deny 工具都不弹审批：

```bash
AGENTFACTORY_TOOL_APPROVAL_MODE=allow_all
```

## Skill 与 MCP

Skill 是制造期和运行期的协议知识来源，按 describe / read_resource 递进披露。create-agent skill 只应该提供：

- guidance：什么时候需要该能力、应该改哪些文件。
- examples：从空包增加能力的完整增量例子。
- repair：validator issue 后的修复提示。

MCP 通过统一 provider 暴露成 ToolSpec。宿主机 MCP 可以通过 MCP gateway 提供给 Docker 子 Agent，子 Agent 镜像不需要重复安装 Node 依赖。

## 上下文、记忆、知识

ContextSystem 负责模型调用前的 turn evidence 和会话压缩，不再把工具表、最近消息等动态内容塞进稳定 system prompt。

MemorySystem 负责跨会话记忆：

```text
conversation
  -> background memory write
  -> store namespace
  -> optional semantic index
  -> retrieval evidence
```

KnowledgeSystem 负责知识源发现、索引和检索。知识目录在子 Agent 中映射到：

```text
/runtime/knowledge
```

## 定时任务

SchedulerSystem 使用 SQLite 作为事实源，APScheduler 负责触发，任务执行复用 RuntimeKernel 或 ToolExecutionGateway。

支持任务类型：

```text
graph_run
script_run
tool_call
```

支持触发类型：

```text
cron
interval
date
```

子 Agent 可以通过运行期工具创建自己的定时任务。需要用户审批的工具在 unattended scheduler policy 下不会静默执行。

## Docker 子 Agent runtime

构建 runtime 镜像：

```bash
DOCKER_BUILDKIT=1 docker build -t agentfactory-runtime-python:3.12 -f docker/agent-runtime/Dockerfile .
```

可指定基础镜像和 Debian 镜像源：

```bash
DOCKER_BUILDKIT=1 docker build -t agentfactory-runtime-python:3.12 \
  --build-arg PYTHON_BASE_IMAGE=python:3.12-slim \
  --build-arg DEBIAN_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian \
  --build-arg DEBIAN_SECURITY_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian-security \
  -f docker/agent-runtime/Dockerfile .
```

容器挂载约定：

```text
/package                  read-only   AgentPackage
/resources/resources.json read-only   package resources
/artifacts                read-write  artifact output
/workdir                  read-write  temporary workdir
/runtime                  read-write  session/checkpoint/memory/extensions/knowledge/trace
/runtime/extensions       read-write  runtime extensions
/runtime/knowledge        read-write  knowledge root
/volumes/*                optional sandbox contract volumes
```

Docker preflight 会检查 Docker CLI、daemon、runtime image、mount、volume、network 和 sandbox contract。

## 事件流与前端

CLI、chat、create-agent、子 Agent runtime 都通过统一 runtime events 交互。前端只做事件投影和渲染，不直接理解后端内部状态文件。

常见事件包括：

```text
run_started
node_started
model_streaming
tool_running
tool_completed
tool_failed
tool_approval_requested
interrupt_requested
run_completed
run_failed
model_cache_metrics
```

协议目录在：

```text
agent_factory/factory_graph/frontend_bridge/protocol_catalog.json
```

## Trace

TraceSystem 使用 JSONL fact store。运行期 trace 一般位于：

```text
/runtime/trace/runs/<trace_id>/
  manifest.json
  trace.jsonl
  refs.jsonl
```

create-agent 制造 trace 位于制造工作区的 `.factory/manufacturing_trace.json`。Trace 是事实源；CLI timeline 是对 runtime events 的实时投影。

## 本地运行产物

```text
.agentfactory/
  sessions/
  checkpoints/
  memory/
  scheduler/
  packages/
  published_agent_packages/
  agent_runtime/
  factory/
```

这些目录不进入 Git。清理历史运行数据时注意保留：

- `.agentfactory/factory/mcp_servers/`：宿主机 MCP 安装位置。
- `.agentfactory/published_agent_packages/`：正式发布包。

## 开发检查

本项目不要求自行运行特化业务样例。常规改动优先做语法和静态检查。

Python：

```bash
PYTHONPYCACHEPREFIX=/private/tmp/fastagentfactory_pycache .venv/bin/python -m compileall -q agent_factory
```

TypeScript：

```bash
pnpm --dir cli typecheck
```

Git diff：

```bash
git diff --check
```

运行真实链路、调用外部模型、调用 MCP、执行 Docker agent，应该在明确需要时手动进行。

## 参考文档

- [docs/basic_capability_construction.md](docs/basic_capability_construction.md)：基础能力、Contract、Builder 与 RuntimeKernel 接入规范。
- [docs/runtime_render_pipeline.md](docs/runtime_render_pipeline.md)：runtime events 与前端渲染链路。
