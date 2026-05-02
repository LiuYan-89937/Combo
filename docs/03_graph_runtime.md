# 03. Runtime 执行模型

## 目标

实现 AgentPackage 的最小运行时，让通过校验的 Agent 可以真正执行。

Runtime 不固定为单一 Graph 模型，而是根据 Agent 场景选择执行模式：

```text
1. 流程固定、步骤稳定、业务链路明确：
   使用 WorkflowRuntime，一环扣一环顺序执行。

2. 场景复杂、多轮变化、状态跳转多、分支多：
   使用 GraphRuntime，通过 GraphState 和条件路由进行状态流转。
```

第一版先在同一个 Runtime 层内实现这两类执行模式的最小闭环，不做多进程隔离，多进程放到第 06 阶段。

## 执行模型选择

AgentPackage 可以在 `runtime.yaml` 或 `workflow.yaml` 中声明执行模型：

```yaml
runtime:
  type: "workflow_runtime"
```

或：

```yaml
runtime:
  type: "graph_runtime"
```

选择建议：

| 场景 | 推荐 Runtime | 说明 |
| --- | --- | --- |
| 固定审批流程 | `workflow_runtime` | 顺序稳定，容易测试和追踪 |
| 标准客服流程 | `workflow_runtime` 或 `graph_runtime` | 简单客服用 workflow，复杂多意图客服用 graph |
| 多工具、多分支任务 | `graph_runtime` | 需要根据状态动态跳转 |
| 长任务、多轮协作 | `graph_runtime` | 需要 checkpoint、interrupt、resume |
| 高风险操作链 | `workflow_runtime` | 每一步明确确认和审计 |

第一版可以先让 `runtime.type` 显式指定，不做自动判断。后续可以让 `AgentFactoryAgent` 根据需求复杂度推荐 Runtime。

## 核心模块

```text
agent_factory/runtime/
├── runtime_selector.py
├── base_runtime.py
├── workflow_runtime.py
├── graph_runtime.py
├── node.py
├── edge.py
├── route.py
├── state.py
├── result.py
├── event_bus.py
├── checkpoint.py
├── interrupt.py
├── condition_evaluator.py
└── upgrade_detector.py
```

## 核心对象

### RuntimeSelector

`RuntimeSelector` 根据 `runtime.type` 创建运行时：

```python
class RuntimeSelector:
    def select(self, package: AgentPackage) -> BaseRuntime:
        ...
```

### BaseRuntime

```python
class BaseRuntime(Protocol):
    async def run(
        self,
        package: AgentPackage,
        input_message: AgentInput,
        context: RuntimeContext,
    ) -> AgentRunResult:
        ...
```

### GraphState

状态对象可以包含动态 `values`，但不能裸 dict 到处传，必须封装在 `GraphState` 对象里。

```python
class GraphState(BaseModel):
    values: dict[str, Any]
    current_node: str | None = None
    history: list[NodeExecutionRecord] = []
    checkpoints: list[CheckpointRecord] = []
    metadata: GraphMetadata
```

### NodeResult

```python
class NodeResult(BaseModel):
    next_state: GraphState
    status: Literal["success", "failed", "interrupted"]
    output_keys: list[str] = []
    interrupt: InterruptRequest | None = None
    error: RuntimeErrorInfo | None = None
```

### RuntimeContext

```python
class RuntimeContext(BaseModel):
    agent_name: str
    instance_id: str | None = None
    session_id: str | None = None
    package_version: str
    registry: RegistryClient
    model_service: ModelService
    context_manager: ContextManager
    tool_router: ToolRouter
    mcp_manager: MCPClientManager
    memory_manager: MemoryManager
    policy_engine: PolicyEngine
    trace_logger: TraceLogger
```

## WorkflowRuntime

`WorkflowRuntime` 面向固定流程，节点按 workflow 中定义的顺序稳定执行。

适用场景：

```text
1. 表单式流程。
2. 审批式流程。
3. 固定客服流程。
4. 高风险操作链。
5. 测试和审计要求强的流程。
```

执行逻辑：

```text
1. 从 start_node 开始。
2. 按 edge 顺序寻找下一个节点。
3. 遇到 route 时才执行条件判断。
4. 每一步都写 trace。
5. 遇到 interrupt 时暂停。
6. 到 end_node 时结束。
```

WorkflowRuntime 的特点：

```text
1. 可预测。
2. 易测试。
3. 审计清晰。
4. 不适合复杂动态跳转。
```

## GraphRuntime

`GraphRuntime` 面向复杂状态流转，节点通过 `GraphState` 和条件路由动态选择下一步。

适用场景：

```text
1. 多意图对话。
2. 多工具组合。
3. 多轮任务状态变化。
4. 出错后重试或降级。
5. 运行中可能触发 UpgradeRequest。
```

