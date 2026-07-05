# 多 Agent 协作设计文档

## 1. 目标

多 Agent 协作提供一种群聊式工作台体验：用户提出复杂目标后，由一个主 Agent 负责目标拆解、任务分配、过程监控、审批处理和最终验收；多个子 Agent 在各自隔离的运行空间内完成被分配的任务，并将进度、阻塞、结果和产物投影回协作会话。

第一版目标不是实现完全自治的多 Agent 社会，而是实现一个可控、可恢复、可审计的协作闭环：

- 用户和主 Agent 在协作会话中交互。
- 主 Agent 是唯一调度者。
- 子 Agent 之间互不可见。
- 子 Agent 只接收主 Agent 明确传入的任务、输入和交付标准。
- 主 Agent 实时监控子 Agent 执行状态。
- 审批和追问由协作会话的硬切换模式决定：用户亲自处理，或主 Agent 代理处理。
- 主 Agent 负责验收子 Agent 结果，并决定返工、接受或汇总交付。

## 2. 非目标

第一版明确不做以下能力：

- 子 Agent 之间直接通信。
- 子 Agent 自行拉起其他 Agent。
- 多个主 Agent 同时编排。
- 可视化 DAG 编辑器。
- 所有 Agent 共享同一个上下文窗口。
- 子 Agent 读取其他子 Agent 的会话、记忆、工作区或工具调用记录。
- 主 Agent 代理模式绕过系统级高风险权限策略。

这些能力可以在底层模型稳定后再讨论，但不应进入第一版。

## 3. 核心模型

### 3.1 群聊式体验，星型拓扑

前端表现为群聊：

```text
用户：我要做一份行业调研 PPT。
主 Agent：我将任务拆成调研、数据整理、PPT 生成和验收。
Research Agent：已接收任务，正在检索资料。
Data Agent：等待调研报告。
Research Agent：提交 research_report.md。
主 Agent：调研结果通过，分配给 Data Agent。
Data Agent：提交 charts.xlsx。
PPT Agent：已接收任务，正在生成 deck.pptx。
主 Agent：最终验收完成。
```

但后端拓扑不是群网，而是星型：

```text
用户 <-> 主 Agent <-> 子 Agent A
              <-> 子 Agent B
              <-> 子 Agent C
```

子 Agent A/B/C 之间没有直接边。群聊里看到的子 Agent 消息是事件投影，不代表它们共享同一条上下文。

### 3.2 可见性边界

主 Agent 可见：

- 用户目标与后续补充。
- 协作会话状态。
- 子任务列表。
- 子任务交付标准。
- 每个子 Agent 的任务状态、进度、阻塞、结果摘要和产物引用。
- 主 Agent 自己的验收意见、返工要求和最终汇总。

子 Agent 可见：

- 自己被分配的任务。
- 主 Agent 给自己的交付标准。
- 主 Agent 显式传入的上下文摘要。
- 主 Agent 显式传入的文件、资源、artifact 引用。
- 自己的私有会话、私有工作区、私有工具调用状态。

子 Agent 不可见：

- 其他子 Agent 的存在。
- 其他子 Agent 的任务、状态、输出、工作区、记忆、工具调用。
- 协作会话完整历史。
- 主 Agent 的完整内部上下文。
- 用户未显式授权传入的外部资源。

## 4. 角色职责

### 4.1 用户

用户负责提出目标、补充要求、切换审批模式、决定是否接受最终交付。

用户可以在协作过程中：

- 追加约束。
- 暂停或取消协作。
- 修改主 Agent 的任务分配。
- 接管审批。
- 要求某个子任务返工。
- 查看子 Agent 的完整会话或产物。

### 4.2 主 Agent

主 Agent 是协作控制器，不只是普通聊天助手。

主 Agent 负责：

- 理解用户目标。
- 拆解子任务。
- 选择合适的子 Agent。
- 为每个子任务生成交付标准。
- 下发任务。
- 监控子 Agent 状态。
- 处理或转交子 Agent 的审批与追问。
- 验收子 Agent 输出。
- 要求返工或重分配。
- 汇总最终交付。

主 Agent 不应该：

- 直接修改子 Agent 私有状态。
- 绕过子 Agent 自身工具权限。
- 把一个子 Agent 的完整上下文泄露给另一个子 Agent。
- 在用户审批模式下替用户批准。

### 4.3 子 Agent

子 Agent 是隔离执行者。

子 Agent 负责：

- 接收主 Agent 下发的任务。
- 按交付标准执行。
- 阶段性汇报进度。
- 在阻塞时向主 Agent 提问。
- 提交结果摘要和产物引用。

子 Agent 不负责：

- 理解协作全局。
- 选择其他子 Agent。
- 修改任务图。
- 与其他子 Agent 协商。
- 直接向用户索要信息。

