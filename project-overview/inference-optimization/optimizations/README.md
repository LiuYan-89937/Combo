# 推理优化说明索引

每项优化使用独立 Markdown 文件记录，建议命名为：

```text
YYYY-MM-DD-<operator>-<short-name>.md
```

每份说明至少包含：

1. 优化目标与对应基线 Run ID。
2. 命中的量化类型与 Shape 范围。
3. 修改的 llama.cpp 实现、源码位置和编译选项。
4. Kernel 命中证据与 `rocprofv3` 归因结果。
5. 相同模型、Prompt、输出长度、并发度和推理配置下的普通性能对比。
6. TTFT、Prompt tokens/s、Decode tokens/s、端到端延迟、显存峰值和结果正确性。
7. 已知限制、回退条件与是否适合合入 AMD 实现。

原生 `official` 与自定义 `amd` 两套实现必须分别保留结果，不使用不同测试条件的数据计算提升比例。

## 已验证优化

- [2026-07-19 · RDNA3 Decode 算子优化](2026-07-19-q8-activation-reuse.md)：Q8_1 Kernel 调用减少 `42.74%`；Residual Add、RMSNorm 与权重缩放融合命中 `11,520` 次；AMD 整体实现的普通服务 Decode 吞吐提升 `5.64%`。
