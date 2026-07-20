[English](ROCmOptimizations.md) | [简体中文](ROCmOptimizations.zh-CN.md)

# AMD RDNA3 推理优化改动说明

## 结论

在 Qwen3.6-35B-A3B Q6_K、gfx1100、单并发、256K 上下文、Q8_0 KV Cache 与 Flash Attention 开启的相同条件下，AMD 实现包含三项已命中的 Decode 优化：复用同一 F32 激活的 Q8_1 临时量化结果；将 `Residual Add + RMSNorm + 权重缩放` 融合为一个 RDNA3 HIP Kernel；以及使用原生 HIP Wave32 Kernel 执行普通二维 Q6_K × Q8_1 MatVec。前两项与已有 AMD Kernel 集合将正常服务 Decode 吞吐从 Official 的 `84.0867 tok/s` 提升到 `88.8320 tok/s`，提升 `5.64%`；Native Q6_K MMVQ 在该 AMD 基线上进一步取得 `0.94%` 的五轮平均增益。

两组各包含 1 次预热和 5 次计量，计量标准差分别为 `0.1943 tok/s` 与 `0.1718 tok/s`。Official 与 AMD 的 5 次归一化流式输出哈希一致，均为 `6c7bf1d59882869591634b94616d151349bfdf6081fde7ea45686fdd3a83d473`。

`5.64%` 是两项优化与当前 AMD Kernel 集合共同启用时的端到端综合收益。算子分析能够分别证明 Q8_1 重复调用被删除、Residual RMSNorm 融合实际命中，但当前数据没有通过逐项关闭优化进行消融，因此不把综合收益错误拆分到某一个 Kernel。

## 与 Official 原实现的总体对比

| 优化位置 | Official 原实现 | AMD 实现 | 直接减少的工作 |
| --- | --- | --- | --- |
| MatVec 输入量化 | 每次 `ggml_cuda_mul_mat_vec_q()` 调用都分配临时 Q8_1 Buffer，并对传入的 F32 激活重新量化 | 在单次计算图内识别具有多个 MatVec 消费者的同一激活，按设备数据与布局复用已生成的 Q8_1 Buffer | Q8_1 Kernel 调用减少 57,600 次，即 `42.74%` |
| 残差归一化 | Residual Add 单独执行；llama.cpp 已有的融合路径再执行 `RMSNorm + 权重 MUL`，合计两个 Kernel | 一个 RDNA3 HIP Kernel 同时完成 Residual Add、RMSNorm 和权重缩放，并保留两个必要输出 | 每个命中子图由两个 Kernel 降为一个；减少一次残差显存回读和一次 Kernel 启动 |
| 普通 Q6_K MatVec | CUDA/HIP 共用 Kernel 使用两个 Wave 协作计算一个输出行，并通过 LDS 合并跨 Wave 部分和 | 原生 HIP Kernel 使用一个 Wave32 计算一个输出行，四个 Wave 共享 LDS 激活，并采用双累加链 | 删除每行的跨 Wave LDS 写入、同步和合并，减少 Workgroup 数并复用激活读取 |
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

## 优化三：原生 RDNA3 Q6_K × Q8_1 MMVQ

### 基线瓶颈

变体追踪显示，Decode 中普通二维、单 Token、无 IDs 的 Q6_K MatVec 是最大的可独立改写族。主要动态 Shape 的 Profiler 占比分别为：

| M × K | 调用次数 | 总耗时占比 |
| --- | ---: | ---: |
| 8192 × 2048 | 5,120 | 10.99% |
| 4096 × 2048 | 3,840 | 6.01% |
| 248320 × 2048 | 128 | 5.90% |
| 2048 × 4096 | 3,840 | 4.68% |

实现不匹配这些具体数值，而是接受运行时 M、K 和量化行跨度；表格只用于说明真实工作负载的热点分布。

### 与原实现的差异

原 CUDA/HIP 共用 MMVQ 路径为 Q6_K 分配两个 Wave 共同计算一个输出行。两个 Wave 分别处理部分 K Block，随后把第二个 Wave 的部分和写入 LDS，通过 Workgroup 同步后由第一个 Wave 合并并做 Wave32 归约。

