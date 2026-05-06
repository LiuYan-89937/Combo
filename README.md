# FastAgentFactory

FastAgentFactory 是一个 **CLI-first、文档驱动的 Agent 工厂**。你可以用自然语言描述想要的 Agent，系统会生成一个本地可运行、可测试、可发布治理的 AgentPackage。

当前项目已经完成 `agentfactory_refactor_architecture.md` 描述的 8 个 Phase 重构，重构进度与验收记录见 [docs/refactor_progress.md](docs/refactor_progress.md)。

## 当前状态

- Runtime 已硬切为 `langgraph_native`，旧 `WorkflowRuntime` / `GraphRuntime` 不再对外导出。
- `RuntimeGraphCompiler + TaskGraphCompiler` 会把完整 AgentPackage 的 `task_graph.yaml` 编译为 LangGraph-native app，并注入 ControlGraph 能力：模型调用、工具、审批、native interrupt/resume、trace、memory、context。
- AgentInstance Runtime 的执行基层已迁移到 LangChain/LangGraph-native：runtime message 使用 `BaseMessage` / `AIMessage` / `ToolMessage`，审批恢复使用 LangGraph checkpointer + `Command(resume=...)`。
- Factory 生产图按 14 阶段传递 typed artifacts，并通过 `FactoryNodeAccessPolicy` 限制节点只能读取和修改 allow-list 字段。
- Resource Setup 使用 resolver registry：local path、Python package、system command、URL documentation、credential config、human approval；数据库文件/schema 探测走环境 probe 和受控 shell，不在 resolver 层特化 SQLite。
- Readiness issue 只保存结构化事实，不在环境探测层硬编码用户话术；clarification 由 task/small model 输出 summary、problem、impact、next_action，模型不可用时使用泛化模板兜底。
- Shell/CLI 展示已对接 Runtime 状态，`interrupted` 会显示审批提示与 `/run --yes`，Factory stream 完成后会展示自然语言 AgentPackage summary 和下一步操作。
- ToolBuildPipeline 已拆出 contract-first 生成、状态机、静态检查、测试、sandbox、repair loop。
- Harness 真实驱动 `AgentInstanceRuntime`，支持工具调用、上下文可见性、context compression、checkpoint resume 等断言。
- Registry/Release 记录 PackageProvenance、PromotionGate、UpgradeRequest、PatchPlan、ApprovalRecord、PackageDiff 生命周期信息。

最近本地验收：

```bash
uv run --extra dev pytest
# 133 passed, 3 skipped, 2 warnings
```

真实模型端到端验收为 opt-in：

```bash
AGENTFACTORY_RUN_PROVIDER_SMOKE=1 uv run --extra dev pytest tests/test_model_provider_smoke.py
# 2 passed, 1 skipped
```

其中通过项覆盖自然语言生成 AgentPackage 和复杂 SQLite 资源型 AgentPackage；跳过项是极简 provider `ok` smoke，因为当前 provider 对该最小提示返回空 content。

## 生成流程

```text
自然语言需求
  -> FactoryContextEnvelope
  -> RequirementUnderstanding
  -> CapabilityPlan
  -> ConditionPlan
  -> ResourceNeedPlan
  -> EvidenceReport
  -> ReadinessDecision
  -> ResourceContractSet
  -> ImplementationPlan
  -> AgentPackage
  -> ToolBuildReport
  -> HarnessSpec
  -> ProductionSummary
```

生成的 AgentPackage 包含：

```text
instructions.yaml
output.yaml
conversation.yaml
run_context.yaml
toolsets.yaml
knowledge.yaml
guardrails.yaml
handoffs.yaml
observability.yaml
runtime.yaml
task_graph.yaml
tools.yaml
mcp.yaml
context.yaml
memory.yaml
harness.yaml
package.yaml
generated/
  draft_tools/
  tool_tests/
  reports/
```

## 环境要求

- Python 3.11+
- uv
- 一个 OpenAI-compatible Chat Completions 模型服务

安装依赖：

```bash
cd /Users/liuyan/Desktop/FastAgentFactory
uv sync --extra dev
```

