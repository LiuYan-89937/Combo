# 02. 声明式规范与校验器

## 目标

实现 AgentPackage 的标准结构、Pydantic 模型、加载器和校验器。这个阶段的核心是让框架先能“读懂”和“拒绝错误的包”。

设计重点：

```text
1. YAML 是输入格式，不是内部数据结构。
2. 边界层可以短暂使用 raw mapping。
3. 进入核心逻辑后必须转换成强类型对象。
4. Runtime、Harness、Registry 不直接消费 dict。
5. 校验错误必须结构化，方便 CLI 和 --json 输出。
```

也就是说，第一版采用 **object-first** 原则：能用 Pydantic 对象、枚举、值对象表达的地方，不使用裸 dict。

## 核心模块

```text
agent_factory/specs/
├── agent_spec.py
├── building_primitives.py
├── base.py
├── context_spec.py
├── tool_spec.py
├── mcp_spec.py
├── workflow_spec.py
├── memory_spec.py
├── policy_spec.py
├── harness_spec.py
├── runtime_spec.py
├── version_spec.py
├── upgrade_spec.py
├── patch_plan_spec.py
├── approval_record_spec.py
├── package_diff_spec.py
└── base.py

agent_factory/package/
├── package_loader.py
├── package_validator.py
├── package_schema.py
├── condition_validator.py
├── patch_plan.py
├── patch_plan_validator.py
├── approval_record.py
├── approval_validator.py
├── package_diff.py
└── package_diff_validator.py
```

## 对象模型原则

### 1. 边界层 raw，核心层 object

允许：

```text
YAML 文件
  ↓
ruamel.yaml 解析为 raw mapping
  ↓
Pydantic model_validate
  ↓
AgentPackage 对象
  ↓
Validator / Harness / Runtime / Registry
```

不允许：

```text
YAML 文件
  ↓
dict
  ↓
dict 在 Runtime、Harness、Registry 中到处传
```

### 2. PackageLoader 返回 AgentPackage 对象

`PackageLoader` 不应该只返回一个大 dict，而应该返回聚合对象：

```python
class AgentPackage(BaseModel):
    root_path: Path
    instructions: InstructionSpec
    output: OutputSpec
    conversation: ConversationSpec
    run_context: RunContextSpec
    toolsets: ToolsetSpec
    knowledge: KnowledgeSpec
    guardrails: GuardrailSpec
    handoffs: HandoffSpec
    observability: ObservabilitySpec
    agent: AgentSpec
    workflow: WorkflowSpec
    context: ContextSpec
    tools: ToolSpec
    mcp: MCPSpec
    memory: MemorySpec
    policy: PolicySpec
    harness: HarnessSpec
    runtime: RuntimeSpec
    version: VersionSpec
    sources: PackageSources
```

`sources` 记录文件来源和 hash：

```python
class PackageSources(BaseModel):
    instructions_yaml: SourceFile
    output_yaml: SourceFile
    conversation_yaml: SourceFile
    run_context_yaml: SourceFile
    toolsets_yaml: SourceFile
    knowledge_yaml: SourceFile
    guardrails_yaml: SourceFile
    handoffs_yaml: SourceFile
    observability_yaml: SourceFile
    agent_yaml: SourceFile
    workflow_yaml: SourceFile
    context_yaml: SourceFile
    tools_yaml: SourceFile
    mcp_yaml: SourceFile
    memory_yaml: SourceFile
    policy_yaml: SourceFile
    harness_yaml: SourceFile
    runtime_yaml: SourceFile
    version_yaml: SourceFile
```

### 3. 嵌套结构也要对象化

例如 workflow 不使用节点 dict：

```python
class WorkflowSpec(BaseSpec):
    metadata: Metadata
    graph: WorkflowGraph
    state_schema: dict[str, StateFieldType]
    nodes: list[WorkflowNode]
    edges: list[WorkflowEdge]
    checkpoint: CheckpointSpec | None = None
    interrupts: list[InterruptSpec] = []

class WorkflowNode(BaseModel):
    id: str
    type: NodeType
    description: str | None = None
    input_keys: list[str] = []
    output_keys: list[str] = []
```

