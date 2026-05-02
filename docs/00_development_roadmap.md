# 00. 开发路线图

## 目标

把 AgentFactory 第一版拆成可执行阶段，先跑通框架闭环，再逐步补齐能力。第一版不是做完整产品后台，而是完成一个 CLI-first、可测试、可追踪、可升级的 Agent 制造与运行框架。

## 阶段总览

```text
阶段 1：工程骨架
  ↓
阶段 2：声明式规范与校验器
  ↓
阶段 3A：Model / LLM 交互层
  ↓
阶段 3B：Agent Building Primitives
  ↓
阶段 3C：Factory Production Runtime
  ↓
阶段 3D：AgentInstance Runtime 执行模型
  ↓
阶段 4：Capability / Tool / MCP / Context
  ↓
阶段 5：Harness
  ↓
阶段 6：Registry 与进程隔离
  ↓
阶段 7：返厂升级、审批、发布
  ↓
阶段 8：CLI-first 操作体验
  ↓
阶段 9：MVP 样例最终确认
```

## 阶段依赖

| 阶段 | 依赖 | 核心产物 |
| --- | --- | --- |
| 工程骨架 | 无 | Python 包、CLI 空壳、目录结构 |
| 规范与校验器 | 工程骨架 | Pydantic spec、PackageLoader、PackageValidator |
| Model / LLM 交互层 | 工程骨架、规范与校验器 | ModelService、ModelRouter、ProviderAdapter、OpenAI-compatible adapter、FakeModelAdapter |
| Agent Building Primitives | 规范与校验器、Model / LLM 交互层 | InstructionSpec、OutputSpec、ConversationSpec、RunContextSpec、ToolsetSpec、KnowledgeSpec、GuardrailSpec、HandoffSpec、ObservabilitySpec |
| Factory Production Runtime | 规范与校验器、Model / LLM 交互层、Agent Building Primitives | LangGraph StateGraph、FactoryProductionState、生产节点、条件路由、stream、trace、memory |
| AgentInstance Runtime 执行模型 | 规范与校验器、Model / LLM 交互层、Agent Building Primitives | WorkflowRuntime、GraphRuntime、GraphState、Node、Route、RuntimeContext |
| Capability 能力层 | 规范与校验器、Runtime | CapabilityRegistry、ToolRouter、MCPClientManager、ContextManager |
| Harness | 规范、Runtime、能力层 | HarnessRunner、测试报告、可复现记录 |
| Registry 与隔离 | 规范、Harness | 文件系统 Registry、ProcessRuntime |
| 返厂升级 | Registry、Harness | UpgradeRequest、PatchPlan、ApprovalRecord、PackageDiff |
| CLI-first | 全部核心服务 | create/test/run/upgrade/release 等命令 |
| MVP 样例最终确认 | 全部阶段 | 从候选样例中选择最终 MVP Agent |

## 第一版完成定义

```text
1. 能通过 CLI 根据自然语言需求，使用 LangGraph Factory Production Runtime 生成文件系统中的 AgentPackage 草稿。
2. 能校验 AgentPackage 的所有必需文件。
3. 能通过 ModelService 调用 OpenAI-compatible provider 或 FakeModelAdapter。
4. 能加载和校验 Agent Building Primitives 必需标准件。
5. 能根据 AgentPackage 声明运行 WorkflowRuntime 或 GraphRuntime。
6. 能通过 ToolRouter 调用工具。
7. 能接入一个 MCP Server 并映射为 Capability。
8. 能运行 Harness 并输出可复现报告。
9. 能把通过测试的 AgentPackage 注册到文件系统 Registry。
10. 能为一个 AgentInstance 创建独立进程。
11. 能从 unknown intent 生成 UpgradeRequest。
12. 能生成 PatchPlan、审批高风险 change、生成 PackageDiff。
13. 能发布 v1.1.0 Candidate / Available。
14. 能通过 CLI 查看 trace、approval、diff、registry。
15. 底层 smoke runner 只能用于开发验证，不能替代正式 PackageWriter / PackageValidator / Harness 流程。
```

## 暂不做

```text
1. 可视化 Web 后台。
2. 企业级多租户权限。
3. 分布式调度。
4. 生产级容器编排。
5. 未经审批的生成代码上线。
6. 让 LLM 直接执行工具。
7. 复杂商业化管理。
```
