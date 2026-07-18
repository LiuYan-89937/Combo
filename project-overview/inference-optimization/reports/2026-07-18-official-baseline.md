# Official llama.cpp 算子基线分析

## 测试身份

| 项目 | 值 |
|---|---|
| Run ID | `f9a42bd7b86c42c8a38df70cd23a08e0` |
| Profile | `qwen3_6_35b_a3b_apex_i_quality_chat` |
| 实现 | Official llama.cpp |
| Revision | `f955e394bf94e01e5e36186d13c985727e5ef5b5` |
| 优化状态 | `baseline` |
| 自定义 Kernel | 否 |
| Prefill | 512 tokens |
| Decode | 128 tokens |
| 重复次数 | 3 |
| Profiler | `rocprofv3` |
| HIP Graph replay | 为归因关闭 |
| 测试后 Runtime 恢复 | 成功 |
| 归因警告 | 0 |

## Prefill 热点

Prefill 算子分析进程耗时为 5.44 秒。GPU Kernel 热点如下：

| Kernel 类别 | 调用次数 | 总耗时 | 占 GPU Kernel 耗时 |
|---|---:|---:|---:|
| Quantized MatMul / MMQ | 720 | 421.86 ms | 57.87% |
| Tensile GEMM | 810 | 122.51 ms | 16.81% |
| Gated Delta Net | 90 | 56.85 ms | 7.80% |
| MoE Expert Indexing | 360 | 19.69 ms | 2.70% |
| Type Conversion | 1,140 | 17.07 ms | 2.34% |
| Q8_1 Quantization | 723 | 10.54 ms | 1.45% |
| Binary Multiply | 330 | 10.26 ms | 1.41% |
| Flash Attention Tile | 30 | 9.94 ms | 1.36% |

主要 MMQ 变体：

| 权重量化 | Shape `(m,n,k)` | 调用次数 | 总耗时 | 平均耗时 |
|---|---:|---:|---:|---:|
| Q6_K | `512,4096,2048` | 60 | 109.19 ms | 1.820 ms |
| IQ4_XS | `512,4096,2048` | 120 | 103.14 ms | 0.859 ms |
| Q5_K | `512,4096,2048` | 60 | 59.88 ms | 0.998 ms |
| Q6_K | `2048,4096,512` | 30 | 52.03 ms | 1.734 ms |
| IQ4_XS | `2048,4096,512` | 60 | 49.70 ms | 0.828 ms |

Prefill 中 MMQ 占绝对主导；MMVQ 仅调用 3 次、耗时 1.65 ms、占比 0.23%。

## Decode 热点

Decode 算子分析进程耗时为 13.76 秒。GPU Kernel 热点如下：

| Kernel 类别 | 调用次数 | 总耗时 | 占 GPU Kernel 耗时 |
|---|---:|---:|---:|
| Quantized MatVec / MMVQ | 134,784 | 1.869 s | 52.65% |
| Q8_1 Quantization | 134,784 | 285.05 ms | 8.03% |
| Flash Attention Vector | 3,840 | 199.43 ms | 5.62% |
| RMSNorm | 50,304 | 157.06 ms | 4.42% |
| Embedding Row Gather | 23,424 | 148.11 ms | 4.17% |
| Binary Add | 53,760 | 143.79 ms | 4.05% |
| Floating-point MatVec | 30,720 | 128.24 ms | 3.61% |
| MoE Top-K Routing | 15,360 | 114.18 ms | 3.22% |

主要 MMVQ 变体：

| 权重量化 | Shape `(m,n,k)` | 调用次数 | 总耗时 | 平均耗时 |
|---|---:|---:|---:|---:|
| Q6_K | `8192,1,2048` | 15,360 | 369.79 ms | 24.07 μs |
| Q6_K | `4096,1,2048` | 11,520 | 208.76 ms | 18.12 μs |
| Q6_K | `248320,1,2048` | 384 | 205.83 ms | 536.02 μs |
| Q6_K | `2048,1,4096` | 11,520 | 161.27 ms | 14.00 μs |
| IQ4_XS MoE | `512,1,2048` | 7,680 | 123.09 ms | 16.03 μs |
| Q8_0 | `2048,1,512` | 15,360 | 116.97 ms | 7.61 μs |

Decode 的主 Shape 均为 `n=1`，符合逐 Token 矩阵向量计算路径。

## 当前优化优先级

1. Decode Q6_K MMVQ：优先覆盖 `8192×1×2048`、`4096×1×2048`、`248320×1×2048` 和 `2048×1×4096`。
2. Decode Q8_1 动态量化：其调用次数与 MMVQ 相同，单独占 8.03%，是 MMVQ 优化后的主要上限之一。
3. Prefill MoE MMQ：重点分析 Q6_K、IQ4_XS、Q5_K 的 tile、共享内存、occupancy 和专家布局。
4. 每次优化必须同时记录普通性能测试，避免将关闭 HIP Graph 的归因耗时误当成生产性能。