## 5. 审批模式

协作会话有一个硬切换字段：

```json
{
  "approval_mode": "user_controlled"
}
```

允许值：

- `user_controlled`
- `main_agent_delegated`

### 5.1 用户审批模式

`user_controlled` 表示所有审批、追问和关键决策都交给用户。

适用场景：

- 高风险工具调用。
- 文件删除或覆盖。
- 发布、发送、提交等外部写操作。
- 成本较高的模型调用。
- 用户要求强控制的任务。

行为规则：

- 子 Agent 的审批请求先到主 Agent。
- 主 Agent 不能直接批准，只能整理上下文并转交用户。
- 用户决策后，主 Agent 将结果转回子 Agent。
- 主 Agent 可以给出建议，但不替用户执行决策。

### 5.2 主 Agent 代理模式

`main_agent_delegated` 表示主 Agent 可以在协作目标范围内替用户处理子 Agent 的审批和追问。

适用场景：

- 用户希望自动推进。
- 多个低风险子任务并发执行。
- 子 Agent 需要补充细节，但主 Agent 已经能从全局目标判断。
- 主 Agent 需要验收和返工。

行为规则：

- 子 Agent 的审批请求先到主 Agent。
- 主 Agent 根据目标、交付标准、权限策略决定批准、拒绝或修改输入。
- 主 Agent 可以回答子 Agent 的澄清问题。
- 主 Agent 可以要求子 Agent 返工。
- 系统级权限策略仍然优先，主 Agent 代理不能越权。

### 5.3 模式切换

审批模式可以由用户手动切换，但切换只影响后续审批事件。

不回溯修改已经发出的审批决策。

切换时应在协作消息流中记录系统事件：

```text
系统：审批模式已切换为主 Agent 代理。
```

## 6. 任务协议

主 Agent 分配给子 Agent 的任务必须结构化，而不是只发送一句自然语言。

推荐任务载荷：

```json
{
  "task_id": "task_...",
  "assignee_agent_id": "research_agent",
  "task": "调研近三年企业知识库 RAG 的主流方案",
  "delivery_standard": {
    "format": "markdown_report",
    "must_include": [
      "技术路线",
      "代表产品",
      "优缺点",
      "引用来源"
    ],
    "quality_bar": "信息要可追溯，避免泛泛总结"
  },
  "visible_context": {
    "user_goal": "制作一份行业调研 PPT",
    "style": "简约、商务、结论清晰"
  },
  "input_artifacts": [],
  "expected_outputs": [
    "summary",
    "artifact_refs"
  ]
}
```

字段说明：

- `task_id`：协作任务 ID。
- `assignee_agent_id`：被分配的子 Agent。
- `task`：自然语言任务描述。
- `delivery_standard`：交付标准，主 Agent 后续按此验收。
- `visible_context`：主 Agent 允许子 Agent 看到的上下文摘要。
- `input_artifacts`：显式传入的文件或产物引用。
- `expected_outputs`：期望返回的结果类型。

## 7. 子 Agent 状态流

子 Agent 执行过程中需要投影事件到协作会话。

推荐状态：

- `assigned`：任务已分配。
- `accepted`：子 Agent 已接收。
- `planning`：子 Agent 正在规划。
- `working`：子 Agent 正在执行。
- `tool_calling`：子 Agent 正在调用工具。
- `progress`：阶段性进展。
- `blocked`：阻塞，需要主 Agent 或用户决策。
- `submitted`：提交结果，等待主 Agent 验收。
- `revision_requested`：主 Agent 要求返工。
- `completed`：主 Agent 验收通过。
- `failed`：任务失败。
- `cancelled`：任务取消。

这些状态应统一映射到协作消息流和右侧任务状态栏。

## 8. 结果验收

子 Agent 提交结果后，不直接视为完成。主 Agent 必须验收。

子 Agent 返回：

```json
{
  "task_id": "task_...",
  "status": "submitted",
  "summary": "已完成企业知识库 RAG 调研，产出 Markdown 报告。",
  "artifact_refs": [
    {
      "type": "markdown",
      "title": "RAG 调研报告",
      "path": "workdir/research_report.md"
    }
  ],
  "notes": "引用来源已整理在报告末尾。"
}
```

主 Agent 验收结果：

```json
{
  "task_id": "task_...",
  "decision": "accepted",
  "review": "报告覆盖技术路线、代表产品和优缺点，满足交付标准。"
}
```

或要求返工：

```json
{
  "task_id": "task_...",
  "decision": "revision_requested",
  "review": "缺少国内代表产品对比，请补充至少 5 个案例。"
}
```

## 9. 数据模型

### 9.1 协作会话

