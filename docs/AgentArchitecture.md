# FastAgentFactory Agent 架构

![FastAgentFactory Agent 系统架构](assets/diagrams/fastagentfactory-agent-architecture.png)

FastAgentFactory 将 Agent 的交互入口、生命周期控制、运行时执行、工具访问和本地模型推理解耦为五层。图中的箭头表示控制流或受控的数据访问关系，不表示所有模块运行在同一个进程。

## 1. User Experience

Web UI 提供聊天、Agent 制造与进化、多 Agent 协作、模型配置和性能测试入口。前端通过 HTTP API 提交命令，通过运行时事件流接收模型输出、工具状态、子任务进展和产物信息。

## 2. Factory Control Plane

Factory 控制面管理 AgentPackage、会话、调度任务和协作任务。它负责把用户请求绑定到明确的包、会话、模型 Profile、工作区和运行策略，而不直接实现具体 Agent 的推理循环。

## 3. Agent Runtime

Runtime Kernel 根据 AgentPackage 的 Assembly Spec 构建运行图。当前主要支持 `react_agent` 和 `plan_and_execute` 两类执行模式，并在统一状态协议下接入上下文、记忆、知识和交付产物。

- `ReAct`：模型在推理、工具调用和观察结果之间动态循环。
- `Plan & Execute`：规划、执行和最终交付分离，适合长流程任务。
- `Context`：按预算装配对话、任务状态和运行提示。
- `Memory`：维护跨轮次或跨会话的受控记忆。
- `Knowledge`：按需检索本地资料，不把完整知识库无差别注入上下文。
- `Artifacts`：保存报告、图片和其他可交付文件。

## 4. Tool & Resource Gateway

所有工具调用都经过统一网关，网关负责 Schema 校验、路径边界、权限策略、资源注入、结果压缩和审计记录。AgentPackage 可以声明内置工具、MCP、Skill、运行时 Resource 和独立 Workspace，但不能绕过网关直接获取宿主机任意资源。

## 5. Local AI Infrastructure

推理节点为 Chat、Embedding、Image Generation 和 GPU 遥测提供统一控制接口。节点既可以与 Web 运行在同一台 Linux/ROCm 主机，也可以位于独立 AMD Radeon 主机并通过 SSH 隧道访问。

Chat 推理同时保留 Official 与 AMD 两套 llama.cpp 构建。两套实现使用同一模型与 Profile，便于在一致参数下切换、测试并验证自定义 HIP Kernel。Agent 运行容器、SQLite 状态库和会话工作区属于本地基础设施，不依赖闭源 Agent 平台完成核心执行。

## 隔离边界

- AgentPackage 是能力和依赖声明边界。
- Session 是对话状态边界。
- Collaboration Task 是子 Agent 工作和交付边界。
- Workspace 是文件访问边界。
- Tool Gateway 是工具与资源权限边界。
- Model Profile 是模型能力、上下文、KV Cache、并发和推理参数边界。

架构图为项目说明用信息图，精确模块和实现入口以源码为准。