检查 CLI：

```bash
uv run agentfactory --help
```

## 配置模型

复制环境变量示例：

```bash
cp .env.example .env
```

填写 `.env`：

```env
AGENTFACTORY_LLM_PROVIDER=openai_compatible_chat
AGENTFACTORY_OPENAI_BASE_URL=
AGENTFACTORY_OPENAI_API_KEY=
AGENTFACTORY_OPENAI_MODEL=
```

可选配置：

```env
AGENTFACTORY_LLM_TIMEOUT_SECONDS=600
AGENTFACTORY_LLM_TEMPERATURE=0.2
AGENTFACTORY_LLM_MAX_OUTPUT_TOKENS=8192
AGENTFACTORY_LLM_THINKING=enabled

AGENTFACTORY_TASK_MODEL=
AGENTFACTORY_TASK_TEMPERATURE=0.1
AGENTFACTORY_TASK_MAX_OUTPUT_TOKENS=2048
AGENTFACTORY_TASK_THINKING=disabled
```

`.env` 已被 `.gitignore` 忽略。Factory 和 Runtime 会对 prompt、trace、memory、harness report 中的 secret 做 redaction；真实 secret 应通过 external config 或运行时上下文传入，不进入模型 prompt。

## Agent Memory 策略

生成出来的 Agent 默认使用 `memory.yaml` 中的 filesystem backend：

- session 级对话写入 `memory/session_memory.jsonl`，按 `session_id` 隔离。
- prompt 只回放最近 `conversation.yaml.history_window` 轮，默认 12 轮。
- 长对话超过窗口后触发 rolling summary，摘要由 `RuntimeContextCompiler` 注入 system prompt。
- 只有 `completed` turn 会写入 session memory；`interrupted`、`failed`、审批提示等运行状态不会作为普通 assistant 对话污染后续 prompt。
- 写入 memory 前会做 secret redaction。
- `summary_memory_file` 当前作为包规格声明保留，运行时摘要暂在 prompt 编译阶段滚动生成。

## 快速开始

初始化本地 Factory 工作区：

```bash
uv run agentfactory init
```

进入交互式 shell：

```bash
uv run agentfactory shell
```

在 shell 中输入自然语言需求，例如：

```text
创建一个客服 Agent，支持订单查询、投诉、售后问题处理和转人工。
```

然后执行：

```text
/create-agent
/drafts
/drafts use latest
/run --input "你好，介绍一下你能做什么"
```

也可以直接使用普通命令：

```bash
uv run agentfactory create-agent \
  --prompt "创建一个客服 Agent，支持订单查询、投诉、售后问题处理和转人工。" \
  --draft \
  --stream
```

## 常用命令

草稿管理：

```bash
uv run agentfactory drafts list
uv run agentfactory drafts show latest
uv run agentfactory drafts delete latest --yes
```

校验和测试：

```bash
uv run agentfactory validate-agent .agentfactory/packages/drafts/<draft-id>
uv run agentfactory test-agent .agentfactory/packages/drafts/<draft-id>
```

运行 Agent：

```bash
uv run agentfactory run-agent .agentfactory/packages/drafts/<draft-id> --input "你好"
```

审批恢复高风险或需确认工具：

```bash
uv run agentfactory run-agent .agentfactory/packages/drafts/<draft-id> \
  --input "执行需要审批的操作" \
  --approve <tool-call-id-or-tool-id>
```

Registry / 发布治理：

```bash
uv run agentfactory registry list
uv run agentfactory registry release <agent-name> --version <version>
uv run agentfactory registry rollback <agent-name> --version <version>
```

升级治理：

```bash
uv run agentfactory patch plan <package-path> --prompt "补充能力" --target-version 1.1.0
uv run agentfactory patch approve <change-id> --actor user --patch-plan <plan-path>
uv run agentfactory patch apply <package-path> --output <candidate-path>
```

## SQLite Agent 示例

你可以用下面这个需求测试本地 SQLite 工具型 Agent：