Instruction、Output、Conversation、RunContext、Toolset、Knowledge、Guardrail、Handoff、Observability、工具、MCP、Harness、PatchPlan 同理：顶层和关键子结构都要对象化。

### 4. Agent Building Primitives 是核心必需结构

第一版 AgentPackage 必须包含：

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
```

规则：

```text
1. Factory 创建 AgentPackage 时必须生成这些文件。
2. 手写 AgentPackage 缺少任一文件时 validator 返回 fatal issue。
3. 空能力也必须以空集合表达，例如 toolsets: []、targets: []、sources: []。
4. Runtime、Harness、Registry 不消费这些 YAML 的 raw dict，只消费 Pydantic 对象。
5. 正式 Agent 运行必须从 AgentPackage 目录加载，不把手动构造的内存对象当作 Factory 产物。
```

### 5. 可以保留少量 schema dict

以下字段可以保留为结构化 mapping，因为它们本身是 JSON Schema 或动态对象：

```text
Tool.input_schema
Tool.output_schema
OutputSpec.schema
HarnessCase.expected
Runtime metadata 扩展字段
MCP input_mapping / output_mapping
```

但这些字段也应该通过类型别名或值对象包起来：

```python
JsonSchema = dict[str, Any]
MappingExpression = dict[str, str]
```

不能用无语义的 `dict` 到处传递。

## 基础模型约定

所有 spec 继承统一基类：

```python
class BaseSpec(BaseModel):
    schema_version: str
    kind: str
    metadata: Metadata

    model_config = ConfigDict(
        extra="forbid",
        frozen=False,
        validate_assignment=True,
    )
```

通用对象：

```text
Metadata
SourceFile
ValidationIssue
ValidationReport
PackageRef
CapabilityRef
VersionRef
RiskLevel
CapabilityStatus
```

未知字段第一版默认禁止。这样可以尽早发现拼写错误和配置漂移。

## 必做任务

```text
1. 定义 AgentSpec、WorkflowSpec、ToolSpec、MCPSpec 等模型。
2. 定义 InstructionSpec、OutputSpec、ConversationSpec、RunContextSpec、ToolsetSpec、KnowledgeSpec、GuardrailSpec、HandoffSpec、ObservabilitySpec。
3. 定义 UpgradeRequestSpec、PatchPlanSpec、ApprovalRecordSpec、PackageDiffSpec。
4. 实现 PackageLoader，读取 AgentPackage 目录中的 YAML 文件并返回 AgentPackage 对象。
5. 实现 PackageValidator，检查必需文件、schema_version、kind、entrypoints。
6. 实现 ConditionValidator，校验受限 Python condition 表达式的 AST 白名单。
7. 校验 workflow edge 的 from/to 是否引用已存在节点。
8. 校验 workflow route 必须有兜底分支。
9. 校验 condition / when 引用字段必须存在于 state_schema。
10. 校验 high / critical 工具必须有 confirm_required。
11. 校验 mcp.yaml 必须存在，并包含标准 MCP 接入字段。
12. 校验 generated/ 和 patches/ 草稿区引用是否存在。
13. 实现 PatchPlanValidator、ApprovalValidator、PackageDiffValidator。
14. 输出 ValidationReport 对象，CLI 再负责渲染。
```

## 校验层级

```text
PackageLoader
  ↓
YAML parse
  ↓
Pydantic schema validation
  ↓
cross-file validation
  ↓
risk / policy validation
  ↓
