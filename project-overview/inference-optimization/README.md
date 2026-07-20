# llama.cpp 推理优化档案

本目录集中保存 FastAgentFactory 在 AMD Radeon GPU 与 ROCm 环境中的 llama.cpp 推理分析数据、基线结论和后续优化说明。稳定扩散图片生成不属于本目录的优化范围。

## 目录约定

- `data/`：从 Benchmark 记录导出的原始结构化数据，作为结果追溯依据。
- `reports/`：对单次或多次测试结果的可读分析，不替代原始数据。
- `optimizations/`：自定义 Kernel、计算路径调整、编译选项和验证结果的说明。

## 当前基线

- 实现：Official llama.cpp
- 模型：Qwen3.6-35B-A3B-APEX-I-Quality
- 设备后端：ROCm
- 测试类型：算子分析
- Run ID：`f9a42bd7b86c42c8a38df70cd23a08e0`
- 测试时间：2026-07-18

关联文件：

- [原始算子分析数据](data/2026-07-18-official-operator-analysis-f9a42bd7.json)
- [Official llama.cpp 基线分析](reports/2026-07-18-official-baseline.md)
- [AMD RDNA3 推理优化改动说明](optimizations/README.md)

## 当前成功优化

- [AMD RDNA3 推理优化改动说明](optimizations/README.md)：汇总 Q8_1 激活复用、Residual RMSNorm 融合、Native Q6_K MMVQ、Q8_0 Wave 选择与 RDNA3 MMQ Tile 优化及其验证结果。

## 数据使用边界

算子分析会关闭 HIP Graph replay，并在 `rocprofv3` 下执行，用于建立 Host Shape 与 GPU Kernel 的安全对应关系。因此其中的 Kernel 耗时适合判断热点和优化优先级，不应作为正常服务吞吐量。TTFT、Prompt tokens/s、Decode tokens/s 与端到端延迟必须使用普通性能测试单独验证。
