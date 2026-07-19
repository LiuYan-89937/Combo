# RDNA3 Decode 算子优化：Q8_1 激活复用与 Residual RMSNorm 融合

## 结论

在 Qwen3.6-35B-A3B Q6_K、gfx1100、单并发、256K 上下文、Q8_0 KV Cache 与 Flash Attention 开启的相同条件下，AMD 实现包含两项已命中的 Decode 优化：复用同一 F32 激活的 Q8_1 临时量化结果，以及将 `Residual Add + RMSNorm + 权重缩放` 融合为一个 RDNA3 HIP Kernel。整套 AMD 实现将正常服务 Decode 吞吐从 Official 的 `84.0867 tok/s` 提升到 `88.8320 tok/s`，提升 `5.64%`。

两组各包含 1 次预热和 5 次计量，计量标准差分别为 `0.1943 tok/s` 与 `0.1718 tok/s`。Official 与 AMD 的 5 次归一化流式输出哈希一致，均为 `6c7bf1d59882869591634b94616d151349bfdf6081fde7ea45686fdd3a83d473`。

`5.64%` 是两项优化与当前 AMD Kernel 集合共同启用时的端到端综合收益。算子分析能够分别证明 Q8_1 重复调用被删除、Residual RMSNorm 融合实际命中，但当前数据没有通过逐项关闭优化进行消融，因此不把综合收益错误拆分到某一个 Kernel。

## 与 Official 原实现的总体对比

| 优化位置 | Official 原实现 | AMD 实现 | 直接减少的工作 |
| --- | --- | --- | --- |
| MatVec 输入量化 | 每次 `ggml_cuda_mul_mat_vec_q()` 调用都分配临时 Q8_1 Buffer，并对传入的 F32 激活重新量化 | 在单次计算图内识别具有多个 MatVec 消费者的同一激活，按设备数据与布局复用已生成的 Q8_1 Buffer | Q8_1 Kernel 调用减少 57,600 次，即 `42.74%` |
| 残差归一化 | Residual Add 单独执行；llama.cpp 已有的融合路径再执行 `RMSNorm + 权重 MUL`，合计两个 Kernel | 一个 RDNA3 HIP Kernel 同时完成 Residual Add、RMSNorm 和权重缩放，并保留两个必要输出 | 每个命中子图由两个 Kernel 降为一个；减少一次残差显存回读和一次 Kernel 启动 |
| 架构分派 | 使用通用 CUDA/HIP 实现与原有融合匹配器 | Host 运行时识别 RDNA3，设备端使用 Wave32、`float4` 和 RDNA3 归约实现 | 非 RDNA3 或约束不满足时保持 Official 路径 |

这两项优化都没有减少模型应执行的数学运算，也没有改变权重、KV Cache、上下文、采样参数或输出长度。区别只在于删除重复的数据变换与中间显存往返。

## 优化一：复用 MatVec 激活的 Q8_1 量化结果

Decode 的量化 MatVec 路径会先将 F32 激活转换为 Q8_1，再与量化权重执行点积。Qwen3.6 的多个线性投影会在同一计算图中消费同一激活；Official 实现会在每次 MatVec 分派前重复执行相同的 Q8_1 量化。

AMD 实现增加计算图级激活量化缓存：

- 扫描当前计算图，只选择被两个及以上 `MUL_MAT` 或 `MUL_MAT_ID` 节点消费的 F32 激活根张量。
- 缓存键由激活根张量、实际数据地址、Shape、Stride、补齐后的列数和 HIP Stream 共同组成。
- 每个图执行周期重新建立缓存，避免跨计算图复用已失效的激活值。
- 每个 HIP Stream 使用独立条目，缓存内存按分配逆序释放，符合 llama.cpp 设备内存池的 LIFO 生命周期。
- 未命中、非 RDNA3 或不安全的多 HIP Graph replay 场景继续使用 Official 临时量化路径。

该优化复用的是 MatVec 输入激活的临时 Q8_1 表示，不是模型会话的 KV Cache，也不改变权重格式、采样参数或输出语义。

### 实现位置

