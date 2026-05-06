# AgentFactory Refactor Progress

Source document: `agentfactory_refactor_architecture.md`

Last verified command:

```bash
uv run --extra dev pytest
```

Latest result: `133 passed, 3 skipped, 2 warnings`

Real model E2E command:

```bash
AGENTFACTORY_RUN_PROVIDER_SMOKE=1 uv run --extra dev pytest tests/test_model_provider_smoke.py
```

Latest real-model result: `2 passed, 1 skipped`。
通过项为自然语言端到端生成 AgentPackage、复杂 SQLite 资源型 AgentPackage；跳过项为极简 provider `ok` smoke，因为当前 provider 对该最小提示返回空 content。

## Phase 1: 清理旧 Runtime 方向

- [x] 标记旧 `WorkflowRuntime` 为 legacy outcome: hard-cut, no longer exported.
- [x] 停止继续扩展旧 Runtime.
- [x] 引入 explicit `langchain-core` / `langgraph` runtime dependencies.
- [x] 硬切为 `RuntimeGraphCompiler + TaskGraphCompiler`，并接入 `CompiledAgentRuntime`.

验收摘要: `tests/test_agent_instance_runtime.py` 覆盖无旧 Runtime 导出、生成包 runtime.yaml 使用 `langgraph_native` + `task_graph.yaml`、compiler 返回 LangGraph app。

## Phase 2: Model Layer / LangChain Runtime Adapter

- [x] Factory 模型调用仍使用统一 `ModelService`；Agent Runtime 不再依赖该层.
- [x] 实现 retry / timeout / exponential backoff.
- [x] 实现 empty content retry.
- [x] 实现 structured output parse/repair fallback.
- [x] Factory 经 `ModelService` 进入 runner；AgentInstance Runtime 已迁移为 LangChain-native chat model adapter，不再依赖旧自定义消息协议.

验收摘要: 现有 `tests/test_model_layer.py` 结构化输出、空内容重试、provider payload 测试通过。

## Phase 3: LangGraph-native AgentInstance Runtime

- [x] 编译 LangChain `BaseMessage` / `AIMessage` / `ToolMessage` runtime messages.
- [x] 编译 LangChain-compatible tools.
- [x] 实现 `PolicyWrappedToolNode`.
- [x] 由 `task_graph.yaml` 编译通用任务图，ControlGraph 注入 model/tool/observation/final 能力.
- [x] 接入 memory / trace / LangGraph native interrupt 基础链路.
- [x] `run-agent` 默认走新 Runtime，CLI 默认进程隔离；注入测试 runtime 时使用内联路径。
- [x] worker IPC 将 Runtime 业务状态作为 `AgentRunResult` 返回，`interrupted` / `needs_configuration` 不再被 shell 误判为进程失败。
- [x] Factory stream 完成后渲染自然语言 `ProductionSummary`，说明 Agent 能做什么、验证情况、剩余风险和 next steps。
- [x] Runtime 执行链移除旧自定义 runtime DTO 和 fixed ReAct 图，模型续写遵循 LangChain `AIMessage.tool_calls` / `ToolMessage` 序列。

验收摘要: `tests/test_agent_instance_runtime.py` 覆盖 TaskGraph compile、tool loop、native interrupt/resume；CLI/Harness/worker 全部改为 `AgentInstanceRuntime`。

## Phase 4: Context-first Factory Pipeline

- [x] `FactoryContextEnvelope` 已存在并继续作为模型调用 envelope.
- [x] `NodeContextCompiler` 已存在.
- [x] `DecisionLedger` / `EvidenceStore` 已存在.
- [x] `stage_history` 输出映射为文档 14 阶段名称.
- [x] 工厂节点通过 `FactoryNodeAccessPolicy` 获取投影 state，只能读取 node allow-list 中的 typed artifact/envelope 字段.
- [x] 工厂节点返回值通过 access policy merge，只能修改 node allow-list 中的字段.

验收摘要: `tests/test_factory_context.py` 覆盖 envelope 隔离；`tests/test_refactor_architecture.py` 覆盖 14 阶段进度名称和 tool-generation 节点无法读取 raw requirement/raw_model_data。

## Phase 5: Resource Setup 子流程

- [x] `ResourceNeedPlan` 已存在.
- [x] 新增 `ResourceResolverRegistry`.
- [x] 新增 local path / python package / system command / URL documentation / credential config / human approval resolvers；移除特化 SQLite resolver，数据库可达性与 schema 证据走环境 probe / 受控 shell。
- [x] `probe_environment` 会把 ResourceNeed resolver 输出追加到 evidence reports.
- [x] `ReadinessDecision` 已存在并接入生产图.
- [x] targeted clarification 保持最多 3 个选项.
- [x] readiness issue 存储结构化 `details`，不在环境探测层硬编码用户话术.
- [x] readiness clarification 通过结构化展示层面向用户改写；优先 task/small model 输出 summary/problem/impact/next_action，模型不可用时本地模板兜底.

验收摘要: `tests/test_refactor_architecture.py` 覆盖 credential resolver 不读取 secret，`UrlDocumentationResolver` 只读取显式 URL 且报告不保存网页正文。

