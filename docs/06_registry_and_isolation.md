# 06. Registry 与 AgentInstance 进程隔离

## 目标

实现第一版文件系统 Registry 和 AgentInstance 进程隔离。

这一阶段的核心原则：

```text
AgentFactory 负责生产、登记、启动、升级 Agent。
AgentInstance 启动后像一个独立运行的小程序。
Runtime、ToolRouter、工具实现、MCPClientManager、ContextManager、MemoryManager、PolicyEngine 都在 AgentInstance 自己的进程内。
```

也就是说，第一版不是“主进程代理所有工具调用”，而是：

```text
AgentFactory / Control Process
  ↓ 启动
AgentInstance Process
  ├── WorkflowRuntime / GraphRuntime
  ├── ToolRouter
  ├── ToolExecutor
  ├── Tool implementations
  ├── MCPClientManager
  ├── ContextManager
  ├── MemoryManager
  ├── PolicyEngine
  ├── CheckpointManager
  └── TraceLogger
```

## Registry 定位

Registry 是框架的资产目录和版本账本，不是每次运行调用的中转站。

Registry 负责：

```text
1. 记录 AgentPackage。
2. 记录 Capability。
3. 记录版本状态。
4. 记录 HarnessReport。
5. 记录 Trace 索引。
6. 记录 PatchPlan / ApprovalRecord / PackageDiff / Release。
7. 为 AgentInstance 启动提供 package snapshot。
```

AgentInstance 启动时读取一个确定的 package snapshot。运行过程中，它在自己的进程内根据该 snapshot 调用工具、MCP、上下文和记忆。

## 文件系统 Registry

第一版目录：

```text
.agentfactory_registry/
├── agents/
│   └── customer-service-agent/
│       └── 1.0.0/
│           ├── package/
│           ├── record.yaml
│           └── manifest.yaml
├── capabilities/
├── tools/
├── mcp/
├── contexts/
├── memories/
├── models/
├── policies/
├── harness_reports/
├── traces/
├── patch_plans/
├── package_diffs/
├── approvals/
├── releases/
└── instances/
```

每条记录至少包含：

```text
id
type
name
version
status
created_at
updated_at
source_path
hash
refs
```

## Registry API

业务代码不能直接散落读写 Registry 文件，必须通过 Registry API。

```python
class RegistryBackend(Protocol):
    def put(self, record: RegistryRecord) -> None: ...
    def get(self, ref: RegistryRef) -> RegistryRecord: ...
    def list(self, query: RegistryQuery) -> list[RegistryRecord]: ...
    def update_status(self, ref: RegistryRef, status: RegistryStatus) -> None: ...
```

第一版实现：

```text
FileSystemRegistryBackend
AgentRegistry
CapabilityRegistry
HarnessReportRegistry
TraceRegistry
PatchPlanRegistry
ApprovalRegistry
PackageDiffRegistry
ReleaseRegistry
InstanceRegistry
```

## AgentInstance 自包含进程

正式定义：

```text
一个 AgentInstance 对应一个 OS 进程。
```

一个 AgentPackage 可以创建多个 AgentInstance：

```text
customer-service-agent:1.0.0
├── instance dev-001
├── instance test-001
└── instance prod-001
```

每个实例进程独立加载自己的 package snapshot，并在进程内完成运行。

## AgentInstance 进程内部结构

```text
AgentInstance Process
├── AgentRuntime
│   ├── RuntimeSelector
│   ├── WorkflowRuntime
│   └── GraphRuntime
├── ToolRouter
├── ToolExecutor
├── tools/
├── MCPClientManager
├── ContextManager
├── MemoryManager
├── PolicyEngine
├── CheckpointManager
├── TraceLogger
└── LocalRuntimeRegistryView
```

说明：

```text
1. ToolRouter 在 AgentInstance 进程内。
2. ToolExecutor 在 AgentInstance 进程内。
3. 工具实现代码在 AgentInstance 进程内执行。
4. MCPClientManager 在 AgentInstance 进程内管理该实例需要的 MCP 连接。
5. ContextManager 和 MemoryManager 在 AgentInstance 进程内运行。
6. PolicyEngine 在 AgentInstance 进程内执行权限和风险检查。
7. TraceLogger 可以写本实例 trace，并由 Registry 建索引。
```

## Control Process 职责

AgentFactory / Control Process 负责生命周期管理，而不是工具调用代理。

```text
1. 读取 Registry。
2. 找到 AgentPackage 版本。
3. 创建 AgentInstanceRecord。
4. 准备 package snapshot。
5. 启动 AgentInstance 进程。
6. 停止 AgentInstance 进程。
7. 查看实例状态。
8. 收集或索引 trace / report。
9. 执行升级、发布、回滚。
```

Control Process 不做：