ValidationReport
```

### Schema 校验

```text
1. 必需字段存在。
2. 字段类型正确。
3. 枚举值合法。
4. 未知字段禁止。
5. 版本格式合法。
```

### 跨文件语义校验

```text
1. agent.yaml entrypoints 指向文件必须存在。
2. instructions.yaml persona / goal 必须非空。
3. output.yaml structured output 必须有合法 JSON schema。
4. toolsets.yaml 中 exposed_tools 和 hidden_tools 不能重叠。
5. knowledge.yaml retriever 必须引用已存在 source。
6. guardrails.yaml stage / action 必须合法。
7. handoffs.yaml target id 必须唯一。
8. observability.yaml 不能允许记录 api_key / secret / authorization。
9. workflow 节点、边、路由引用必须一致。
10. workflow condition 引用字段必须存在于 state_schema。
11. tools.yaml 中工具必须被 policy 允许后才能运行。
12. mcp.yaml bindings 必须引用存在的 server。
13. harness.yaml 必须覆盖新增意图、工具、MCP、升级规则。
14. runtime.yaml namespace 必须包含 agent_id 和 instance_id 维度。
```

### 风险与策略校验

```text
1. tool_policy.default_allow 必须为 false。
2. high / critical 工具必须 confirm_required=true。
3. 有 side_effects 的工具必须声明 idempotent。
4. Factory 生成工具必须有 implementation.source=factory_generated。
5. generated_code 未审批不能 Available。
6. PatchPlan 中高风险 change 必须 approval_required=true。
7. PackageDiff 出现计划外变更不能进入 Harness。
```

## 受限 Python 表达式校验

第一版条件表达式只允许：

```text
Name
Constant
List / Tuple / Dict
BoolOp
UnaryOp
Compare
Subscript
Load
```

禁止：

```text
Call
Attribute
Import
Assign
Lambda
Comprehension
dunder name
```

表达式字段引用规则：

```text
1. Name 必须存在于 workflow.state_schema。
2. Subscript 的根对象必须存在于 workflow.state_schema。
3. 禁止使用未声明变量。
4. 禁止属性访问，例如 selected_tool.risk_level。
5. 使用 selected_tool['risk_level'] 这类下标访问。
```

## ValidationReport

校验器返回对象，不直接 print。

```python
class ValidationReport(BaseModel):
    ok: bool
    package_name: str | None = None
    issues: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []

class ValidationIssue(BaseModel):
    severity: Literal["error", "warning"]
    code: str
    message: str
    file: str | None = None
    path: str | None = None
    suggestion: str | None = None
```

CLI 人类可读输出示例：

```text
› /validate examples/customer_service_agent

  Validation failed

  ! workflow.yaml
    edge route_after_upgrade_check -> select_tool references missing node

  ! tools.yaml
    repair_ticket_create is high risk but confirm_required is false

  Next
  Fix the files above and run /validate again
```

`--json` 输出必须直接序列化 `ValidationReport`，不能混入 Rich 样式。

## CLI 命令

```bash
agentfactory validate-agent examples/customer_service_agent
agentfactory validate-agent examples/customer_service_agent --strict
agentfactory validate-agent examples/customer_service_agent --json

agentfactory validate-patch patch_plan.yaml
agentfactory validate-approval approval.yaml
agentfactory validate-diff diff.yaml
```

斜杠命令：

```text
/validate examples/customer_service_agent
/validate-patch patch_plan.yaml
/validate-approval approval.yaml
/validate-diff diff.yaml
```

## 验收标准

```text
1. validate-agent 可以校验 examples/customer_service_agent。
2. 缺任意必需 YAML 文件时校验失败。
3. workflow 引用不存在节点时校验失败。
4. route 缺兜底分支时校验失败。
5. condition 出现函数调用时校验失败。
6. high 工具没有 confirm_required 时校验失败。
7. mcp.yaml 不存在时校验失败。
8. condition 引用未声明 state 字段时校验失败。
9. PackageLoader 返回 AgentPackage 对象，而不是 dict。
10. validate-agent --json 输出 ValidationReport JSON。
11. PatchPlan 高风险 change 没有 approval_required=true 时校验失败。
12. PackageDiff 有 unexpected_changes 时校验失败。
```

## 不做

```text
1. 不执行 workflow。
2. 不调用工具。
3. 不连接 MCP Server。
4. 不生成 AgentPackage。
```
