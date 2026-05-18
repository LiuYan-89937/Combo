# FastAgentFactory

FastAgentFactory 是一个 CLI-first 的 Agent 工厂工程。当前目标不是做一个单次脚本生成器，而是把用户需求逐步转成可校验、可测试、可返厂维修的 RuntimeKernel AgentPackage。

当前系统分为两层：

- **Python Runtime**：负责 FactoryGraph、RuntimeKernel、AgentAssembly、session/checkpoint、工具执行、interrupt/resume、package materialization 和后续 harness/repair。
- **TypeScript CLI Frontend**：负责终端交互、阶段展示、流式事件渲染、工具审批、资源补全、会话切换和阶段重跑。

旧 Python CLI 已移除，不再保留兼容入口。

## 当前进度

已经完成的主干能力：

- RuntimeKernel v0：图模式编译、执行控制器、checkpoint/resume、observability、harness bridge、节点 wrapper、上下文/记忆/知识/policy 策略接口，以及默认策略注册。
- AgentAssembly v0：assembly schema、loader、validator、compiler、runner，以及 binding 强 schema 校验。
- FactoryGraph：10 阶段 LangGraph 生产图。
- Python Runtime Bridge：`agent_factory/factory_graph/frontend_bridge/` 通过 JSONL over stdio 暴露运行层事件和命令。
- TypeScript CLI：`cli/` 使用 Ink/React 作为唯一交互入口。
- Factory 基础工具：文件系统、搜索/理解、shell 三类工具，使用 LangChain `@tool` 注册，并通过 LangGraph `ToolNode` 注入。
- 阶段级 checkpoint 重跑：`/rerun <stage_id>` 基于 LangGraph checkpoint history 从指定阶段入口继续执行。

当前 10 个阶段状态：

| 阶段 | 状态 | 说明 |
| --- | --- | --- |
| 1. `requirement_capture` | 已实现 | 需求捕获与澄清，用户确认后进入后续阶段。 |
| 2. `runtime_pattern_selection` | 已实现 | 只基于 Pattern metadata/description 选择 RuntimeKernel pattern。 |
| 3. `graph_behavior_planning` | 已实现 | 基于 pattern 结构摘要规划节点行为、路由和中断点。 |
| 4. `node_strategy_planning` | 已实现 | 为每个节点规划 wrapper、上下文策略、记忆策略、policy、tool visibility。 |
| 5. `tool_capability_planning` | 已实现 | 规划工具能力契约、节点可见性、审批要求和实现状态。 |
| 6. `resource_and_condition_planning` | 已实现 | ReAct 资源准备阶段，工具检查走 `ToolNode`，验证后写 resources 文件。 |
| 7. `assembly_spec_generation` | 已实现 | 冻结 `AgentAssemblySpec`、`PackageMaterializationPlan` 和生成 Agent 的 `render_manifest`。 |
| 8. `package_generation` | 已实现 | 按第七阶段物化计划生成 AgentPackage draft、`render_manifest.json` 和真实工具代码草稿。 |
| 9. `harness_generation_and_test` | 已实现 | 生成并校验 sandbox/runtime/test 契约，执行 AgentPackage sandbox validation，产出 harness report。 |
| 10. `repair_or_finalize` | 待实现 | 将根据 harness/trace/report 做修复或最终出厂。 |

当前默认断点在第 8 阶段 `package_generation`。完成后会停下展示 package 产物，方便人工审查。

## 工程原则

- 需要暴露工具的阶段必须遵循 ReAct：`model -> tool_calls -> ToolNode -> observation -> model`。
- 纯规划阶段可以直接使用结构化模型输出，但必须走统一结构化输出入口。
- 结构化输出必须使用 Pydantic schema、prompt JSON 约束、`response_format/json_mode` 和业务校验，禁止手写裁剪 JSON。
- Factory 自身的 main/task model 配置不属于生成 Agent 的业务资源，不写入 generated resources。
- 资源不完整、不可验证、模型不可用或结构化输出失败时，不能生成伪业务产物。
- `.agentfactory/` 是运行产物目录，不进入 Git。

## 安装

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

在 `.env` 中填写模型配置：

```bash
AGENTFACTORY_OPENAI_BASE_URL=
AGENTFACTORY_OPENAI_API_KEY=
AGENTFACTORY_OPENAI_MODEL=
AGENTFACTORY_TASK_MODEL=
```

主模型用于核心制造流程、资源分析/重写、Assembly/Package 生成，并作为生成 Agent 的默认模型能力来源。task model 用于 Factory 内部轻量任务，例如 `/chat`、意图识别、简单分类和 CLI 辅助。

## CLI 使用

启动 TypeScript CLI：

```bash
pnpm --dir cli factory
```

根目录提供转发脚本：

```bash
pnpm factory
```

默认每次启动创建新 Factory 会话，不自动继承上一次上下文。

常用命令：

```text
/chat
/create-agent
/exit
/quit
/help
/session
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
```

说明：

- `/chat`：进入聊天模式，使用 Factory 轻量模型和基础工具。
- `/create-agent`：进入 Agent 制造模式，运行 10 阶段 FactoryGraph。
- `/sessions`：打开历史会话选择器，可上下选择。
- `/resume <session_id>`：按完整 id 切换会话。
- `/rerun <stage_id>`：从指定阶段入口 checkpoint 重跑，保留此前成功阶段产物。
- `/tool-grep <query|off>`：过滤工具执行与 observation 展示。
- `/stop <stage_id|off>`：设置或关闭阶段断点。

旧入口已经移除：

```text
uv run agentfactory shell
uv run agentfactory create-agent
uv run agentfactory test-stages
```