```text
1. 不代理每一次工具调用。
2. 不代理每一次 MCP 调用。
3. 不共享 AgentInstance 的 Python 全局状态。
4. 不直接修改运行中 AgentInstance 的内部状态。
```

## LocalRuntimeRegistryView

AgentInstance 不能随意读取整个 Registry。启动时由 Control Process 提供该实例需要的 package snapshot 和能力清单。

`LocalRuntimeRegistryView` 是实例进程内的只读视图：

```text
1. 当前 AgentPackage。
2. 当前版本允许的 Capability。
3. 当前版本允许的 Tool。
4. 当前版本允许的 MCP binding。
5. 当前版本 Policy。
6. 当前实例 namespace。
```

这样 AgentInstance 可以独立运行，但不会越权读取其他 Agent 或其他版本的 Registry 内容。

## Namespace

每个 AgentInstance 必须有独立 namespace：

```text
agent:{agent_name}:version:{version}:instance:{instance_id}:context
agent:{agent_name}:version:{version}:instance:{instance_id}:memory
agent:{agent_name}:version:{version}:instance:{instance_id}:trace
agent:{agent_name}:version:{version}:instance:{instance_id}:checkpoint
agent:{agent_name}:version:{version}:instance:{instance_id}:mcp
```

规则：

```text
1. 不同 AgentInstance 不能共享 memory namespace。
2. 不同 AgentInstance 不能共享 checkpoint namespace。
3. MCP 连接按实例隔离。
4. Trace 按实例隔离。
5. Context cache 按实例隔离。
```

## InstanceRecord

```python
class InstanceRecord(BaseModel):
    instance_id: str
    agent_name: str
    package_version: str
    runtime_type: Literal["workflow_runtime", "graph_runtime"]
    process_id: int | None = None
    status: InstanceStatus
    namespace: InstanceNamespace
    package_hash: str
    created_at: datetime
    started_at: datetime | None = None
    stopped_at: datetime | None = None
```

状态：

```text
Created
Starting
Running
Interrupted
Stopping
Stopped
Failed
```

## Trace 写入

第一版允许 AgentInstance 进程自己写 trace JSONL，但必须写入自己的 namespace 路径。

推荐：

```text
.agentfactory_registry/traces/
└── customer-service-agent/
    └── 1.0.0/
        └── dev-001/
            └── trace-xxx.jsonl
```

规则：

```text
1. 每个实例只写自己的 trace 目录。
2. TraceRegistry 负责建立索引。
3. TraceLogger 必须追加写，不覆盖旧 trace。
4. 未来可增强为主控集中收集或 OpenTelemetry adapter。
```

## CLI 命令

```bash
agentfactory registry list agents
agentfactory registry list capabilities
agentfactory registry show agent customer-service-agent --version 1.0.0

agentfactory run-agent customer-service-agent --version 1.0.0 --instance dev-001

agentfactory instance list
agentfactory instance show dev-001
agentfactory instance stop dev-001
agentfactory instance logs dev-001
```

斜杠命令：

```text
/registry list agents
/registry list capabilities
/registry show agent customer-service-agent --version 1.0.0
/run customer-service-agent --version 1.0.0 --instance dev-001
/instance list
/instance show dev-001
/instance stop dev-001
/instance logs dev-001
```

## 必做任务

```text
1. 实现 FileSystemRegistryBackend。
2. 实现 AgentRegistry。
3. 实现 CapabilityRegistry。
4. 实现 HarnessReportRegistry。
5. 实现 TraceRegistry。
6. 实现 ReleaseRegistry。
7. 实现 InstanceRegistry。
8. 实现 InstanceManager。
9. 实现 ProcessRuntime。
10. 实现 package snapshot 准备。
11. 实现 LocalRuntimeRegistryView。
12. 实现 AgentInstance 进程启动和停止。
13. 实现实例 namespace 生成。
14. 实现实例 trace 目录隔离。
```

## 验收标准

```text
1. register-agent 能把通过 AgentHarness 的包写入 Registry。
2. 未通过 AgentHarness 的包不能进入 Available。
3. run-agent 能启动独立 AgentInstance 进程。
4. AgentInstance 进程内包含 ToolRouter / ToolExecutor / MCPClientManager。
5. 工具调用不需要 Control Process 代理。
6. 实例异常退出不影响 Control Process。
7. 不同 instance 的 memory namespace 不同。
8. 不同 instance 的 trace 目录不同。
9. instance list 能看到运行中实例。
10. instance stop 能停止指定实例。
```

## 不做

```text
1. 不做容器隔离。
2. 不做 Kubernetes。
3. 不做远程 Registry。
4. 不做多机调度。
5. 不做主进程代理所有工具调用。
6. 不做跨实例共享 Python 对象。
```

