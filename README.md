# FastAgentFactory

当前仓库已经做过一次彻底清理，只保留：

- 一个 **LangGraph 14 阶段骨架**
- 一个最小 CLI
- 一个最小 shell
- 一个逐阶段测试入口

旧的 package 生成、tool build、harness、registry、repair、verify、drafts 等流程已经全部移除。

## 当前保留的 14 个阶段

1. `capture_requirement`
2. `understand_requirement`
3. `plan_capabilities`
4. `identify_conditions`
5. `plan_resource_needs`
6. `collect_evidence`
7. `build_resource_contracts`
8. `decide_readiness`
9. `plan_implementation`
10. `generate_package_specs`
11. `generate_tools`
12. `sandbox_test_and_repair`
13. `generate_harness`
14. `complete_summary`

这些阶段现在都只是空壳节点，默认消息是：

`阶段空壳已保留，内部实现已清空，等待重写。`

## 安装

```bash
cd /Users/liuyan/Desktop/FastAgentFactory
uv sync --extra dev
```

## 最小命令

初始化工作区：

```bash
uv run agentfactory init
```

进入 shell：

```bash
uv run agentfactory shell
```

运行单阶段断点：

```bash
uv run agentfactory create-agent \
  --prompt "创建一个记账 Agent" \
  --stop-after-stage capture_requirement \
  --json
```

逐阶段测试完整骨架：

```bash
uv run agentfactory test-stages \
  --prompt "创建一个记账 Agent"
```

也可以直接运行示例脚本：

```bash
.venv/bin/python examples/manual_stage_skeleton_test.py \
  --input "创建一个记账 Agent"
```

## 当前目标

这版仓库不是可用产品，而是一个 **准备逐阶段重写的 LangGraph 骨架**。

接下来应该按阶段逐个补内部实现，而不是恢复旧流程。
