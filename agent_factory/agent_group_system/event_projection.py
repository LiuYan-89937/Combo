"""
Agent 群聊系统 - 事件投影器

职责：
将 runtime FactoryFrontendEvent 投影为群聊消息（中文摘要）

复用模式：镜像 collaboration_system/event_projection.py
"""

from __future__ import annotations

import logging
from typing import Any

from agent_factory.agent_group_system.store import AgentGroupStore
from agent_factory.factory_graph.frontend_bridge.protocol import FactoryFrontendEvent


class GroupEventRecorder:
    """群聊事件记录器（per-run 实例）"""

    def __init__(
        self,
        store: AgentGroupStore,
        group_id: str,
        group_run_id: str,
        speaker_package_id: str,
        max_output_chars: int = 900,
        logger: logging.Logger | None = None,
    ):
        self.store = store
        self.group_id = group_id
        self.group_run_id = group_run_id
        self.speaker_package_id = speaker_package_id
        self.max_output_chars = max_output_chars
        self.logger = logger or logging.getLogger(__name__)
        self._seen_progress_keys: set[str] = set()

    def accept(self, event: FactoryFrontendEvent) -> None:
        """接受一个事件并投影为消息（如果需要）"""
        message_info = self._message_for_event(event)
        if message_info is None:
            return

        message_kind, content = message_info
        event_ref = event.event_id

        # 幂等记录
        self.store.record_agent_message(
            self.group_id, self.group_run_id, message_kind, content, event_ref
        )

    def _message_for_event(self, event: FactoryFrontendEvent) -> tuple[str, str] | None:
        """
        将事件转为 (message_kind, content)

        返回 None 表示不需要记录为消息
        """
        event_type = event.event_type

        # 工具调用
        if event_type == "tool_call_started":
            return self._tool_message(event, "started")

        if event_type == "tool_call_completed":
            return self._tool_message(event, "completed")

        if event_type == "tool_call_failed":
            return self._tool_message(event, "failed")

        # 审批请求
        if event_type == "tool_approval_requested":
            return self._approval_message(event)

        # 节点/阶段进度
        if event_type in ("node_started", "node_completed", "stage_started", "stage_completed"):
            return self._node_message(event)

        # 其他进度事件（去重）
        if event_type in ("run_started", "message_processing", "planning", "reflection"):
            return self._progress_message(event)

        # 默认：不记录
        return None

    def _tool_message(self, event: FactoryFrontendEvent, status: str) -> tuple[str, str]:
        """工具调用消息"""
        payload = event.payload or {}
        tool_name = payload.get("tool_name", "未知工具")

        if status == "started":
            content = f"🔧 正在调用工具：{tool_name}"
            message_kind = "tool_call"
        elif status == "completed":
            result = payload.get("result", "")
            content = f"✅ 工具 {tool_name} 完成"
            if result:
                content += f"\n结果：{self._truncate(result, 200)}"
            message_kind = "tool_result"
        else:  # failed
            error = payload.get("error", "未知错误")
            content = f"❌ 工具 {tool_name} 失败：{self._truncate(error, 200)}"
            message_kind = "tool_result"

        return message_kind, content

    def _approval_message(self, event: FactoryFrontendEvent) -> tuple[str, str]:
        """审批请求消息"""
        payload = event.payload or {}
        tool_name = payload.get("tool_name", "未知工具")
        reason = payload.get("reason", "")

        content = f"⏸️ 等待审批：{tool_name}"
        if reason:
            content += f"\n原因：{self._truncate(reason, 200)}"

        return "approval_request", content

    def _node_message(self, event: FactoryFrontendEvent) -> tuple[str, str] | None:
        """节点/阶段消息（过滤琐碎节点）"""
        node_label = event.node_label or event.node_id or ""
        event_type = event.event_type

        # 过滤内部节点
        if node_label.startswith("__"):
            return None

        if event_type in ("node_started", "stage_started"):
            content = f"▶️ 开始：{node_label}"
        else:
            content = f"✅ 完成：{node_label}"

        return "progress", content

    def _progress_message(self, event: FactoryFrontendEvent) -> tuple[str, str] | None:
        """进度消息（去重）"""
        # 去重键：event_type + node_id
        progress_key = f"{event.event_type}:{event.node_id or 'global'}"
        if progress_key in self._seen_progress_keys:
            return None

        self._seen_progress_keys.add(progress_key)

        event_type = event.event_type
        if event_type == "run_started":
            content = "🚀 开始运行"
        elif event_type == "message_processing":
            content = "💬 处理消息中"
        elif event_type == "planning":
            content = "🤔 规划中"
        elif event_type == "reflection":
            content = "🔍 反思中"
        else:
            content = f"ℹ️ {event_type}"

        return "progress", content

    def _truncate(self, text: str, max_len: int) -> str:
        """截断文本"""
        if len(text) <= max_len:
            return text
        return text[: max_len - 3] + "..."


def create_event_recorder(
    store: AgentGroupStore,
    group_id: str,
    group_run_id: str,
    speaker_package_id: str,
    logger: logging.Logger | None = None,
) -> GroupEventRecorder:
    """工厂函数：创建事件记录器"""
    return GroupEventRecorder(
        store=store,
        group_id=group_id,
        group_run_id=group_run_id,
        speaker_package_id=speaker_package_id,
        logger=logger,
    )
