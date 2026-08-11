# Dynamic Runtime 重构审计

本目录保存重构执行过程中可重复生成和复核的审计证据。

生成当前旧结构与本地数据基线：

```bash
python3 scripts/audit_dynamic_runtime_refactor.py \
  --output docs/refactor/legacy_inventory.json
```

审计脚本遵循以下边界：

- 只读取源码路径、匹配数量、数据目录统计和 SQLite 表行数；
- 不读取或输出模型凭据、MCP 密钥、Resource Store 密文和用户消息内容；
- 不修改 `.agentfactory` 中的任何数据；
- 兼容项目当前支持的 Python 3.9 及以上解释器；
- 输出中的绝对根路径用于证明执行环境，迁移逻辑不能依赖该路径；
- 为每个旧引用文件分配唯一执行单元；`unassigned_files` 非空时执行单元 0 不得验收；
- 每个执行单元完成后重新生成结果，并通过对应旧结构计数是否归零进行验收。
- 第二轮审计还跟踪重复能力注册表、隐式环境变量策略、进程级审批信任、无归属运行状态和旧 Prompt/Executor 装配；这些计数不要求品牌词归零，而要求所有命中都有唯一迁移或删除责任。
- 第三轮审计继续跟踪浏览器端运行策略、模型重试与副作用幂等、附件/上下文多投影、日期与时区、事件重连、执行环境、能力供应链、桌面 sidecar 端点和 SQLite Schema 权威。

`legacy_inventory.json` 是执行单元 0 的基线。后续迁移报告必须引用其 Schema 版本和生成时间。