- `vendor/llama.cpp-official/ggml/src/ggml-cuda/mmvq.cu`：Official 基线在每次 MatVec 调用中分配临时 Q8_1 Buffer 并执行量化。
- `vendor/llama.cpp-amd/ggml/src/ggml-cuda/common.cuh`：在 CUDA/HIP Backend Context 中持有缓存状态。
- `vendor/llama.cpp-amd/ggml/src/ggml-cuda/mmvq.cuh`：声明缓存生命周期接口。
- `vendor/llama.cpp-amd/ggml/src/ggml-cuda/mmvq.cu`：识别可复用激活、维护缓存并接入 Q8_1 量化入口。
- `vendor/llama.cpp-amd/ggml/src/ggml-cuda/ggml-cuda.cu`：在计算图执行边界准备、禁用和释放缓存。

Host 侧通过 `GGML_CUDA_CC_IS_RDNA3(...)` 读取运行时设备架构，不依赖全局 `-DRDNA3` 编译参数。设备端 HIP 编译仍由目标架构宏选择 RDNA3 指令，因此新服务器使用正式部署脚本构建即可自动分派，非 RDNA3 设备不会启用该缓存。

### 算子归因证据

相同的 `Prefill=512`、`Decode=128`、`repetitions=3` 与 `top_kernels=20` 设置下：

| 指标 | Official | AMD 激活复用 | 变化 |
| --- | ---: | ---: | ---: |
| Decode Q8_1 调用次数 | 134,784 | 77,184 | -42.74% |
| Decode Q8_1 总耗时 | 285.048 ms | 171.822 ms | -39.72% |
| Q8_1 平均单次耗时 | 2.115 μs | 2.226 μs | 不作为收益来源 |
| profiler 下 Decode | 52.8507 tok/s | 56.9230 tok/s | +7.71% |

收益来自删除重复量化调用，而不是让单次 Q8_1 Kernel 更快。`rocprofv3` 会引入额外开销，因此表中的 profiler 吞吐只用于归因，最终性能结论采用下方普通服务测试。

AMD Q6_K × Q8_1 专用路径在最终干净构建中仍为 `selected=81,024`、`dispatch=81,024`、`fallback=0`，说明 Host 运行时架构判断没有破坏已有 RDNA3 分派。

## 优化二：融合 Residual Add、RMSNorm 与权重缩放

### 原始逻辑图与实际执行方式

模型的残差归一化路径原本由三个连续 GGML 节点完成：

```text
residual_input + residual_skip
              │
              ▼
             ADD ───────────────► residual_output
              │
              ▼
          RMS_NORM
              │
              ▼
        MUL(norm_weight) ────────► normalized_output
```

上图是 GGML 的逻辑节点，不等同于三个独立 GPU Kernel。Official llama.cpp 已经能够把后两个节点 `RMS_NORM → MUL` 交给 `ggml_cuda_op_rms_norm_fused()`，因此原来的真实执行路径是：

```text
Official：Binary Add Kernel
              │ 写 residual_output
              ▼
          重新读取 residual_output
              │
              ▼
          RMSNorm + MUL 融合 Kernel ──► normalized_output

AMD：     Residual Add + RMSNorm + MUL 融合 Kernel
              ├────────────────────────► residual_output
              └────────────────────────► normalized_output
```

因此本项目不是重复实现 Official 已有的 `RMSNorm + MUL` 融合，而是把无法被原融合器覆盖的前置 Residual Add 一并纳入。匹配成功时，GPU Kernel 启动数由两个降为一个；按逻辑张量流量计算，Official 至少读取 `input + skip + residual_output + norm_weight` 四份数据并写出两个结果，AMD 读取 `input + skip + norm_weight` 三份数据并写出相同的两个结果，省去一次完整残差张量回读。

### RDNA3 实现

- 使用 `float4` 向量化加载和存储，一次处理四个 F32 元素。
- 每个线程先在寄存器中保留残差和平方和，同时写出后续网络仍需消费的残差结果。
- 使用 Wave32 shuffle 完成 Wave 内归约，再通过少量 LDS 共享内存合并各个 Wave 的平方和。
- 只计算一次 `rsqrt(sum(x²) / width + epsilon)`，随后在寄存器中完成归一化与权重缩放。
- 根据每行向量数量选择 256 或 128 线程 Workgroup，每线程处理 1–8 个 `float4`，不依赖模型专属 Shape 硬编码。
- Kernel 使用当前 HIP Stream，保持原计算图的执行顺序。

### 图匹配与安全边界

融合仅在以下条件同时满足时启用：

