# 07. 返厂升级、审批、发布

## 目标

实现从 AgentInstance 运行中发现问题，到 AgentFactory 生成新 AgentPackage 版本的完整返厂升级链路。

核心原则：

```text
1. AgentInstance 不能私自修改自己。
2. AgentInstance 只能提交 UpgradeRequest。
3. AgentFactory / Control Process 负责升级规划、审批、打补丁、测试和发布。
4. 新版本以新的 AgentPackage snapshot 形式存在。
5. 旧版本必须可追踪、可回滚、可继续运行旧实例。
```

升级链路：

```text
UpgradeRequest
  ↓
PatchPlan
  ↓
ApprovalRecord
  ↓
PackageDiff
  ↓
AgentHarness
  ↓
Release
```

## 和 AgentHarness 的关系

AgentHarness 不是升级系统，但升级系统必须调用它验证候选版本。

```text
PatchPlan 生成新版本
  ↓
PackageDiff 证明实际变更符合计划
  ↓
AgentHarness 验证候选 AgentPackage 在合理范围内正确运行且可观测
  ↓
ReleasePlanner 决定发布策略
```

07 不实现 Evolution Harness，不做“自动判断新版本更聪明”。07 只保证升级链路可控、可审计、可回滚。

## 核心对象

```text
UpgradeRequest：为什么要改
PatchPlan：准备怎么改
ApprovalRecord：谁批准了哪些高风险变更
PackageDiff：最终实际改了什么
HarnessReport：候选版本的 AgentHarness 运行结果
Release：是否进入 Candidate / Available / Canary / Stable
RollbackPlan：如何回到旧版本
```

## 核心模块

```text
agent_factory/factory/
├── upgrade_planner.py
├── release_planner.py
└── package_generator.py

agent_factory/package/
├── patch_plan.py
├── patch_plan_validator.py
├── patch_plan_executor.py
├── approval_record.py
├── approval_validator.py
├── package_diff.py
└── package_diff_validator.py

agent_factory/ops/
├── version_manager.py
├── release_manager.py
├── rollback_manager.py
└── upgrade_audit.py
```

## UpgradeRequest

`UpgradeRequest` 可以由三类来源生成：

```text
1. 使用者主动提出需求。
2. AgentInstance 自检发现能力缺失。
3. 监控或 AgentHarness 发现稳定失败模式。
```

AgentInstance 中常见触发：

```text
1. unknown intent。
2. missing required tool。
3. MCP capability missing。
4. policy 无法满足用户目标。
5. workflow / graph 无合法路径。
6. 某类请求持续转人工。
```

UpgradeRequest 必须包含：

```text
request_id
source
agent_name
current_version
instance_id
trigger
observed_context
expected_change
risk
trace_refs
```

规则：

```text
1. AgentInstance 可以生成 UpgradeRequest。
2. AgentInstance 不允许修改 AgentPackage。
3. UpgradeRequest 必须进入 Registry。
4. UpgradeRequest 必须关联 trace 或观测样本。
```

## PatchPlan

`PatchPlan` 是升级计划，不是实际变更。

它说明：

```text
1. 要改哪些文件。
2. 每个 change 的 JSONPath target。
3. 每个 change 的风险等级。
4. 哪些 change 需要审批。
5. 哪些 generated_code 需要准入。
6. 需要新增或更新哪些 AgentHarness scenario。
7. 如何回滚。
```

支持操作：

```text
add
update
append
patch
deprecate
```

v0.1 不支持物理删除能力。删除必须先走 `deprecate -> Disabled`。

规则：

```text
1. PatchPlan 必须通过 PatchPlanValidator。
2. target_path 使用 JSONPath 风格。
3. target_file 必须在允许的 AgentPackage 文件范围内。
4. 高风险 change 必须 approval_required=true。
5. generated_code 必须落到 generated/draft_tools/。
6. PatchPlan 修改后，旧 ApprovalRecord 失效。
```

## ApprovalRecord

`ApprovalRecord` 记录使用者或授权主体对高风险 change 的审批。

必须记录：

```text
approval_id
actor
authority_scope
patch_plan_id
patch_plan_hash
approved_items
risk_snapshot
evidence
decision
expires_at
trace_id
```

规则：

```text
1. 高风险 change 必须逐项审批。
2. ApprovalRecord 只对当前 PatchPlan hash 有效。
3. generated_code 审批必须记录代码 hash。
4. 拒绝审批必须记录 reason。
5. ApprovalRecord 不允许覆盖，只能追加新记录。
```

## PackageDiff

`PackageDiff` 是 PatchPlan 执行后的实际变更记录。

必须记录：

```text
diff_id
patch_plan_id
approval_record_ids
package_hash.before
package_hash.after
file_changes
change_results
unexpected_changes
rollback
```

规则：

```text
1. PackageDiff 只能由 PatchPlanExecutor 生成。
2. PackageDiff 必须证明实际变更与 PatchPlan 一致。
3. 高风险 change 必须关联 approval_record_id。
4. unexpected_changes.count 必须为 0。
5. 出现计划外变更时不能进入 AgentHarness。
6. PackageDiff 必须进入 Registry。
```

