# 12. Factory Production Runtime

## 目标

AgentFactory 生产 AgentPackage 不是一次性 workflow，而是一个需要条件分支、修复回路、澄清分支和流式反馈的生产图。

第一版 Factory 生产线使用 **LangGraph StateGraph** 实现。这里的 Graph 只服务于 Factory 自己的“制造过程”，不等同于未来 AgentInstance 的 Runtime。生成出来的 Agent 以后仍可根据自己的配置选择 WorkflowRuntime 或 GraphRuntime。

## 边界

```text
Factory Production Runtime
  负责：需求分析、澄清判断、标准件生成、schema repair、写 YAML、校验、trace、memory、stream
  不负责：AgentInstance 运行、工具真实执行、MCP 调用、Harness 完整执行

AgentInstance Runtime
  负责：读取 AgentPackage 后按声明运行
  可选：固定 Workflow 或复杂 Graph
```

## 生产链路

```text
requirement
  -> LangGraph FactoryProductionRuntime
  -> ModelService.generate_structured()
  -> AgentPackagePrimitives.model_validate()
  -> PackageWriter
  -> PackageValidator
  -> .agentfactory/packages/drafts/<slug>/
```

## Graph 节点

```text
capture_requirement
load_factory_context
analyze_requirement
maybe_clarify
plan_primitives
validate_primitives
repair_primitives
write_package
generate_tool_scripts
generate_tool_tests
generate_mcp_bindings
generate_harness_scenarios
validate_package
record_factory_memory
complete
failed
needs_clarification
```

## 条件边

```text
maybe_clarify
  -> needs_clarification
  -> plan_primitives

plan_primitives
  -> validate_primitives
  -> failed

validate_primitives
  -> repair_primitives
  -> write_package
  -> failed

repair_primitives
  -> validate_primitives
  -> failed

write_package
  -> generate_tool_scripts
  -> failed

generate_tool_scripts
  -> generate_tool_tests
  -> failed

generate_tool_tests
  -> generate_mcp_bindings
  -> failed

generate_mcp_bindings
  -> generate_harness_scenarios
  -> failed

generate_harness_scenarios
  -> validate_package
  -> failed

validate_package
  -> record_factory_memory
  -> failed

record_factory_memory
  -> complete
```

## 状态对象

生产图内部使用 `FactoryProductionState` 作为领域状态，再转成 LangGraph state dict 进入 `StateGraph`。

关键字段：

```text
run_id
requirement
status
current_stage
package_path
raw_model_data
primitives
validation_report
generated_artifacts
generated_tool_count
generated_tool_test_count
mcp_binding_count
harness_scenario_count
repair_attempts
max_repair_attempts
clarification_questions
events
error
runtime_type
stage_history
```

原则：

```text
1. 节点内先把 state dict 校验回对象。
2. 模型输出永远不可信，必须经过 Pydantic schema 校验。
3. repair 默认最多一次，避免无限自修复。
4. 工具脚本只生成 draft，不直接进入 Available。
5. 需求不清晰时进入 needs_clarification，不写 AgentPackage。
6. trace 和 memory 写入 Factory 自己的 .agentfactory/，与 AgentInstance 隔离。
```

## CLI 流式输出

`create-agent` 默认使用 stream：

```bash
agentfactory create-agent --prompt "创建一个客服 Agent" --draft --stream
```

人类输出逐步显示 `FactoryEvent`。JSON stream 输出 JSON Lines：

```bash
agentfactory create-agent --prompt "创建一个客服 Agent" --draft --json --stream
```

非流式 JSON 输出最终结果：

```bash
agentfactory create-agent --prompt "创建一个客服 Agent" --draft --json --no-stream
```

## 当前实现范围

已实现：

```text
1. LangGraph StateGraph 生产 AgentPackage primitives。
2. 澄清分支。
3. primitives schema 校验与 repair 回路。
4. PackageWriter 写 9 个 YAML 标准件文件。
5. 生成工具草稿脚本和配套工具单测。
6. 生成 MCP binding 草稿配置。
7. 生成 Harness 场景和 fixture 草稿。
8. PackageValidator 立即校验生成目录。
9. Factory trace / memory 记录。
10. CLI human stream 和 JSONL stream。
```

后续接入：

```text
1. 执行 generated tool tests。
2. 运行 AgentHarness 场景。
3. MCP stdio health_check / tools/list。
4. 工具脚本静态检查和沙箱执行。
5. 审批与 PackageDiff 节点。
```
