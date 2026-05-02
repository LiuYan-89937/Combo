# 09. MVP 样例候选

## 当前状态

本文件暂时记录第一版 MVP 样例候选，不作为最终实现承诺。

最终 MVP 样例需要等以下框架能力完成后再确定：

```text
1. 01 工程骨架。
2. 02 声明式规范与校验器。
3. 03 Runtime 执行模型。
4. 04 Capability / Tool / MCP / Context。
5. 05 AgentHarness。
6. 06 Registry 与 AgentInstance 进程隔离。
7. 07 返厂升级、审批、发布。
8. 08 CLI-first 操作体验。
```

也就是说，09 不在当前阶段把客服 Agent MVP 方案写死。等框架主干跑通后，再根据实现成本和验收价值决定最终 MVP Agent。

## MVP 样例选择标准

最终 MVP Agent 应满足：

```text
1. 能通过自然语言创建 AgentPackage 草稿。
2. 能覆盖 WorkflowRuntime 或 GraphRuntime 至少一种执行模型。
3. 能用到 ToolCapability。
4. 能用到 MCP 外部能力。
5. 能用到 ContextBundle 和 visibility_policy。
6. 能被 AgentHarness 观测。
7. 能注册到文件系统 Registry。
8. 能作为独立 AgentInstance 进程运行。
9. 能触发 UpgradeRequest。
10. 能跑通 PatchPlan -> ApprovalRecord -> PackageDiff -> AgentHarness -> Release。
```

## 候选 1：客服 Agent

客服 Agent 仍然是强候选，因为它覆盖面完整：

```text
1. 有明确 intent。
2. 有工具调用。
3. 有 MCP 知识库查询。
4. 有转人工和高风险确认。
5. 有 Context 可见性。
6. 有 unknown intent 触发返厂升级。
```

候选能力：

```text
v1.0.0:
  - 售前咨询
  - 售后咨询
  - 退款意图识别
  - 投诉意图识别
  - 转人工
  - 订单查询工具
  - 客服知识库 MCP 查询

v1.1.0 候选升级:
  - 新增 repair_return 意图
  - 新增 repair_ticket_create 工具声明
  - 生成 repair_ticket_create 工具代码草稿
  - 创建返厂工单前触发 human_confirm
```

## 候选 2：代码审查 Agent

代码审查 Agent 也可以作为 MVP 候选，但实现复杂度可能更高。

优点：

```text
1. 工具和文件上下文明显。
2. AgentHarness 可以观测 diff、诊断和建议。
3. 适合 CLI 用户。
```

风险：

```text
1. 代码分析工具链复杂。
2. 容易过早进入真实工程场景。
3. MCP 和工具 mock 成本较高。
```

## 候选 3：知识库问答 Agent

知识库问答 Agent 实现成本最低，但覆盖面不足。

优点：

```text
1. 容易实现。
2. MCP 查询路径清晰。
3. AgentHarness 易写。
```

不足：

```text
1. 工具风险和审批链路覆盖不足。
2. 返厂升级价值不明显。
3. 不能充分验证 Tool / Patch / Approval / Release。
```

## 暂定建议

在框架搭完之前，不最终决定 09。

当前倾向：

```text
首选：客服 Agent
备选：知识库问答 Agent
暂缓：代码审查 Agent
```

原因：

```text
客服 Agent 最适合验证 AgentFactory 的完整闭环：
自然语言创建、工具、MCP、Context、AgentHarness、独立进程、UpgradeRequest、PatchPlan、ApprovalRecord、PackageDiff、Release。
```

## 最终确认时间点

在完成以下验收后再确定 09 的最终内容：

```text
1. agentfactory shell 可用。
2. validate-agent 可用。
3. WorkflowRuntime / GraphRuntime 至少一个可运行。
4. ToolRouter 最小闭环可用。
5. MCP mock 或 stdio test server 可用。
6. AgentHarness 可运行 scenario。
7. Registry 可注册 AgentPackage。
8. AgentInstance 可独立进程启动。
```

## 不做

```text
1. 当前不锁死最终 MVP 业务场景。
2. 当前不写完整客服 Agent YAML。
3. 当前不承诺 v1.0.0 / v1.1.0 具体范围。
4. 当前不接真实支付、删除、工单生产系统。
```