```text
创建一个本地 SQLite 工单管理 Agent，名字叫 LocalTicketAgent。

它面向非技术人员，用自然语言管理这个本地 SQLite 数据库：
/Users/liuyan/Desktop/FastAgentFactory/.agentfactory/local_db/customer_ops.sqlite3

第一版只管理 customer_tickets 表，字段包括：
ticket_id, customer_name, channel, title, description, status, priority, assignee, created_at, updated_at。

必须通过工具访问数据库，模型不能假装已经查询或修改数据库。

需要生成这些工具：
1. list_customer_tickets：分页列出工单。
2. get_customer_ticket：按 ticket_id 查询单个工单。
3. search_customer_tickets：按客户名、状态、优先级、标题关键词搜索。
4. create_customer_ticket：创建新工单。
5. update_customer_ticket_status：更新工单状态，只允许 open、pending、resolved、closed。
6. close_customer_ticket：关闭工单。

安全要求：
- 所有 SQL 必须使用参数化查询。
- 禁止 DROP、ALTER、ATTACH、DETACH、PRAGMA、VACUUM。
- 禁止删除数据库文件。
- 禁止访问数据库路径之外的文件。
- 读操作是 low risk，可以直接执行。
- 写操作是 medium risk，需要审批或明确确认。
- 不允许读取 .env、API key、secret、authorization、tool_auth_token。

输出风格：
简洁、明确，告诉用户查到了什么、改了什么、下一步可以做什么。
```

生成后测试：

```text
/drafts use latest
/run --input "现在有哪些工单？"
/run --input "查一下 T-1001"
```

## Runtime 安全模型

模型不能直接执行工具。运行链路是：

```text
Model 返回 `AIMessage.tool_calls`
  -> AgentInstanceRuntime
  -> PolicyWrappedToolNode
  -> ToolRouter
  -> PolicyEngine
  -> ToolExecutor
  -> ToolResultEnvelope
  -> compressed observation
  -> Model 总结回复
```

`ToolResultEnvelope.status` 支持：

```text
completed | failed | interrupted | needs_configuration | blocked
```

上下文分三类：

- `visible_to_model`：允许进入 prompt 的文本。
- `visible_to_tools`：数据库路径、文件路径、external config refs 等工具运行资源。
- `hidden`：API key、secret、authorization、tool_auth_token 等敏感信息。

长对话会触发 context compression；工具 observation 会被压缩和 redaction 后再回注模型；LangGraph checkpointer 只落 package-local runtime checkpoint，不把 secret 写进 prompt、trace、memory 或 harness report。

## 本地工作区

运行后会生成：

```text
.agentfactory/
  config.yaml
  memory/
  traces/
  approvals/
  upgrades/
  packages/
    drafts/
  registry/
```

这些目录保存本地运行状态、草稿、trace、memory、审批记录和 registry 索引，默认不提交到 Git。

## 测试

默认测试：

```bash
uv run --extra dev pytest
```

Focused tests：

```bash
uv run --extra dev pytest tests/test_agent_instance_runtime.py
uv run --extra dev pytest tests/test_refactor_architecture.py
uv run --extra dev pytest tests/test_harness_runner.py
```

真实模型端到端测试默认关闭，需要显式打开：

```bash
AGENTFACTORY_RUN_PROVIDER_SMOKE=1 uv run --extra dev pytest tests/test_model_provider_smoke.py
```

## 常见问题

### `agentfactory: command not found`

优先使用：

```bash
uv run agentfactory --help
```

或者激活虚拟环境：

```bash
source .venv/bin/activate
agentfactory --help
```

### 模型请求超时

Factory 生成 AgentPackage 会进行多次模型调用，复杂资源和工具生成会更慢。可以在 `.env` 中调大：

```env
AGENTFACTORY_LLM_TIMEOUT_SECONDS=600
```

### 生成的 Agent 草稿在哪里

默认在：

```text
.agentfactory/packages/drafts/
```

查看：

```bash
uv run agentfactory drafts list
```

### 如何查看完整重构验收状态

查看：

```bash
sed -n '1,180p' docs/refactor_progress.md
```
