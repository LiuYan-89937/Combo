# 工厂 RuntimeKernel 阶段总原则

Factory 阶段是否必须使用 ReAct，取决于该阶段是否向模型暴露工具。

- 纯规划、纯判断、纯结构化输出阶段，可以直接调用模型并要求结构化结果。
- 任何阶段只要需要读取文件、搜索、执行 shell、运行测试、写文件、修复代码或调用外部工具，就必须使用 LangGraph 原生 ReAct 闭环：`model -> tool_calls -> ToolNode -> observation -> model`。
- ReAct 阶段不能在阶段代码中绕过 `ToolNode` 手写工具调用；工具结果必须以 Observation 回到模型，再由模型决定继续检查、请求用户补全、失败、阻塞或产出最终结果。
- 当前必须 ReAct：`assembly_spec_generation` 使用 validator-observation ReAct。
- `resource_and_condition_planning` 已清空旧子图，阶段行为等待基于统一工具系统重新设计。
- 后续实现时必须 ReAct：`package_generation`、`harness_generation_and_test`、`repair_or_finalize`。

# Deferred TODO

- 十个阶段闭环完成后，统一界定“工厂制造出来的 Agent 能力边界”，并把它作为各阶段环境提示词和阶段配置的共同来源。
- 能力边界需要说明：当前可制造 Agent 的交互形态、运行环境、工具能力、资源依赖、上下文/记忆策略、审批/安全能力、输出形态、不可承诺能力。
- 能力边界不能分散硬编码在各阶段 prompt 中；应沉淀为统一配置或上下文模块，再由各阶段按职责引用。
- 第一阶段需求澄清、后续资源准备和 package 生成都必须基于这份能力边界，避免模型提出当前 Factory 无法落地的设想。

# requirement_capture
中文：需求捕获
English: Requirement Capture
建议结构：强烈建议使用 subGraph
原因：捕获并澄清用户要什么 Agent，并生成用户确认过的业务制造计划。当前阶段合并原“需求捕获”和“计划完善”职责：先做多轮需求澄清，再展示固定标题的纯文本业务计划，由用户选择继续或输入修改意见。
ReAct 要求：当前不暴露工具，可直接结构化输出；如果未来引入文件读取、搜索或其他工具，必须改为 ReAct。


# runtime_pattern_selection
中文：运行模式选择
English: Runtime Pattern Selection
建议结构：先做单节点
原因：基于业务制造计划选择 RuntimeKernel pattern，例如 react_agent、clarify_then_act、workflow 等。本阶段只能读取 PatternCatalogItemSpec 摘要，包括 pattern_id、kind、embeddable、version、name、description、metadata；不能把完整 Pattern YAML、nodes、edges、wrappers 或 contracts 传给模型。
ReAct 要求：当前不暴露工具，可直接结构化输出。


# graph_behavior_planning
中文：图行为规划
English: Graph Behavior Planning
建议结构：轻量 subGraph
原因：按选定 pattern 规划节点职责、节点顺序、关键路由和中断点。本阶段只能把业务制造计划、runtime_pattern_selection 和 PatternStructureSummary 传给模型；PatternStructureSummary 由 RuntimeKernel 从完整 Pattern 派生，只包含节点摘要、路由摘要、中断点和终止摘要，不包含完整 YAML、node config、wrapper config、工具实现、资源探测结果或 AssemblySpec。
ReAct 要求：当前不暴露工具，可直接结构化输出。


# node_strategy_planning
中文：节点策略规划
English: Node Strategy Planning
建议结构：强烈建议使用 subGraph
原因：给每个节点规划 wrapper、上下文策略、记忆策略、policy 和 tool visibility。本阶段写可装配级别的策略引用和配置意图，不写 wrapper 实现代码、prompt 正文、工具实现、数据库/API 方案、资源探测结论或 AssemblySpec。模型只能读取业务制造计划、runtime_pattern_selection、graph_behavior_plan、PatternStructureSummary、wrapper catalog 和 strategy catalog。
ReAct 要求：当前不暴露工具，可直接结构化输出。


# tool_capability_planning
中文：工具能力规划
English: Tool Capability Planning
建议结构：轻量 subGraph
原因：规划需要哪些工具能力、哪些节点可见、哪些需要审批；不在本阶段生成具体工具代码。
ReAct 要求：当前不暴露工具，可直接结构化输出。


# resource_and_condition_planning
中文：资源与条件规划
English: Resource And Condition Planning
建议结构：强烈建议使用 subGraph
原因：判断工具和策略需要哪些前置资源、环境、权限和外部服务。
当前状态：旧资源准备子图已清空，仅保留 `resource_condition_plan`、`resource_file_path` 和空 `factory_resources.json` 输出骨架。
ReAct 要求：待重新设计。后续是否暴露工具、暴露哪些工具、如何审批和如何转 observation，必须基于统一工具系统重新确定。


# assembly_spec_generation
中文：装配规格生成
English: Assembly Spec Generation
建议结构：强烈建议使用 subGraph
原因：生成 AgentAssemblySpec draft，并为后续 package、harness、repair 提供统一装配输入。draft 与校验报告写入 `.agentfactory/assemblies/<factory_run_id>/`。
ReAct 要求：必须使用 validator-observation ReAct。模型生成 draft，系统调用 AgentAssemblyValidator 校验，校验错误作为 observation 回到模型继续修正；本阶段不暴露 shell/file 工具，不使用 ToolNode。


# package_generation
中文：包生成
English: Package Generation
建议结构：强烈建议使用 subGraph
原因：生成工具代码、配置文件和 AgentPackage 结构。
ReAct 要求：后续实现时必须 ReAct。本阶段会写文件、生成代码、检查目录和读取资源文件，不能绕过 `ToolNode`。


# harness_generation_and_test
中文：Harness 生成与测试
English: Harness Generation And Test
建议结构：强烈建议使用 subGraph
原因：生成 harness，驱动 RuntimeKernel 运行，并输出可返厂维修的检测报告。
ReAct 要求：后续实现时必须 ReAct。本阶段会运行测试、读取 trace/report、可能执行 shell 或检查文件，工具结果必须作为 Observation 回到模型。


# repair_or_finalize
中文：修复或定稿
English: Repair Or Finalize
建议结构：强烈建议使用 subGraph
原因：根据 harness/trace 修复 spec、工具和 wrapper 配置；通过后产出最终出厂结果。
ReAct 要求：后续实现时必须 ReAct。本阶段会读取 harness 证据、修改 spec 或代码、再验证修复结果。
