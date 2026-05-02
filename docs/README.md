# AgentFactory 分步骤开发文档

这组文档用于指导第一版工程实现。`开发规范以及架构初版.md` 保留为架构母文档；本目录按开发顺序拆分，每个文件只描述一个阶段的目标、产物、实现边界和验收标准。

第一版采用 **CLI-first** 路线，不做可视化页面。CLI 是正式操作面，同时底层能力保持 API-ready，方便后续接 Web UI、桌面端或二次开发 SDK。CLI 同时支持普通命令和 Claude Code 风格的斜杠交互命令。

## 阅读顺序

```text
00_development_roadmap.md
  ↓
01_project_skeleton.md
  ↓
02_specs_and_validator.md
  ↓
04_model_llm_interaction.md
  ↓
11_agent_building_primitives.md
  ↓
12_factory_production_runtime.md
  ↓
03_graph_runtime.md
  ↓
04_capabilities_tools_mcp_context.md
  ↓
05_harness.md
  ↓
06_registry_and_isolation.md
  ↓
07_upgrade_patch_release.md
  ↓
08_cli_first_operations.md
  ↓
09_mvp_candidate.md
  ↓
10_future_enhancements.md
```

## 文档职责

| 文件 | 职责 |
| --- | --- |
| `00_development_roadmap.md` | 总体阶段、依赖关系、完成定义 |
| `01_project_skeleton.md` | 搭建 Python 包、目录、CLI 空壳、基础工程配置 |
| `02_specs_and_validator.md` | 实现 AgentPackage 规范模型、加载器、校验器 |
| `04_model_llm_interaction.md` | 实现 ModelService、ProviderAdapter、OpenAI-compatible Chat Completions、FakeModelAdapter |
| `11_agent_building_primitives.md` | 定义 Factory 生产个性化 Agent 的 Instruction、Output、Conversation、Toolset、Knowledge、Guardrail、Handoff、Observability 标准件 |
| `12_factory_production_runtime.md` | 使用 LangGraph StateGraph 实现 Factory 生产 AgentPackage primitives 的生产图、分支、repair 和 stream |
| `03_graph_runtime.md` | 实现 WorkflowRuntime / GraphRuntime、节点、路由、状态、trace、checkpoint |
| `04_capabilities_tools_mcp_context.md` | 实现 Capability、Tool、MCP、Context 的最小闭环 |
| `05_harness.md` | 实现可复现 Harness 和测试报告 |
| `06_registry_and_isolation.md` | 实现文件系统 Registry 和 AgentInstance 进程隔离 |
| `07_upgrade_patch_release.md` | 实现 UpgradeRequest、PatchPlan、ApprovalRecord、PackageDiff、发布和回滚 |
| `08_cli_first_operations.md` | 定义第一版 CLI 命令和成熟 agent CLI 操作体验 |
| `09_mvp_candidate.md` | 记录 MVP 样例候选，框架主干搭完后再最终确定 |
| `10_future_enhancements.md` | 记录 01/02/03 讨论中暂缓的后续增强点 |

## 第一版原则

```text
1. 先骨架，后能力。
2. 先声明式配置，后自动生成。
3. 先 CLI 闭环，后可视化页面。
4. 先文件系统 Registry，后可替换存储。
5. 先统一 Model / LLM 调用边界，后让 Runtime 和 Factory 使用模型。
6. 先标准化 Agent Building Primitives，后让 Factory 生成个性化 Agent。
7. Factory 自己的生产图使用 LangGraph，AgentInstance Runtime 仍按 AgentPackage 声明选择 Workflow 或 Graph。
8. 先保留 MVP 候选，框架主干搭完后再确定最终样例。
9. 每个阶段都要有可运行命令和验收标准。
```