Native RDNA3 Kernel 改为：

- 每个 Wave32 独立计算一个输出行，不再执行跨 Wave 部分和写入与同步。
- 每个 Workgroup 包含四个 Wave；四行计算共享一次载入 LDS 的 Q8_1 激活。
- 每个 Lane 交错处理量化 Block，并使用两条独立累加链降低连续 `sudot4` 的数据依赖。
- Q6_K 解码、精确零点修正和缩放继续复用已验证的 RDNA3 mixed-sign `sudot4` 点积实现。
- M、K、量化行跨度和动态 LDS 大小全部由运行时配置；只在普通二维、单 Token、无 IDs、无额外融合且 LDS 容量满足 gfx1100 约束时启用。
- 其他布局继续进入原 MMVQ 分派，不改变 MoE、批量或融合路径。

### 命中与性能证据

算子分析中 Native Kernel 在 Decode 阶段 `selected=11,584`、`dispatch=11,584`、`fallback=0`，并在 `rocprofv3` 中出现同等数量的 GPU Kernel 事件。固定 Prompt、`temperature=0`、`seed=42`、`cache_prompt=false`、每轮 128 个输出 Token 的正常服务结果为：

| 指标 | AMD 原 MMVQ | AMD Native Q6_K MMVQ | 变化 |
| --- | ---: | ---: | ---: |
| 五轮平均 Decode | 90.4832 tok/s | 91.3322 tok/s | +0.94% |
| 五轮标准差 | 0.0797 tok/s | 0.4032 tok/s | — |
| 去除重载后首轮的四轮平均 | 90.5183 tok/s | 91.5122 tok/s | +1.10% |
| 输出 Token 哈希 | `8015c7cc…b4e94` | `8015c7cc…b4e94` | 完全一致 |

五轮统计保留每次实现重载后的第一轮，没有通过删除低值扩大收益；四轮稳定态只作为补充观察。

### 实现位置

- `vendor/llama.cpp-amd/ggml/src/ggml-hip/amd-kernels/q6-k-mmvq-native.hip`：原生 RDNA3 Wave32 Kernel。
- `vendor/llama.cpp-amd/ggml/src/ggml-hip/amd-kernels/q6-k-mmvq-native.hpp`：动态启动契约与能力检查。
- `vendor/llama.cpp-amd/ggml/src/ggml-hip/amd-kernels/q6-k-mmvq.cuh`：共享的 RDNA3 Q6_K 点积实现。
- `vendor/llama.cpp-amd/ggml/src/ggml-cuda/mmvq.cu`：Host 架构和张量布局分派。
- `vendor/llama.cpp-amd/.fastagentfactory-kernel-catalog.json`：稳定 Kernel ID 与作用说明。

## 普通服务性能

| 指标 | Official | AMD 整体实现 | 变化 |
| --- | ---: | ---: | ---: |
| Decode 平均吞吐 | 84.0867 tok/s | 88.8320 tok/s | +5.64% |
| Decode 标准差 | 0.1943 tok/s | 0.1718 tok/s | — |
| Prompt 平均耗时 | 482.680 ms | 478.321 ms | -0.90% |
| 每次输出 Token | 256 | 256 | 相同 |
| 输出哈希 | `6c7bf1…d473` | `6c7bf1…d473` | 相同 |

测试使用 `temperature=0`、`seed=42`、冷 Prompt Cache、单并发，并在同一服务器时段依次重载 Official 与 AMD 实现。完整 Prompt、每次计量值和环境条件保存在结构化数据中。

## 优化四：Q8_0 × Q8_1 MMVQ 动态 Wave32/Wave64 分派

Decode 中普通二维、单 Token、无 IDs 且无额外融合的 Q8_0 MatVec 增加两个独立编译的原生 HIP 变体。Host 分派器不读取模型名称，也不匹配固定 Shape，而是根据运行时 K、输出行数、动态 LDS、Kernel Occupancy、物理 Wave 大小和每个 Workgroup 的输出行数估算调度成本。`AGENTFACTORY_AMD_Q8_MMVQ_WAVE_MODE=official|wave32|wave64|auto` 仅用于独立消融；生产默认使用 `auto`。

