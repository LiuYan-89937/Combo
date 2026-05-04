# FastAgentFactory
!!!!!!!!!!!!!!!!!
很多功能以及命令只是摆设
并未完善！







!!!!!!!!!!!!!!!!!
FastAgentFactory 是一个 **CLI-first 的 Agent 工厂**。你可以用自然语言描述想要的 Agent，系统会生成一个本地可运行的 AgentPackage，并提供校验、测试、运行、草稿管理和本地 trace 能力。

它不是只生成一段 prompt，而是生成一套可落地的本地包：

```text
自然语言需求
  -> AgentPackage 草稿
  -> 配置文件
  -> 工具代码
  -> 工具测试
  -> Harness 场景
  -> 本地验证报告
  -> 可运行 Agent
```

## 适合做什么

当前版本适合本地 MVP、Agent 原型和工程化验证：

- 创建客服 Agent、数据库管理 Agent、计算工具 Agent 等本地 Agent。
- 让 Agent 通过工具访问本地资源，例如 SQLite 数据库。
- 对生成的工具做静态检查和沙箱测试。
- 在 CLI 里管理草稿、运行 Agent、查看测试结果和 trace。
- 使用文件系统保存 Factory 状态、Agent 草稿、记忆和运行记录。

当前项目仍是本地优先的开发版本，不建议直接用于生产系统。

## 环境要求

- Python 3.11+
- uv
- 一个 OpenAI-compatible Chat Completions 模型服务

安装依赖：

```bash
cd /Users/liuyan/Desktop/FastAgentFactory
uv sync
```

检查 CLI：

```bash
uv run agentfactory --help
```

如果你已经激活虚拟环境：

```bash
source .venv/bin/activate
agentfactory --help
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

AGENTFACTORY_WEB_SEARCH_PROVIDER=disabled
AGENTFACTORY_WEB_SEARCH_API_KEY=
AGENTFACTORY_WEB_SEARCH_BASE_URL=
AGENTFACTORY_WEB_SEARCH_MAX_RESULTS=5
AGENTFACTORY_WEB_SEARCH_TIMEOUT_SECONDS=20
AGENTFACTORY_WEB_SEARCH_SEARCH_DEPTH=basic
AGENTFACTORY_WEB_SEARCH_TOPIC=general
AGENTFACTORY_WEB_SEARCH_INCLUDE_ANSWER=false
AGENTFACTORY_WEB_SEARCH_INCLUDE_RAW_CONTENT=false
AGENTFACTORY_WEB_SEARCH_INCLUDE_IMAGES=false
AGENTFACTORY_WEB_SEARCH_INCLUDE_FAVICON=false
AGENTFACTORY_WEB_SEARCH_INCLUDE_DOMAINS=
AGENTFACTORY_WEB_SEARCH_EXCLUDE_DOMAINS=
AGENTFACTORY_WEB_SEARCH_COUNTRY=
AGENTFACTORY_AGENT_WEB_INHERITANCE=explicit
```

`.env` 已经被 `.gitignore` 忽略，不会提交到 Git。

`web_search` 是 Factory 生产阶段的内部能力。默认关闭；当前真实 provider 先实现 Tavily。开启后 Factory 可以在生成工具前搜索公开 API/文档。生成的 Agent 只有在需求明确需要运行时联网/搜索/实时资料时，才会选择性继承 `web_search` / `browser_fetch` 内置能力。当前不提供 fake 搜索：要么配置真实 Tavily，要么明确不可搜索。

## 快速开始

初始化本地 Factory 工作区：

```bash
uv run agentfactory init
```

进入交互式 shell：

```bash
uv run agentfactory shell
```

进入后可以直接输入自然语言需求，例如：

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

## 普通命令用法

不进入 shell，也可以直接用普通命令：

```bash
uv run agentfactory create-agent \
  --prompt "创建一个客服 Agent，支持订单查询、投诉、售后问题处理和转人工。" \
  --draft \
  --stream
```

查看草稿：

```bash
uv run agentfactory drafts list
uv run agentfactory drafts show latest
```

校验草稿：

```bash
uv run agentfactory validate-agent .agentfactory/packages/drafts/<draft-id>
```

运行测试：

```bash
uv run agentfactory test-agent .agentfactory/packages/drafts/<draft-id>
```

运行 Agent：

```bash
uv run agentfactory run-agent .agentfactory/packages/drafts/<draft-id> --input "你好"
```

删除草稿：

```bash
uv run agentfactory drafts delete latest --yes
```

## Shell 常用命令

```text
/help
/create-agent
/drafts
/drafts show latest
/drafts use latest
/validate
/test
/run --input "..."
/repair-agent
/register
/registry
/trace
/diff
/approval
/exit
```

在 shell 里，普通自然语言输入会先作为需求记录下来；`/create-agent` 会使用当前记录的需求生成 Agent 草稿。

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
- 写操作是 medium risk，需要在回复里清楚说明将要修改什么。
- 不允许读取 .env、API key、secret、authorization、tool_auth_token。

输出风格：
简洁、明确，告诉用户查到了什么、改了什么、下一步可以做什么。
```

生成后在 shell 里测试：

```text
/drafts use latest
/run --input "现在有哪些工单？"
/run --input "查一下 T-1001"
```

## 本地文件说明

运行后会生成本地工作区：

```text
.agentfactory/
  config.yaml
  memory/
  traces/
  packages/
    drafts/
```

常见目录：

```text
.agentfactory/packages/drafts/
  <draft-id>/
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
    memory/
    traces/
```

这些内容都是本地运行状态，默认不提交到 Git。

## 工具与资源安全

FastAgentFactory 里，模型不能直接执行工具。

运行链路是：

```text
Model 提出 ToolCallProposal
  -> Runtime
  -> ToolRouter
  -> ToolExecutor
  -> 工具结果
  -> Model 总结回复
```

上下文分三类：

- 模型可见：允许进入 prompt 的文本。
- 工具可见：数据库路径、文件路径等工具运行资源。
- 隐藏字段：API key、secret、authorization、tool_auth_token 等敏感信息。

SQLite 这类二进制资源不会作为文本读进模型 prompt，只会作为工具资源路径传给工具。

## 测试

运行单元测试：

```bash
uv run python -m unittest discover -s tests
```

运行语法检查：

```bash
uv run python -m compileall agent_factory tests examples
```

真实 provider smoke test 默认关闭。需要主动打开：

```bash
AGENTFACTORY_RUN_PROVIDER_SMOKE=1 uv run python -m unittest tests.test_model_provider_smoke
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

### `uv run agentfactory` 找不到命令

确认已经执行：

```bash
uv sync
```

项目需要作为 package 安装，`pyproject.toml` 已经配置了：

```toml
[tool.uv]
package = true
```

### 模型请求超时

Factory 生成 Agent 时可能会进行多次模型调用，复杂工具生成会比较慢。可以在 `.env` 里调大：

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

### 如何清理草稿

```bash
uv run agentfactory drafts delete latest --yes
```

或者删除指定 draft：

```bash
uv run agentfactory drafts delete <draft-id> --yes
```
