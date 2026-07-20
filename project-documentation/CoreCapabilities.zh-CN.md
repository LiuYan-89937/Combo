[English](CoreCapabilities.md) | [简体中文](CoreCapabilities.zh-CN.md)

# 核心能力介绍

FastAgentFactory 的核心能力由多个可组合后端子系统构成。能力是否对某个 Agent 可用，需要同时满足 Package Contract、Assembly Binding、运行时环境和权限策略，不能只根据代码仓库中“存在某个模块”判断。

## 1. Agent 生命周期

### Agent 制造

从自然语言需求和附件生成完整 AgentPackage，包括 Pattern、Prompt、模型、工具、Skill、知识、资源和依赖声明。制造过程有工作区隔离、作者工具、Checkpoint、Trace 和验证。

### Agent 进化

选择已有包，结合目标和相关失败 Trace 做定向修改，并在失败时恢复。进化复用制造底座，但增加目标归属门控和变更范围约束。

### Package 管理

支持枚举、选择、初始化、运行、关闭、删除 AgentPackage 实例，并刷新 Agent Registry。Package 是部署和版本管理的核心单元。

## 2. RuntimeKernel 与图编排

- YAML Pattern 编译为 LangGraph `StateGraph<RuntimeGraphState>`；
- NodeRegistry 解耦图拓扑与节点实现；
- 支持认知、操作、终止、保留节点和子图；
- 节点统一经过 system wrapper、node wrapper、hook、Trace 和 state patch 校验；
- 支持条件路由、中断、重试、超时、取消和完成状态；
- 支持 Package 自定义 state section 与读写边界。

当前主 Pattern 是 `react_agent` 和 `plan_and_execute`。前者适合动态工具循环，后者提供独立计划状态和 planner/executor/final 角色分离。

## 3. 模型系统

### 模型池

Model Pool 管理 chat、embedding 和 image-generation profile、artifact、默认角色、能力元数据与使用记录。模型 Contract 可按角色绑定 main、task、compression，也可为模型工具单独绑定图像模型。

### 运行时模型选择

- AgentPackage 通过 Model Binding 声明模型来源和能力要求；
- `local_registry` 指向明确 profile；
- `local_default` 解析模型池中对应角色的默认 profile，主要用于受控系统包；
- 请求可通过 `model_profile_overrides.main` 覆盖本轮 main profile；
- 绑定解析时校验 kind、enabled、artifact 和可运行性。

当前实现的“默认模型”仍来自 ModelPoolStore 的默认 profile；Endpoint 的环境变量只负责推理服务连接，不能替代缺失的 profile 元数据。

### 推理强度

前端请求可在 `runtime_config.user_config.reasoning_intensity` 中传递 0 到运行时上限的强度。RuntimeKernel 在模型调用前把强度映射到模型的 reasoning settings；不支持推理配置的 profile 仍受其能力边界限制。

### 模型操作与多模态

`ModelOperationService` 提供按角色执行模型操作的统一入口。图像生成属于 Model Tool Binding，结果写入 Artifact Store；它不是 chat 模型的隐式副作用，也不应在业务包中依赖未经声明的模型 ID。

## 4. 工具系统

### 工具来源

- Builtin Tools：工作区文件、知识、调度等平台内置能力；
- Package Python Tools：随 AgentPackage 发布的业务工具；
- Instance Extensions：实例级扩展工具；
- MCP Tools：通过宿主 MCP Gateway 暴露给隔离运行时；
- SkillHub Tools/Skills：通过 SkillHub Gateway 发现和加载；
- Model Tools：图像生成、编辑等带独立模型 Binding 的工具；
- Runtime Internal Tools：例如 `runtime_plan`，由 RuntimeKernel 直接执行。

### 工具治理

ToolGateway 统一处理 Schema、Resource、风险、审批、entrypoint、结果投影和 ToolObservation。节点级 Binding 控制模型可见工具，执行前再按来源节点校验，形成“可见性 + 执行”双重边界。

## 5. Session、Checkpoint 与状态

- Factory Session 保存产品层会话、当前模式和前端恢复信息；
- Agent Session 保存某个 Package 的运行会话元数据；
- LangGraph Checkpointer 保存线程状态，支持继续运行和中断恢复；
- Package State Contract 声明业务状态 Schema、默认值和节点读写约束；
- RuntimeState 保存消息、计划、工具、执行、可观测和运行配置。

聊天记录、Checkpoint、Memory、Trace 是四种不同数据。删除聊天记录不必然删除 checkpoint 或 Trace；清理策略应按存储边界执行。

## 6. Context 与 Memory

### Context Assembly

Context Contract 配置检索、候选数量、最低分、总条数、总 token 和分来源限制。只有启用并注册的 source 才参与自动检索与装配。

例如：

```json
{
  "retrieval": {
    "enabled": true,
    "source_ids": ["cross_session_memory"]
  },
  "assembly": {
    "max_items_total": 8,
    "max_tokens_total": 1200,
    "per_source_limits": {
      "cross_session_memory": 4
    }
  }
}
```