- Wave32：一个物理 Wave32 计算一行，每四个 Lane 处理一个 Q8_0 Block，四个 Wave 共享 LDS 中的 Q8_1 激活。
- Wave64：一个物理 Wave64 划分为两个独立的 32-Lane 输出组，同时计算两行；它保持 Wave32 的 Block 映射与浮点累加顺序，避免不同 Wave 宽度改变贪心解码 Token。
- Auto：查询两个已编译 Kernel 的 VGPR、LDS 与活跃 Workgroup 上限，再结合当前任务几何选择成本更低的变体。当前 `2048 × 1 × 512` 热点选择 Wave32。

编译产物的 AMDGPU Metadata 已直接验证：两个 Kernel 的 `.wavefront_size` 分别为 `32` 和 `64`，不是只修改名称。两者均使用 18 个 SGPR、16 个 VGPR，最大 Workgroup 为 128 线程。

### 算子归因

同一 AMD 二进制内强制回到 Official Q8 路径后再分别强制两个变体，因此该消融不会混入 Q6_K、Residual RMSNorm 等其他 AMD 优化差异：

| Q8_0 普通 Decode 路径 | 调用次数 | Kernel 总耗时 | 相对 Official |
| --- | ---: | ---: | ---: |
| Official | 5,120 | 38.775 ms | — |
| Native Wave32 | 5,120 | 20.507 ms | -47.11% |
| Native Wave64 | 5,120 | 22.450 ms | -42.10% |

Auto 的 Host 计数为 `selected=5,120`、`dispatch=5,120`、`fallback=0`，对应的 rocprof GPU 事件也是 5,120 次，最终选择 `amd.q8_0_q8_1_mmvq_native_rdna3.wave32`。

## RDNA3 MMQ 输出列 Tile 优化

Official 的 MMQ 选择器以减少输出列 Tile 数量为主要目标。在 gfx1100 的 Wave32 执行模型下，它会为本次模型的 Prefill 路径选择 `J=128`。更大的 `J` 虽然减少了 Tile 数量，却同时扩大每个 Workgroup 的寄存器与 LDS 工作集，降低了 RDNA3 上的有效占用率。

AMD 实现保留 Official 的量化解码、点积、累加、Stream-K 和边界处理，只调整 RDNA3 的配置选择：输出列 Tile 上限由固定的 128 改为 `2 × 物理 Wave 宽度`。gfx1100 使用 Wave32，因此选择 `J=64`。该规则来自设备执行宽度，不依赖模型名称或某个固定输入 Shape；非 RDNA3 设备继续使用 Official 路径。

固定 5,595 Prompt Token、32 输出 Token、单并发、Q8_0 KV、`temperature=0`、`seed=42`、关闭 Prompt Cache 的五轮正常服务结果如下：

| 实现 | 平均 Prompt TPS | 相对变化 | 输出一致性 |
|---|---:|---:|---|
| Official `J=128` | 1,992.95 | 基线 | 一致 |
| AMD `J=64` | 2,403.83 | +20.62% | 一致 |

在关闭 HIP Graph replay 的 4,096 Token rocprof 归因中，两侧均执行 1,920 次 MMQ Kernel。Official 总耗时为 1,124.289 ms，AMD 为 730.378 ms，下降 35.04%。`amd.mmq_rdna3` 的 Host 计数为 `selected=1,920`、`dispatch=1,920`、`fallback=0`，说明性能变化确实来自 MMQ Tile 配置，而不是跳过计算或其他服务环节。

### 正常服务吞吐

每种模式独立加载相同 256K、单槽位服务，预热一次后计量五次，每次固定生成 128 Token：

| 模式 | Decode 平均吞吐 | 标准差 | 相对 Official |
| --- | ---: | ---: | ---: |
| Official Q8 路径 | 87.4755 tok/s | 0.0681 | — |
| 强制 Wave32 | 88.2386 tok/s | 0.0107 | +0.87% |
| 强制 Wave64 | 88.1969 tok/s | 0.0530 | +0.82% |
| Auto（选择 Wave32） | 88.3035 tok/s | 0.0406 | +0.95% |