- 三个节点严格为 `ADD → RMS_NORM → MUL`，且数据依赖完全匹配。
- 输入、输出和归一化权重均为连续 F32 张量，Shape 相容且地址满足 `float4` 对齐。
- 归一化权重为单行并覆盖完整隐藏维度。
- 两个必要输出不存在不安全的局部别名，权重不会与输出内存重叠。
- 行宽可由通用的 128/256 线程向量分区覆盖。

不满足条件时，图匹配器记录明确的 fallback reason，并继续执行 Official 节点，不改变模型语义。

### 实现位置

- `vendor/llama.cpp-amd/ggml/src/ggml-hip/amd-kernels/residual-rmsnorm.hip`：RDNA3 Wave32 向量化融合 Kernel 与通用 Workgroup 分区。
- `vendor/llama.cpp-amd/ggml/src/ggml-hip/amd-kernels/residual-rmsnorm.hpp`：能力检查和启动接口。
- `vendor/llama.cpp-amd/ggml/src/ggml-cuda/ggml-cuda.cu`：子图识别、别名检查、fallback 记录和 Backend 分派。
- `vendor/llama.cpp-amd/.fastagentfactory-kernel-catalog.json`：稳定 Kernel ID、名称和作用说明。
- `vendor/llama.cpp-official/ggml/src/ggml-cuda/ggml-cuda.cu` 与 `norm.cu`：Official 基线的 `RMS_NORM → MUL` 匹配和融合 Kernel 分派。

### 算子归因证据

最终 Decode 算子分析中，自定义融合 Kernel 的 `selected=11,520`、`dispatch=11,520`、`fallback=0`。被融合掉的 Official Kernel 调用同步减少：

| 指标 | Official | AMD 融合后 | 变化 |
| --- | ---: | ---: | ---: |
| RMSNorm 调用次数 | 50,304 | 38,784 | -11,520（-22.90%） |
| RMSNorm 总耗时 | 157.064 ms | 121.322 ms | -22.76% |
| Binary Add 调用次数 | 53,760 | 42,240 | -11,520（-21.43%） |
| Binary Add 总耗时 | 143.785 ms | 117.867 ms | -18.03% |
| AMD Residual RMSNorm 分派 | 0 | 11,520 | 全部成功 |

`GGML_SCHED_DEBUG` 展示的是融合前的逻辑计算图，因此其中的 `ADD` 和 `RMS_NORM` 节点数不会消失；实际执行是否融合应以 Host 分派计数和 `rocprofv3` Kernel 调用次数为准。

## 普通服务性能

| 指标 | Official | AMD 整体实现 | 变化 |
| --- | ---: | ---: | ---: |
| Decode 平均吞吐 | 84.0867 tok/s | 88.8320 tok/s | +5.64% |
| Decode 标准差 | 0.1943 tok/s | 0.1718 tok/s | — |
| Prompt 平均耗时 | 482.680 ms | 478.321 ms | -0.90% |
| 每次输出 Token | 256 | 256 | 相同 |
| 输出哈希 | `6c7bf1…d473` | `6c7bf1…d473` | 相同 |

测试使用 `temperature=0`、`seed=42`、冷 Prompt Cache、单并发，并在同一服务器时段依次重载 Official 与 AMD 实现。完整 Prompt、每次计量值和环境条件保存在结构化数据中。

## 数据

- [最终 AMD 算子分析](../data/2026-07-19-amd-q8-activation-reuse-operator-analysis-6ae1c6a1.json)
- [Official/AMD 普通服务成对对比](../data/2026-07-19-q8-activation-reuse-service-comparison.json)
- [Official 算子基线](../data/2026-07-18-official-operator-analysis-f9a42bd7.json)

## 适用边界

- 当前仅在 RDNA3/gfx1100 上启用并完成实测。
- 只缓存计算图内存在重复消费者的 F32 MatVec 激活，单消费者不会增加持久临时分配。
- HIP Graph 实际 replay 时仅在单图生命周期可安全持有缓存；多图情形保留 Official 路径。
- Residual RMSNorm 融合只处理满足通用连续 F32、向量对齐、Shape 和别名安全约束的子图，其他布局保留 Official 路径。
- 模型、量化布局或 llama.cpp 上游图结构变化后必须重新执行算子命中与普通服务成对测试。