```text
collaboration_sessions
- collaboration_id
- title
- main_agent_package_id
- main_agent_session_id
- approval_mode
- status
- created_at
- updated_at
```

说明：

- `main_agent_package_id`：主 Agent 包。
- `main_agent_session_id`：主 Agent 自己的会话。
- `approval_mode`：审批模式。
- `status`：`running`、`completed`、`failed`、`cancelled`。

### 9.2 协作成员

```text
collaboration_members
- member_id
- collaboration_id
- role
- package_id
- display_name
- status
- joined_at
```

`role`：

- `main`
- `worker`

第一版只有一个 `main`，多个 `worker`。

### 9.3 协作任务

```text
collaboration_tasks
- task_id
- collaboration_id
- parent_task_id
- assignee_package_id
- assignee_session_id
- task_text
- delivery_standard_json
- visible_context_json
- input_artifacts_json
- status
- result_summary
- result_payload_json
- artifact_refs_json
- created_at
- updated_at
```

### 9.4 协作消息投影

```text
collaboration_messages
- message_id
- collaboration_id
- speaker_type
- speaker_package_id
- message_kind
- content
- task_id
- event_ref
- created_at
```

`speaker_type`：

- `user`
- `main_agent`
- `worker_agent`
- `system`

`message_kind`：

- `chat`
- `task_assigned`
- `progress`
- `tool_event`
- `approval_requested`
- `approval_resolved`
- `result_submitted`
- `review`
- `final_delivery`

### 9.5 协作审批

```text
collaboration_approvals
- approval_id
- collaboration_id
- task_id
- requested_by_package_id
- decision_owner
- approval_type
- request_payload_json
- status
- decision_payload_json
- created_at
- resolved_at
```

`decision_owner`：

- `user`
- `main_agent`

## 10. 运行时隔离

每个子 Agent 继续使用自己的运行态：

- 独立 runtime instance。
- 独立 session。
- 独立 checkpoint。
- 独立 workdir。
- 独立 context policy。
- 独立 memory scope。
- 独立 tool permission。
- 独立 scheduler。

协作会话不直接合并这些状态，只保存引用。

主 Agent 可以通过协作服务读取子任务状态和结果摘要，但不能直接读子 Agent 私有 checkpoint。

## 11. 工作区与产物

建议工作区分三层：

```text
agent_private_workspace/
collaboration_shared_workspace/
artifact_store/
```

规则：

- 子 Agent 默认只写自己的私有工作区。
- 需要共享的文件由主 Agent 显式加入共享区。
- 最终交付产物进入 artifact store。
- 群聊里展示 artifact 引用，不直接塞大文本。

## 12. 前端交互

### 12.1 协作页面

新增协作入口，页面主体是群聊消息流。

左侧：

- 协作会话列表。
- 新建协作。
- 最近协作。

中间：

- 群聊式消息流。
- 用户输入框。
- 主 Agent 消息。
- 子 Agent 进度投影。
- 审批卡片。
- 结果卡片。

右侧：

- 成员列表。
- 任务列表。
- 审批模式切换。
- 产物列表。
- 当前验收状态。

### 12.2 消息展示

每条消息需要明确身份：

- 用户。
- 主 Agent。
- 子 Agent。
- 系统。

子 Agent 消息应带任务上下文：

```text
Research Agent · 资料调研
正在检索近三年 RAG 方案资料。
```

### 12.3 审批模式切换

右侧状态栏提供硬切换：

- 用户亲自处理。
- 主 Agent 代理处理。

切换后需要写入协作会话状态，并投影一条系统消息。

## 13. 后端服务边界

建议新增 `collaboration_system` 模块，不把协作逻辑塞进现有 runtime manager。

推荐模块：

```text
agent_factory/collaboration_system/
- schema.py
- store.py
- service.py
- orchestrator.py
- events.py
- projections.py
```

职责：

- `schema.py`：协作会话、任务、消息、审批模型。
- `store.py`：SQLite 持久化。
- `service.py`：创建会话、切换模式、写消息、查状态。
- `orchestrator.py`：驱动主 Agent 分配任务和监控结果。
- `events.py`：协作事件类型定义。
- `projections.py`：把 runtime event 投影为群聊消息。

## 14. 内置工具

主 Agent 需要可调用的系统工具：

- `list_collaboration_agents`
- `assign_agent_task`
- `get_agent_task_status`
- `review_agent_result`
- `request_agent_revision`
- `cancel_agent_task`
- `read_agent_task_result`

子 Agent 不需要看到这些全局工具。

子 Agent 只需要普通运行工具和自身 package 工具。

## 15. 事件流

协作事件需要进入前端 SSE。

建议事件类型：

