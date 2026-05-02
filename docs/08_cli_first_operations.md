# 08. CLI-first 操作规范

## 目标

第一版不做可视化页面，而是实现成熟 agent CLI 的操作体验。CLI 是正式产品面，不是临时调试入口。

CLI 同时提供普通命令和 Claude Code 风格的斜杠交互命令：

```text
普通命令：适合脚本、CI、可重复执行
斜杠命令：适合非技术用户在交互式会话里创建、审批、测试、升级 Agent
```

界面风格参考 Claude Code / Codex CLI：终端原生、对话式、低干扰、非全屏。第一版使用 `Typer + Rich + prompt_toolkit`。

## 设计原则

```text
1. 自然语言入口。
2. 交互式确认。
3. 风险清晰展示。
4. 所有结果可用 --json 输出。
5. 所有关键操作可追踪。
6. 所有生成物可落盘、可 diff、可回滚。
7. CLI 调用 Application Service，不直接写业务逻辑。
8. 普通命令和斜杠命令必须共享同一套 Application Service。
9. 人类可读输出和 `--json` 机器输出必须分离。
10. 交互式 shell 不做复杂全屏 TUI。
11. AgentFactory 创建和升级 Agent 的过程必须流式输出到控制台。
12. 长任务必须让用户知道当前阶段、产物路径、风险和下一步。
```

## 视觉语言

```text
提示符：›
新增：+
修改：~
禁用 / 废弃：-
高风险 / 警告：!
下一步建议：Next
```

输出风格：

```text
1. 单列对话流。
2. 简短块状结果。
3. 默认只展示摘要。
4. 长 trace、diff、Harness 报告通过命令展开。
5. 高风险审批项必须醒目展示。
6. 每次关键操作后显示 Next 建议。
7. 错误信息包含原因和下一步建议。
```

示例：

```text
AgentFactory v0.1  ·  customer-service-agent  ·  draft

› /review-agent examples/customer_service_agent

  Agent
  Name     customer-service-agent
  Goal     处理售前、售后、退款、返厂、投诉与人工转接

  Capabilities
  + intent_detection
  + tool_routing
  + mcp_binding
  + memory_management

  High risk
  ! repair_ticket_create requires confirmation

  Next
  /approve-agent examples/customer_service_agent
  /validate examples/customer_service_agent
```

## MVP 命令

```bash
agentfactory init
agentfactory shell

agentfactory create-agent --prompt "创建一个客服 Agent" --draft --stream
agentfactory review-agent examples/customer_service_agent
agentfactory approve-agent examples/customer_service_agent --actor user
agentfactory validate-agent examples/customer_service_agent
agentfactory test-agent examples/customer_service_agent
agentfactory register-agent examples/customer_service_agent

agentfactory run-agent customer-service-agent --version 1.0.0 --chat
agentfactory trace list --agent customer-service-agent
agentfactory trace show trace-001

agentfactory upgrade-agent customer-service-agent --prompt "增加以旧换新意图"
agentfactory plan-upgrade customer-service-agent --request upgrade.yaml --output patch_plan.yaml
agentfactory review-patch patch_plan.yaml
agentfactory approve-patch patch_plan.yaml --change change-tool-001 --actor user
agentfactory apply-patch-plan patch_plan.yaml --output examples/customer_service_agent_v1_1_0
agentfactory diff show diff-20260501-001
agentfactory diff validate diff-20260501-001
agentfactory test-agent examples/customer_service_agent_v1_1_0
agentfactory release customer-service-agent --version 1.1.0 --channel candidate
```

## 工厂流式输出

`create-agent`、`plan-upgrade`、`apply-patch-plan`、`test-agent`、`release` 都可能是长任务。CLI 必须把 AgentFactory 的阶段性进展流式显示在控制台，不能让用户面对空白等待。

默认行为：

```text
1. 交互式 shell 中默认 stream。
2. 普通命令中 create-agent / plan-upgrade / test-agent 默认 stream。
3. 使用 --json 时输出 JSON Lines 事件，不输出 Rich 人类界面。
4. 使用 --quiet 时只输出最终结果。
```

### create-agent 流程展示

示例：