四组共 20 次计量输出哈希全部为 `91bcfac1…f5c8135`。Profiler 只用于 Kernel 归因；表中最终收益来自启用正常 HIP Graph 与普通 HTTP 推理服务的计量。

## MTP 推测解码与并发 QPS

当前 Qwen3.6 GGUF 保留了 NextN/MTP 层。推理 Profile 开启后，llama-server 使用 `--spec-type draft-mtp`，每轮最多生成 3 个候选 Token，再由 Target Model 批量验证。服务只有在 `/slots` 返回 `speculative=true` 后才进入 Ready；普通性能测试从 llama.cpp 最终 `timings` 直接读取候选数与接受数，避免用启动参数冒充实际命中。

同一 790 Token Prompt、128 输出 Token、冷 Prompt Cache、单 Slot、`temperature=0`、`seed=42` 下，每个状态预热一次并计量五次：

| 实现 | MTP | Decode 平均 | 标准差 | 接受率 | 相对本实现关闭态 |
| --- | --- | ---: | ---: | ---: | ---: |
| Official | 关闭 | 84.4307 tok/s | 0.1212 | — | — |
| Official | 开启 | 117.9770 tok/s | 0.2013 | 62.69% | +39.73% |
| AMD | 关闭 | 88.0247 tok/s | 1.5001 | — | — |
| AMD | 开启 | 117.0653 tok/s | 0.0125 | 60.00% | +32.99% |

MTP 的收益来自一次 Target Forward 接受多个 Token，从而摊薄自回归 Decode 中的权重读取、MMVQ、MoE 路由、逐元素 Kernel 和启动开销；它不会让单次 MMVQ 少读权重，还会增加 MTP Head 的候选生成成本。当前 AMD MTP 比 Official MTP 低 `0.77%`，同时接受率低 2.69 个百分点，说明原来面向单 Token MMVQ 的 AMD 优势在多候选验证路径中被稀释。后续优化应分别归因 MTP Draft Head 和 Target 多 Token 验证路径，不能把非 MTP 的 MMVQ 收益直接外推。

正确性补测对 `reasoning_content + content` 的完整 128 Token 输出计算 SHA256。AMD 的 MTP 开/关输出一致，Official MTP 与 AMD 也一致；Official 关闭 MTP 的输出不同，因此本轮不能宣称四条路径位级一致。所有路径都固定生成 128 Token，这一差异应作为不同批处理/浮点执行路径下的贪心分叉保留，而不能删除不利样本。

并发测试采用闭环 Worker，每个 Worker 完成请求后再发送下一个请求。当前 Profile 只有一个 llama-server Slot，所以 2/4 路是排队压力测试，不代表 2/4 个模型实例并行：

| 实现（MTP 开启） | 客户端并发 | QPS | 聚合输出 TPS | 平均请求延迟 |
| --- | ---: | ---: | ---: | ---: |
| Official | 1 | 0.5751 | 73.61 tok/s | 1.739 s |
| Official | 2 | 0.6040 | 77.31 tok/s | 2.907 s |
| Official | 4 | 0.6055 | 77.51 tok/s | 5.394 s |
| AMD | 1 | 0.5946 | 76.11 tok/s | 1.682 s |
| AMD | 2 | 0.6094 | 78.00 tok/s | 2.897 s |
| AMD | 4 | 0.6351 | 81.29 tok/s | 5.125 s |

单 Slot 在 2 路附近已基本饱和；继续增加并发主要增加排队延迟。这里的聚合输出 TPS 包含每个请求的 790 Token Prefill 和完整请求周期，因此低于只计算 Decode 阶段的 llama.cpp `predicted_per_second`，两者不能互相替代。

## 适用边界

- 当前仅在 RDNA3/gfx1100 上启用并完成实测。
- 只缓存计算图内存在重复消费者的 F32 MatVec 激活，单消费者不会增加持久临时分配。
- HIP Graph 实际 replay 时仅在单图生命周期可安全持有缓存；多图情形保留 Official 路径。
- Residual RMSNorm 融合只处理满足通用连续 F32、向量对齐、Shape 和别名安全约束的子图，其他布局保留 Official 路径。
- 模型、量化布局或 llama.cpp 上游图结构变化后必须重新执行算子命中与普通服务成对测试。
