"""
Agent 群聊系统 - 用户主导的多 Agent 交互模式

核心职责：
- 用户通过 @Agent 显式指定当前轮次的参与者
- 所有成员共享群聊公开上下文和逻辑工作区
- 每个成员独立运行时会话、工具状态和执行历史

注：orchestrator 在阶段2-4实现
"""

from agent_factory.agent_group_system.service import AgentGroupService
from agent_factory.agent_group_system.store import AgentGroupStore

__all__ = ["AgentGroupService", "AgentGroupStore"]