执行逻辑：

```text
1. 从 start_node 开始。
2. 节点读写 GraphState。
3. route 根据 condition 选择下一节点。
4. Model、Tool、MCP、Memory、Context 都通过 RuntimeContext 访问。
5. 每一步都写 trace。
6. 超过 max_steps_per_turn 时失败。
7. 遇到 interrupt 时保存 checkpoint 并暂停。
```

GraphRuntime 的特点：

```text
1. 灵活。
2. 适合复杂多变场景。
3. 对校验和 trace 要求更高。
4. 需要防循环和状态污染。
```

## 基础节点

第一版两种 Runtime 共用同一套节点抽象。

```text
input
load_context
intent_detect
route
retrieve
select_tool
call_tool
call_mcp
generate_response
update_memory
check_upgrade
generate_upgrade_request
human_confirm
human_handoff
end
```

节点原则：

```text
1. 节点之间只能通过 GraphState / RuntimeState 传递数据。
2. 节点不能直接访问全局 Registry。
3. call_tool 必须经过 ToolRouter。
4. call_mcp 必须经过 MCPClientManager。
5. intent_detect / generate_response 必须经过 ModelService。
6. LLM 只能产生 ToolCallProposal，不能直接执行工具。
7. 每个节点都必须写 trace。
8. route 判断必须记录命中的 condition。
9. high / critical 工具调用前必须支持 interrupt。
```

## 条件求值

Runtime 复用第 02 阶段的 `ConditionValidator`，不重新实现一套安全规则。

执行时使用 `SafeConditionEvaluator`：

```text
1. 输入是 GraphState.values。
2. 表达式必须已通过 AST 白名单校验。
3. 只能读取 state_schema 中声明过的字段。
4. 禁止函数调用、属性访问、import。
5. route 找不到匹配分支时视为 workflow error。
```

## Trace

第一版 trace 存 JSONL。

```python
class TraceSpan(BaseModel):
    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    agent_name: str
    instance_id: str | None = None
    node_id: str
    node_type: NodeType
    runtime_type: Literal["workflow_runtime", "graph_runtime"]
    started_at: datetime
    ended_at: datetime | None = None
    status: Literal["success", "failed", "interrupted"]
    input_keys: list[str] = []
    output_keys: list[str] = []
    error: RuntimeErrorInfo | None = None
```

## Checkpoint

第一版 checkpoint 只要求能记录，不要求复杂恢复。

```text
checkpoint_id
runtime_type
node_id
state_hash
state_snapshot
created_at
reason
```

恢复接口先保留：

```bash
agentfactory run-agent customer-service-agent --resume checkpoint-001
```

## Interrupt

`human_confirm` 和 `human_handoff` 先实现为暂停请求。

```python
class InterruptRequest(BaseModel):
    interrupt_id: str
    type: Literal["human_confirm", "human_handoff"]
    node_id: str
    reason: str
    risk_level: RiskLevel
    payload: dict[str, Any]
```

Runtime 遇到高风险工具时返回 `interrupted`，CLI 后续提示用户确认。

## 必做任务

```text
1. 实现 RuntimeSelector。
2. 实现 BaseRuntime。
3. 实现 WorkflowRuntime。
4. 实现 GraphRuntime。
5. 实现 GraphState / NodeResult / AgentRunResult。
6. 实现 RuntimeContext。
7. 实现 Node 抽象和基础节点。
8. 实现 SafeConditionEvaluator。
9. 实现 max_steps_per_turn 防死循环。
10. 实现 checkpoint 记录。
11. 实现 trace span 记录。
12. 实现 interrupt 占位，支持 human_confirm 的暂停和恢复接口。
13. intent_detect 第一版允许 rule / fixture / stub，不强制接 LLM。
```

## 验收标准

```text
1. run-agent 可以执行 workflow_runtime 的固定流程。
2. run-agent 可以执行 graph_runtime 的状态流转流程。
3. runtime.type 能正确选择 Runtime。
4. route 能根据 need_upgrade 进入 generate_upgrade_request。
5. route 找不到匹配分支时产生 workflow error。
6. high risk 工具调用前能触发 interrupt。
7. 每个节点执行后都有 trace span。
8. trace span 记录 runtime_type。
9. max_steps_per_turn 生效。
10. workflow error 能写入 trace。
```

## 不做

```text
1. 不做多进程隔离。
2. 不做完整记忆系统。
3. 不做真实外部工具写入。
4. 不做发布和回滚。
5. 不做自动 Runtime 选择，第一版由 runtime.type 显式指定。
6. 不做复杂 checkpoint 恢复，只保留接口和记录。
```
