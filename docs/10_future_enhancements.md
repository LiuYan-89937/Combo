# 10. 后续增强点记录

本文记录 01、02、03 阶段讨论中暂缓实现、但后续可能需要补强的能力。它不是第一版必须完成清单，而是防止讨论结果丢失的增强池。

## 01 工程骨架 / CLI 增强

### Shell 体验增强

```text
1. 持久化命令历史。
2. 更完整的斜杠命令参数补全。
3. 工作区感知的路径补全。
4. Agent / version / trace / patch id 自动补全。
5. 多行输入模式。
6. 当前 Agent 状态栏。
7. 可配置主题。
8. 更完整的键盘快捷键。
```

### CLI 能力增强

```text
1. agentfactory config 管理本地配置。
2. agentfactory profile 支持多环境配置。
3. agentfactory doctor 检查环境、依赖、Registry 状态。
4. agentfactory plugin 预留插件体系。
5. agentfactory export / import 支持包迁移。
6. agentfactory completion 生成 shell completion。
```

### 界面增强边界

```text
1. 第一版不做复杂全屏 TUI。
2. 后续可以增加轻量 dashboard，但不能替代 CLI 命令。
3. Web UI 后续必须复用 application/ 服务，不重新实现业务逻辑。
```

## 02 规范与校验器增强

### Spec 体系增强

```text
1. 为所有 Spec 自动导出 JSON Schema。
2. 支持 schema_version 迁移器。
3. 支持 agent package format upgrade。
4. 支持字段 deprecation warning。
5. 支持 IDE / editor diagnostics。
6. 支持 docs 自动生成字段说明。
```

### 校验器增强

```text
1. auto-fix 模式，自动修复轻微格式问题。
2. warning policy，可配置 warnings-as-errors。
3. 更细粒度的错误 code 体系。
4. 多文件 source map，定位 YAML 行列号。
5. 校验结果 SARIF / JSON 输出。
6. 校验缓存，避免重复解析大包。
```

### 对象模型增强

```text
1. 用更强的值对象替代 JsonSchema alias。
2. 为 CapabilityRef、PackageRef、VersionRef 增加解析和比较能力。
3. 支持不可变 frozen spec，用 builder 生成新版本。
4. 支持 schema diff，用于 PatchPlan 生成前的影响分析。
```

## 03 Runtime 增强

### Runtime 选择增强

```text
1. AgentFactoryAgent 根据需求复杂度推荐 runtime.type。
2. PackageValidator 给出 runtime.type 建议。
3. WorkflowRuntime 与 GraphRuntime 支持混合模式。
4. 固定流程中局部节点可以嵌套 Graph 子图。
5. GraphRuntime 中可嵌套固定 Workflow 子流程。
```

### WorkflowRuntime 增强

```text
1. 表单式节点。
2. 审批式节点。
3. SLA / timeout 策略。
4. 明确的前置条件和后置条件。
5. 更强的人工确认与恢复流程。
```

### GraphRuntime 增强

```text
1. 并行分支。
2. 子图。
3. 循环检测和循环解释。
4. 状态压缩。
5. 状态回放。
6. 状态差异 diff。
7. route 决策解释器。
8. 复杂降级策略。
```

### Checkpoint / Interrupt 增强

```text
1. Durable checkpoint 存储。
2. checkpoint resume 的完整实现。
3. 中断后继续执行的幂等保障。
4. Human-in-the-loop 审批恢复。
5. checkpoint 与 trace、approval 关联。
```

### Trace 增强

```text
1. Trace span 树展示。
2. Trace replay。
3. Trace compare。
4. Trace 到 Harness case 的自动转化。
5. OpenTelemetry adapter。
6. 可视化图执行回放。
```

### Runtime 安全增强

```text
1. Tool input guardrail。
2. Tool output guardrail。
3. MCP output sanitization。
4. 每节点资源限制。
5. 每节点超时和取消。
6. 运行时策略热更新。
```

## 04 Capability / Tool / MCP / Context 增强

### Capability 增强