```text
› /create-agent --draft

  Factory
  + Requirement captured
    "创建一个客服 Agent，支持退款、投诉、转人工和订单查询"

  + RequirementAnalyzer
    clarification none

  + PrimitivePlanner
    output        AgentPackagePrimitives JSON

  + PackageWriter
    path          .agentfactory/packages/drafts/customer-service-agent
    files         instructions.yaml, output.yaml, conversation.yaml, run_context.yaml, toolsets.yaml, knowledge.yaml, guardrails.yaml, handoffs.yaml, observability.yaml

  + ToolGenerator
    path          generated/draft_tools/
    status        draft, approval required

  + ToolTestGenerator
    path          generated/tool_tests/

  + MCPBindingGenerator
    path          mcp.yaml

  + HarnessGenerator
    path          harness.yaml

  + PackageValidator
    status        passed

  Draft created
  Path             .agentfactory/packages/drafts/customer-service-agent

  Next
  /validate .agentfactory/packages/drafts/customer-service-agent
  /test .agentfactory/packages/drafts/customer-service-agent
```

### plan-upgrade 流程展示

```text
› /plan-upgrade customer-service-agent

  Factory
  + UpgradeRequest loaded
    reason         unknown_intent
    samples        3

  + Impact analysis
    files          workflow.yaml, tools.yaml, harness.yaml
    risk           high

  + PatchPlan generated
    changes        3
    approvals      2 required

  ! Approval required
    change-tool-001        repair_ticket_create
    generated-tool-001     generated/draft_tools/repair_ticket_create.py

  Next
  /review-patch patch_plan.yaml
  /approve-patch patch_plan.yaml --change change-tool-001
```

### test-agent 流程展示

```text
› /test examples/customer_service_agent

  AgentHarness
  + Loading scenarios        6
  + Preparing fixtures       tool, mcp, context
  + Running refund_flow_001  passed
  + Running complaint_001    passed
  ! Running safety_001       failed

  AgentHarness failed
  Trace            trace-safety-001

  Next
  /trace show trace-safety-001
```

### 流式事件对象

Application Service 应产生结构化事件，CLI 只负责渲染：

```python
class FactoryEvent(BaseModel):
    event_id: str
    run_id: str
    stage: str
    status: Literal["started", "progress", "completed", "warning", "failed"]
    title: str
    message: str | None = None
    payload: dict[str, Any] = {}
    artifact_path: str | None = None
    next_actions: list[str] = []
```

`--json` 输出 JSON Lines：

```jsonl
{"stage":"RequirementAnalyzer","status":"completed","payload":{"intents":["refund","complaint"]}}
{"stage":"PackageGenerator","status":"completed","artifact_path":"examples/customer_service_agent"}
```

人类界面输出由 `rendering.py` 渲染，不能在业务服务里直接 print。

## 斜杠命令模式

`agentfactory shell` 进入交互式会话。用户输入普通文本时，CLI 将其作为自然语言需求；用户输入 `/` 开头内容时，CLI 将其作为命令执行。

示例：

```text
$ agentfactory shell

› 创建一个客服 Agent，支持退款、返厂、投诉、转人工，并能查询订单
› /create-agent --draft
› /review-agent examples/customer_service_agent
› /approve-agent examples/customer_service_agent
› /validate examples/customer_service_agent
› /test examples/customer_service_agent
› /register examples/customer_service_agent
› /run customer-service-agent --version 1.0.0 --chat
```

升级示例：

```text
› 给客服 Agent 增加以旧换新意图
› /upgrade customer-service-agent
› /plan-upgrade customer-service-agent
› /review-patch patch_plan.yaml
› /approve-patch patch_plan.yaml --change change-tool-001
› /apply-patch-plan patch_plan.yaml
› /diff show diff-20260501-001
› /diff validate diff-20260501-001
› /test examples/customer_service_agent_v1_1_0
› /release customer-service-agent --version 1.1.0 --channel candidate
```

第一版必须支持的斜杠命令：

```text
/help
/exit
/init
/create-agent
/review-agent
/approve-agent
/validate
/test
/register
/run
/upgrade
/plan-upgrade
/review-patch
/approve-patch
/apply-patch-plan
/trace
/diff
/approval
/registry
/release
```

斜杠命令状态规则：