- `collaboration_session_created`
- `collaboration_session_updated`
- `collaboration_message_created`
- `collaboration_task_created`
- `collaboration_task_updated`
- `collaboration_approval_requested`
- `collaboration_approval_resolved`
- `collaboration_artifact_created`
- `collaboration_completed`
- `collaboration_failed`

事件 payload 应包含：

- `collaboration_id`
- `task_id`
- `speaker`
- `status`
- `message`
- `artifact_refs`

## 16. 第一版流程

### 16.1 新建协作

1. 用户点击新建协作。
2. 选择主 Agent。
3. 选择审批模式。
4. 输入目标。
5. 后端创建 `collaboration_session`。
6. 主 Agent session 初始化。

### 16.2 主 Agent 拆任务

1. 主 Agent 读取用户目标。
2. 主 Agent 查询可用子 Agent。
3. 主 Agent 生成任务拆解。
4. 前端展示任务计划。

### 16.3 分配子任务

1. 主 Agent 调用 `assign_agent_task`。
2. 协作服务创建 `collaboration_task`。
3. 目标子 Agent 创建或复用独立 session。
4. 子 Agent 异步运行。
5. 前端显示子 Agent 已接收任务。

### 16.4 子 Agent 执行

1. 子 Agent 在自己的 runtime 中执行。
2. runtime event 投影到协作消息。
3. 如果遇到审批或追问，进入协作审批流程。
4. 子 Agent 提交结果。

### 16.5 主 Agent 验收

1. 主 Agent 读取子任务结果摘要和 artifact 引用。
2. 按交付标准验收。
3. 通过则标记完成。
4. 不通过则要求返工。

### 16.6 最终交付

1. 所有必要子任务完成。
2. 主 Agent 汇总最终交付。
3. 前端显示最终结果与产物。
4. 协作会话进入完成状态。

## 17. 权限规则

权限判断顺序：

1. 系统最高风险策略。
2. 子 Agent 自身工具权限。
3. 协作会话审批模式。
4. 主 Agent 代理决策或用户决策。

主 Agent 代理模式不能跳过 1 和 2。

也就是说：

- 子 Agent 工具权限拒绝的操作，主 Agent 不能批准。
- 系统强制用户确认的操作，主 Agent 不能代签。
- 主 Agent 代理只在允许代理的审批范围内生效。

## 18. 失败与恢复

协作必须可恢复。

需要持久化：

- 协作会话。
- 任务状态。
- 消息投影。
- 审批状态。
- 子 Agent session 引用。
- artifact 引用。

刷新页面后：

- 群聊消息流可恢复。
- 每个子任务状态可恢复。
- 正在运行的子 Agent 状态可重新查询。
- 未完成审批可继续显示。

## 19. 与现有系统的关系

现有能力继续保留：

- Agent package runtime。
- 子 Agent 实例初始化/关闭。
- 子 Agent 独立会话。
- 工具权限。
- 上下文窗口配置。
- 定时任务分区。
- 工作区分区。

协作系统不替代这些能力，而是在上层组合它们。

## 20. 第一版验收标准

第一版完成的标准：

- 可以创建协作会话。
- 可以选择一个主 Agent。
- 可以选择审批模式。
- 主 Agent 可以拆任务。
- 主 Agent 可以把任务分配给已发布子 Agent。
- 子 Agent 互不可见。
- 子 Agent 独立执行并实时投影进度。
- 用户能看到群聊式协作消息。
- 主 Agent 可以验收子 Agent 结果。
- 主 Agent 可以要求返工。
- 子 Agent 产物能在协作会话中引用。
- 刷新后协作会话、任务、消息、审批状态可恢复。

## 21. 推荐落地顺序

第一阶段完成协作骨架：

1. 协作 SQLite 表。
2. 协作 API。
3. 协作 SSE 事件。
4. 协作页面。
5. 手动创建主 Agent 协作会话。

第二阶段完成任务分配闭环：

1. `list_collaboration_agents`。
2. `assign_agent_task`。
3. 子 Agent 异步运行。
4. runtime event 投影。
5. 子任务结果提交。

第三阶段完成主 Agent 监控与验收：

1. 主 Agent 读取任务状态。
2. 主 Agent 验收结果。
3. 主 Agent 要求返工。
4. 主 Agent 最终汇总。

第四阶段完成审批模式：

1. 用户审批模式。
2. 主 Agent 代理模式。
3. 审批状态恢复。
4. 高风险权限边界。

## 22. 结论

多 Agent 协作第一版应采用：

> 群聊式 UI，星型运行拓扑，单主 Agent 编排，子 Agent 严格隔离，审批模式硬切换，结果由主 Agent 验收后交付。

这个设计可以满足用户对“群聊协作”的直觉，同时保持运行态、上下文、权限、记忆和工作区的工程边界清晰。