```text
1. Capability 依赖图。
2. Capability 兼容性矩阵。
3. Capability 自动迁移。
4. Capability impact analysis。
5. Capability marketplace / library。
6. Capability 权限模板。
```

### Tool 增强

```text
1. 生产级工具沙箱。
2. 工具执行资源限制。
3. 工具幂等键自动生成。
4. 工具输入输出 guardrail。
5. 工具调用重放。
6. 工具 mock 自动生成。
7. 工具 schema 到表单的自动渲染。
8. Factory 生成工具的安全静态分析增强。
9. 可选 ToolWorker 进程，用于隔离特别高风险或不可信工具。
```

### MCP 增强

```text
1. streamable HTTP transport。
2. OAuth / 授权增强。
3. MCP Server trust store。
4. MCP Server marketplace。
5. MCP resources / prompts 的完整策略。
6. MCP 工具变更自动 diff。
7. MCP tool cache 与 list_changed 完整处理。
8. MCP 输出注入风险检测。
```

### Context 增强

```text
1. 语义检索上下文。
2. 上下文压缩策略。
3. 上下文 token 预算优化。
4. 上下文 source attribution。
5. 上下文冲突检测。
6. 长期记忆写入建议。
7. 用户可见的上下文解释。
8. ContextBundle diff 和 replay。
```

### Guardrail 增强

```text
1. 完整 input guardrail。
2. 完整 output guardrail。
3. tool input guardrail。
4. tool output guardrail。
5. MCP result sanitization 策略。
6. policy violation 自动升级为 Harness case。
```

## 05 AgentHarness 增强

### 场景增强

```text
1. 多轮长对话场景。
2. 场景参数化。
3. 场景组合。
4. 从 trace 自动生成 scenario。
5. 从线上失败样本生成候选 scenario。
6. 场景标签和覆盖率统计。
```

### 观测增强

```text
1. Runtime path 可视化。
2. ContextBundle diff。
3. Memory read/write diff。
4. Tool / MCP 调用时序图。
5. route decision explanation。
6. 可回放 Harness run。
```

### 断言增强

```text
1. 语义断言。
2. LLM-as-judge 断言。
3. 响应风格断言。
4. 多指标评分。
5. 不确定性阈值。
6. 复杂安全策略断言。
```

### Evolution Harness 边界

```text
1. Evolution Harness 是后续增强，不属于 05 当前主体。
2. Evolution Harness 可以比较新旧版本行为差异。
3. Evolution Harness 可以评估升级是否改善。
4. Evolution Harness 可以推荐新增 Harness scenario。
5. 第一版 AgentHarness 只验证当前 AgentPackage 是否在合理范围内正确运行且可观测。
```

## 07 返厂升级增强

### 审批增强

```text
1. 多审批人。
2. 审批角色和组织权限。
3. 审批过期策略。
4. 审批撤销。
5. 审批模板。
6. 审批链路可视化。
```

### 发布增强

```text
1. 自动灰度。
2. 流量切分。
3. 自动回滚条件。
4. 发布窗口。
5. 发布前后指标对比。
6. 多环境 promotion。
```

### 升级智能化增强

```text
1. 从 trace 自动生成 UpgradeRequest。
2. 从 AgentHarness 失败自动生成 PatchPlan 草稿。
3. 自动生成新增 scenario。
4. 自动分析影响范围。
5. 新旧版本行为差异解释。
6. 与 Evolution Harness 集成。
```

### 状态迁移增强

```text
1. 运行中实例跨版本迁移。
2. GraphState 版本迁移。
3. Memory schema 迁移。
4. Checkpoint 跨版本恢复。
5. 长任务升级策略。
```

## 暂缓原因

```text
1. 第一版目标是跑通 CLI-first 最小闭环。
2. 过早做复杂 Runtime 和 Evolution Harness 会拖慢 Package / AgentHarness / Registry 闭环。
3. 复杂 UI、复杂审批流、复杂 checkpoint 都应在 MVP 可运行后再增强。
4. 当前优先级仍然是：骨架、规范、双 Runtime 最小执行、能力层最小闭环、Harness、Registry、返厂升级。
```