## Bridge 协议

TypeScript CLI 会自动启动 Python bridge 子进程：

```bash
python -m agent_factory.factory_graph.frontend_bridge.stdio_server
```

通信格式是 JSONL over stdio。TS CLI 向 stdin 写 command，Python bridge 向 stdout 写 runtime-bound event。前端只消费标准事件，不依赖 LangGraph 原始 patch；原始 patch 仅进入调试面板。

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
run_started
run_completed
run_failed
stage_started
stage_completed
stage_failed
node_started
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
resource_input_requested
trace_snapshot
debug_patch
error
```

每个 event 都带统一 envelope：

```json
{
  "event_id": "...",
  "event_type": "model_stream_delta",
  "run_id": "...",
  "session_id": "...",
  "mode": "create_agent",
  "graph_id": "factory_graph",
  "stage_id": "...",
  "node_id": "...",
  "span_id": "...",
  "parent_span_id": "...",
  "sequence": 1,
  "timestamp": "...",
  "payload": {}
}
```

## 阶段产物

第六阶段资源文件：

```text
.agentfactory/resources/<factory_run_id>/factory_resources.json
```

格式保持简洁：

```json
{
  "version": "factory_resources.v0",
  "resources": {}
}
```

第七阶段 Assembly 产物：

```text
.agentfactory/assemblies/<factory_run_id>/assembly_spec.json
.agentfactory/assemblies/<factory_run_id>/render_manifest.json
.agentfactory/assemblies/<factory_run_id>/package_materialization_plan.json
.agentfactory/assemblies/<factory_run_id>/assembly_validation_report.json
```

第八阶段 AgentPackage draft：

```text
.agentfactory/packages/<factory_run_id>/
  agent_package.json
  assembly_spec.json
  resources.json
  session.json
  memory/
    config.json
    store.json
  render_manifest.json
  package_report.json
  bindings/
  prompts/
  tools/
  policies/
  retrieval/
  strategies/
  formatters/
```

第八阶段只按第七阶段冻结的 `PackageMaterializationPlan` 生成文件：

- contract 类文件由系统确定性写入。
- 模型只生成计划中标记为 `model_generated` 的内容，例如 `tools/<tool_id>/tool.py` 和 README。
- 工具代码必须是真实 adapter draft，不允许 placeholder/mock/fallback 业务产物。
- 动态工具测试和 Agent 流程测试属于第九阶段。

## 第九阶段 Sandbox 运行边界

第九阶段已经接入 `harness_generation_and_test` 子图，负责把第八阶段 AgentPackage draft 放入受控 sandbox 契约中验证：

- 不把 MySQL、Postgres、Redis 等业务依赖临时安装进 AgentPackage 测试容器。
- AgentPackage 测试容器只负责运行生成的 agent/tool 代码。
- 业务依赖通过显式资源接入：宿主机服务、独立 Docker service、远程服务或声明的数据卷。
- 资源入口只来自第六阶段 `resources.json`，不读取宿主机 `.env`。
- Docker 默认禁用网络；如工具能力需要网络，必须由资源/测试契约显式声明。
- 端口、network、volume、service dependency 必须通过 sandbox contract 声明。
- sandbox 执行失败后，stdout/stderr/exit_code/report 会作为 observation 回到第九阶段模型；模型只能修正 runtime、host interaction、dependency、execution plan 契约后重跑，不能修改第八阶段 package/tool 代码。
- 依赖由 `sandbox_dependency_plan.json` 声明，并在 sandbox 内安装或检查；安装结果会写入 `dependency_results`，不会污染宿主机环境。

建议的 sandbox 挂载约定：

```text
/package      read-only   AgentPackage
/resources    read-only   resources.json
/artifacts    read-write  测试报告、日志、输出文件
/workdir      read-write  临时工作目录
/volumes/*    configurable  用户声明的数据卷
```

如果需要访问宿主机 MySQL，资源应被规范化为容器可访问地址，例如 `host.docker.internal:<port>`。如果是同一 Docker network 内的依赖服务，则使用 service name，例如 `mysql:3306`。

第九阶段落盘产物：

```text
.agentfactory/harness/<factory_run_id>/
  runtime_environment_contract.json
  host_interaction_contract.json
  sandbox_dependency_plan.json
  harness_execution_plan.json
  harness_report.json
  artifacts/
```

如果 Docker 未安装或不可用，阶段不会自动降级到本机运行，而是生成 `status=blocked` 的 harness report，错误位置为 `docker.runtime_detection`。

第九阶段当前可修复的执行类问题包括依赖缺失、依赖安装失败、资源文件错误和测试计划错误。工具代码语法或业务逻辑错误会直接进入 harness report，交给第十阶段 `repair_or_finalize` 处理。

## 环境变量

当前支持的本地变量：

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
AGENTFACTORY_RUN_PROVIDER_SMOKE=0
```

当前 env contract 中不包含 WebSearch/WebResearch 配置。

## 验证命令

本项目当前不要求自行跑特化业务示例。常规改动只做语法、静态和协议级检查。

Python 语法检查示例：

```bash
python -m py_compile \
  agent_factory/factory_graph/frontend_bridge/protocol.py \
  agent_factory/factory_graph/frontend_bridge/stdio_server.py \
  agent_factory/factory_graph/frontend_bridge/runtime_adapter.py \
  agent_factory/factory_graph/graph.py \
  agent_factory/factory_graph/chat_graph.py
```

TypeScript 检查：

```bash
pnpm --dir cli typecheck
pnpm --dir cli lint
pnpm --dir cli test
```

通用静态检查：

```bash
git diff --check
```