## Release

Release 是候选版本进入可用状态的记录。

状态：

```text
Candidate
Available
Canary
Stable
RolledBack
Failed
```

规则：

```text
1. 新版本先进入 Candidate。
2. Candidate 必须运行 AgentHarness。
3. AgentHarness 失败不能进入 Available。
4. 高风险升级建议进入 Canary。
5. Stable 必须有 rollback target。
6. 热更新不能覆盖旧版本。
7. 运行中的旧 AgentInstance 不强制切换。
8. 新 AgentInstance 默认使用最新 Available / Stable 版本。
```

## Rollback

第一版回滚先做版本级回滚，不做运行中状态回滚。

```text
1. Release 记录 rollback target。
2. RollbackManager 可以把默认版本指回旧版本。
3. 已运行旧实例继续运行。
4. 已运行新实例可以停止后重启到旧版本。
5. 不尝试把新版本进程内部状态迁移回旧版本。
```

## 完整流程

```text
AgentInstance 发现能力缺失
  ↓
生成 UpgradeRequest
  ↓
Registry 记录 UpgradeRequest
  ↓
UpgradePlanner 生成 PatchPlan
  ↓
PatchPlanValidator 校验
  ↓
高风险 change 生成 ApprovalRecord
  ↓
PatchPlanExecutor 基于旧 AgentPackage snapshot 生成新 package draft
  ↓
PackageDiff 记录实际变更
  ↓
PackageDiffValidator 校验无计划外变更
  ↓
PackageValidator 校验新 AgentPackage
  ↓
运行新版本 AgentHarness
  ↓
VersionManager 标记 Candidate
  ↓
ReleasePlanner 选择 Available / Canary / Stable
  ↓
ReleaseManager 写入 Registry
```

## 与 AgentInstance 的关系

```text
1. AgentInstance 可以提出 UpgradeRequest。
2. AgentInstance 不能执行 PatchPlan。
3. AgentInstance 不能写自己的 AgentPackage。
4. AgentInstance 不能把自己热替换成新版本。
5. Control Process 可以停止旧实例并启动新版本实例。
6. 旧实例默认继续绑定旧 package snapshot。
```

## CLI 命令

```bash
agentfactory upgrade-agent customer-service-agent --prompt "增加以旧换新意图"
agentfactory plan-upgrade customer-service-agent --request upgrade.yaml --output patch_plan.yaml
agentfactory validate-patch patch_plan.yaml
agentfactory review-patch patch_plan.yaml
agentfactory approve-patch patch_plan.yaml --change change-tool-001 --actor user
agentfactory apply-patch-plan patch_plan.yaml --output examples/customer_service_agent_v1_1_0
agentfactory diff show diff-20260501-001
agentfactory diff validate diff-20260501-001
agentfactory test-agent examples/customer_service_agent_v1_1_0
agentfactory release customer-service-agent --version 1.1.0 --channel candidate
agentfactory rollback customer-service-agent --to-version 1.0.0
```

斜杠命令：

```text
/upgrade customer-service-agent
/plan-upgrade customer-service-agent
/validate-patch patch_plan.yaml
/review-patch patch_plan.yaml
/approve-patch patch_plan.yaml --change change-tool-001
/apply-patch-plan patch_plan.yaml
/diff show diff-20260501-001
/diff validate diff-20260501-001
/test examples/customer_service_agent_v1_1_0
/release customer-service-agent --version 1.1.0 --channel candidate
/rollback customer-service-agent --to-version 1.0.0
```

## 必做任务

```text
1. 实现 UpgradeRequest 模型。
2. 实现 UpgradePlanner。
3. 实现 PatchPlan 模型和校验器。
4. 实现 ApprovalRecord 模型和校验器。
5. 实现 PatchPlanExecutor。
6. 实现 PackageDiff 模型和校验器。
7. 实现 VersionManager。
8. 实现 ReleasePlanner。
9. 实现 ReleaseManager。
10. 实现 RollbackManager。
11. 将 UpgradeRequest / PatchPlan / ApprovalRecord / PackageDiff / Release 写入 Registry。
12. 将 AgentHarness 结果接入 Release 判断。
```

## 验收标准

```text
1. unknown intent 可以生成 UpgradeRequest。
2. plan-upgrade 可以生成 PatchPlan。
3. validate-patch 可以发现非法 target_path。
4. approve-patch 可以生成 ApprovalRecord。
5. PatchPlan hash 改变后旧 ApprovalRecord 失效。
6. apply-patch-plan 可以生成 PackageDiff。
7. diff validate 能发现计划外变更。
8. 高风险 change 无 ApprovalRecord 时不能执行。
9. AgentHarness 失败时不能发布 Available。
10. release 可以写入 Candidate 记录。
11. rollback 能把默认版本指回旧版本。
12. 旧 AgentInstance 不会被强制切换到新版本。
```

## 不做

```text
1. 不做 Evolution Harness。
2. 不做自动生产流量灰度。
3. 不做复杂审批流引擎。
4. 不做跨团队权限系统。
5. 不做运行中状态跨版本迁移。
6. 不做自动判断新版本是否更聪明。
```