这里表示总共最多装配 8 项、1200 token，其中跨会话记忆最多 4 项；它不表示 resource、scheduler、artifact、knowledge 和 trace 会自动各注入若干条。

### Memory

Memory System 负责记忆提取、分段、排名、命名空间、存储、后台写入和注入。Memory Contract 决定是否开启、检索范围和装配预算。跨会话记忆应只返回与当前请求相关的候选内容。

记忆写入频率由 `background.write_interval_turns` 控制，单位是完成的用户轮次。默认值为 `3`，表示第 3、6、9 个用户轮次完成后，将最近最多 3 个用户轮次组成一个片段，异步执行长期记忆提取与去重写入。失败的运行不会触发写入。

- Factory 默认配置可通过 `.env` 的 `AGENTFACTORY_MEMORY_WRITE_INTERVAL_TURNS` 调整。
- AgentPackage 在 `contracts/memory.json` 中显式声明 `background.write_interval_turns` 时，以包 Contract 为准。
- `write_enabled` 控制是否写入，`injection_enabled` 控制后续会话是否检索并注入相关记忆，两者是独立开关。

## 7. Knowledge / RAG

- Knowledge Contract 定义根目录、catalog、RAG store 和摄取设置；
- Knowledge Runtime 负责索引、检索和文档访问；
- 后台 ingestion worker 处理知识源准备；
- `knowledge` 工具提供 search/open/read 等显式操作；
- system wrapper 可向模型说明知识能力和使用规则。

Knowledge 服务注册到 RuntimeServices，不代表知识正文自动拼入 Prompt。对大部分业务包，显式检索比全量注入更可控。

## 8. Resource 与 Secret

Resource Contract 声明工具依赖的配置项和敏感资源。ResourceStore 按 package ID 管理值，EnvironmentResolver 在运行前解析环境与资源，ToolGateway 在调用时只向对应 entrypoint 提供所需资源。

Resource 的状态可以被前端管理，但敏感值不应写入 Prompt、Trace 或 AgentPackage。容器只应获得当前包当前工具所需的最小资源集合。

## 9. Scheduler

Scheduler System 提供：

- date、interval、cron trigger；
- job、run、lease 持久化；
- 创建、更新、删除、查看和运行记录；
- 失败策略、自动暂停和反馈摘要；
- AgentPackage、Agent Group 等目标类型；
- 独立 scheduler run session。

Scheduler Contract 构建 Scheduler Runtime，并把 scheduler 工具资源提供给工具系统。调度状态可通过专用工具或 API 查询，不需要每轮注入聊天上下文。

## 10. Artifact 与交付

Artifact Store 管理 Agent 产生的报告、文本、图片和其他文件，返回可追踪的引用。工作区文件与 Artifact 的语义不同：前者是可操作的任务空间，后者是明确登记的交付结果。

模型工具生成图片时必须有 Artifact Contract；生成服务把输出保存为当前运行可访问的资产，再由最终回答引用。

## 11. Trace、可观测与 Benchmark

- 节点进入、完成、错误和耗时事件；
- 工具调用、风险决策、审批和 ToolObservation；
- trace/span/run 标识与持久化；
- Runtime 状态事件和前端节点事件；
- 失败域分类与可抑制的基础设施 Trace；
- Harness/Benchmark 用于场景验证和结果报告。

Trace 是诊断数据，不是默认对话上下文。只有诊断、进化或专用检视流程明确读取它时才进入分析。

## 12. 多 Agent 协作

Collaboration System 和 Agent Group System 支持主 Agent、worker、任务派发、授权工件复制、状态回传和最终汇总。协作上下文通过运行时配置开启，并动态增加有限的协作工具，同时排除不适合 worker 的工具。

协作不是多个 Agent 共享同一个任意可写目录。材料授权、结果回收和 Artifact 复制由 orchestrator 控制。

## 13. 运行隔离与扩展

- 普通 AgentPackage 使用 Docker Runtime；
- 系统包可使用受信任 Host Runtime；
- runtime、workdir、artifacts 和 extensions 使用独立挂载边界；
- MCP 与 SkillHub 通过宿主 Gateway 向容器提供服务；
- Package Tool、Builtin Tool 和扩展工具统一进入 Registry/Gateway；
- 路径策略和 `builtin_allow_external_paths` 控制文件访问边界。

## 14. 本地与外部推理

模型 profile 支持本地 AMD ROCm/llama.cpp 路径和外部 OpenAI-compatible 推理配置。Model Pool 保存能力与运行参数，Endpoint 配置负责服务地址。部署能力与 Agent 逻辑分离，因此更换推理后端不应要求重写 Pattern。

## 能力落地检查表

一个能力要真正可用，至少检查以下链路：

```text
Package 声明
→ Contract 可解析
→ Builder 注册 service/resource/tool
→ Assembly Binding 允许目标节点使用
→ 运行环境和 Resource 完整
→ Pattern 节点实际触发
→ Trace/Artifact/State 可观察结果
```

只检查其中一层容易得到错误结论。例如工具存在于 Registry，不代表当前节点可见；知识文件存在，不代表已索引；Scheduler 已构建，不代表每轮上下文包含其状态。