```text
1. ShellSession 保存当前 pending_requirement。
2. /create-agent --draft 可以默认读取 pending_requirement。
3. /upgrade 可以默认读取 pending_requirement 作为升级需求。
4. /review-patch 默认读取最近生成的 PatchPlan。
5. /approve-patch 默认要求明确 change id，避免误批高风险变更。
6. /exit 时必须提示未处理的 draft、PatchPlan、ApprovalRecord。
7. 斜杠命令需要支持基础补全。
8. Ctrl+C 取消当前输入，Ctrl+D 等同 /exit。
```

## 交互式体验

CLI 对非技术使用者要展示：

```text
1. Agent 目标摘要。
2. 将新增的能力。
3. 将使用的工具和 MCP。
4. 每个高风险操作的原因。
5. 需要用户确认的 change。
6. Harness 是否通过。
7. 发布和回滚目标。
8. 工厂当前执行阶段。
9. 已生成的文件和 artifact 路径。
10. 长任务失败时的恢复建议。
```

## 机器可读输出

所有命令都应支持：

```bash
--json
--output <path>
--yes
--dry-run
--verbose
--stream / --no-stream
--quiet
```

## 验收标准

| 编号 | 验收项 | 命令 / 场景 | 通过标准 |
| --- | --- | --- | --- |
| 08-001 | CLI help 可用 | `agentfactory --help` | 列出核心命令，不报错 |
| 08-002 | 子命令 help 可用 | `agentfactory create-agent --help` | 展示参数、说明和退出码 |
| 08-003 | Shell 可启动 | `agentfactory shell` | 进入交互式模式 |
| 08-004 | Shell 提示符正确 | shell 启动后 | 使用 `›` 提示符 |
| 08-005 | 斜杠 help 可用 | `/help` | 列出斜杠命令和当前会话状态 |
| 08-006 | Shell 可退出 | `/exit` 或 Ctrl+D | 正常退出，未保存内容有提示 |
| 08-007 | 自然语言输入可捕获 | 输入普通文本 | 写入 `ShellSession.pending_requirement` |
| 08-008 | create-agent 流式输出 | `/create-agent --draft` | 显示 LangGraph 生产节点事件；当前阶段至少包含 requirement、clarification、PrimitivePlanner、PackageWriter、PackageValidator，后续再接 HarnessGenerator |
| 08-009 | create-agent 产物路径可见 | `/create-agent --draft` | 输出 AgentPackage 草稿路径和已生成 YAML 文件列表 |
| 08-010 | create-agent Next 建议 | `/create-agent --draft` | 输出 `/review-agent`、`/validate` 等下一步 |
| 08-011 | review-agent 摘要可读 | `/review-agent <path>` | 展示目标、能力、工具、MCP、风险 |
| 08-012 | 高风险醒目展示 | review / patch 场景 | 使用 `!` 标记高风险项 |
| 08-013 | validate 可读输出 | `/validate <path>` | 成功/失败摘要清晰，失败有文件和建议 |
| 08-014 | test-agent 可流式输出 | `/test <path>` | 逐个 scenario 输出运行状态 |
| 08-015 | trace 可展开 | `/trace show <id>` | 能查看 trace 摘要或详情 |
| 08-016 | plan-upgrade 流式输出 | `/plan-upgrade <agent>` | 显示影响分析、PatchPlan、审批需求 |
| 08-017 | approve-patch 生成审批记录 | `/approve-patch ...` | 生成 ApprovalRecord id |
| 08-018 | diff show 可读 | `/diff show <id>` | 展示 PackageDiff 摘要 |
| 08-019 | diff validate 可用 | `/diff validate <id>` | 能发现计划外变更 |
| 08-020 | release 输出明确 | `/release ...` | 展示版本、channel、rollback target |
| 08-021 | 所有关键命令支持 JSON | `--json` | 输出机器可读 JSON / JSONL，无 Rich 样式 |
| 08-022 | 人类输出和 JSON 分离 | `--json` / 无 `--json` | 两种输出互不污染 |
| 08-023 | 错误码明确 | 任意失败命令 | 返回非 0 exit code 和结构化错误 |
| 08-024 | 普通命令和斜杠命令共用服务 | create / validate / test | 行为一致，不出现两套业务逻辑 |
| 08-025 | 不做全屏 TUI | shell 使用过程 | 保持单列对话流，不进入复杂 dashboard |

## 不做

```text
1. 不做 Web 页面。
2. 不做桌面端。
3. 不做复杂 TUI。
4. 不把核心业务逻辑写在 CLI command 中。
5. 不把斜杠命令做成另一套独立业务实现。
```