## Phase 6: ToolBuildPipeline

- [x] ToolContract 先行的生成逻辑已存在.
- [x] 新增 `ToolBuildPipeline` / `ToolBuildReport` 聚合边界.
- [x] 新增 `ToolStateMachine` transition guard.
- [x] 代码生成、静态检查、测试生成、sandbox test 接入聚合流程.
- [x] 生产图仍保留逐节点 CLI 进度.
- [x] evidence repair loop 接入聚合流程，生成工具测试失败后最多 3 次 repair + rerun.

验收摘要: `tests/test_refactor_architecture.py` 覆盖 repair 两次后通过、状态推进到 `available`。

## Phase 7: Context Engineering

- [x] 新增 `RuntimeContextCompiler`.
- [x] 独立实现 `MessageWindowPolicy` / `SummaryPolicy` / `ToolObservationCompressor` / `VisibilityPolicy` / `ContextBudget` / `ContextPriority`.
- [x] 实现 `NodeStateReducer`，Runtime model/tool 节点只能修改允许字段.
- [x] 长对话触发 context compression，并把 memory summary 回注 system prompt.
- [x] `ToolResultEnvelope` observation 进入模型前由策略压缩/摘要化.
- [x] secret redaction 继续覆盖 prompt/trace/memory 关键路径.
- [x] 新增 LangGraph filesystem checkpointer，审批恢复路径记录 native resume event.
- [x] checkpointer 保存 LangGraph 中断状态，approval resume 不再重新询问模型，而是通过 `Command(resume=...)` 回到中断节点后执行工具并回注 `ToolMessage`.
- [x] Agent session memory 只写入 completed turn；interrupted/failed 运行状态不再作为普通 assistant 对话污染后续 prompt.
- [x] Harness 覆盖 context compression / visibility / native resume 断言.

## Phase 8: Harness / Registry / Release

- [x] Harness 通过 `AgentInstanceRuntime` 驱动.
- [x] Harness 支持 context visibility / compression / native resume 断言.
- [x] Registry 记录 `PackageProvenance`.
- [x] Registry 记录并检查 `PromotionGate`.
- [x] release available 前检查 gate.
- [x] UpgradeRequest / PatchPlan / ApprovalRecord / PackageDiff 生命周期接入 package lifecycle report 与 Registry provenance.

验收摘要: `tests/test_refactor_architecture.py` 覆盖高风险 PatchPlan 必须 approval、apply 后写入 upgrade lifecycle、Registry provenance 记录 upgrade_request/patch_plan/approval ids。

## Section 17 Acceptance

### Factory

- [x] 用户自然语言可以生成完整 AgentPackage: 真实模型 opt-in E2E 已通过.
- [x] 复杂资源型 Agent 会识别条件和资源: 真实模型 SQLite 资源型 E2E 已通过.
- [x] blocking / deferred / warning 分类清晰.
- [x] 澄清问题最多 3 个，并且只针对真实缺口.
- [x] external_config 是 env-like 极简结构.
- [x] 工具测试失败不会吞掉 summary.
- [x] 工具生成只基于契约和证据摘要.
- [x] Factory memory 与 Agent memory 隔离.

### Runtime

- [x] AgentInstance 使用 LangGraph-native ControlGraph + TaskGraph runtime.
- [x] 支持多轮 tool loop.
- [x] 支持链式工具调用.
- [x] `package.runtime.max_turns` 通过 LangGraph recursion/runtime turn guard 生效.
- [x] high risk 工具触发 interrupt.
- [x] `-yes` / `/run --yes` 可以恢复执行路径.
- [x] run-agent chat 支持持续对话.
- [x] session memory 跨 shell 使用 filesystem backend.
- [x] trace 包含 model/tool/final answer 基础事件.
- [x] Harness 可以驱动 AgentInstance runtime.
- [x] 长对话触发 context compression.
- [x] 工具 observation 压缩后回注模型.

### Safety

- [x] LLM 不能直接执行工具.
- [x] 工具必须经过 ToolRouter / PolicyWrappedToolNode.
- [x] PolicyEngine 负责审批和风险控制.
- [x] secret 不进入 trace/memory 的现有 redaction 路径.
- [x] shell/file 写入删除必须审查沿用 ControlledShellRunner.
- [x] sandbox 测试不污染真实资源.
- [x] hidden context 不进入模型 prompt 的基础路径.
- [x] native resume checkpoint metadata 不泄露 secret.

### Context

- [x] Factory 模型调用使用 FactoryContextEnvelope.
- [x] 工具生成节点禁止 raw webpage/raw secret 进入 prompt contract.
- [x] RuntimeGraphState 通过 RuntimeContextCompiler 生成节点可见上下文.
- [x] visible_to_model / visible_to_tools / hidden 基础生效.
- [x] 多轮历史、摘要、memory、tool observation 共同进入 prompt.
- [x] 每个 Runtime 节点只能通过 reducer 修改允许字段.
- [x] Harness 能断言上下文压缩、可见性和 native resume.
