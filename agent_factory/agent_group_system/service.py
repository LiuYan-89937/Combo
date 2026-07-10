"""
Agent 群聊系统 - 服务层

提供基础的 CRUD 服务和业务逻辑封装。
本轮实现：基础服务层，不含 runtime 驱动（留给下一轮 orchestrator）。
"""

from __future__ import annotations

import logging
from typing import Any

from agent_factory.agent_group_system.store import AgentGroupStore


class AgentGroupService:
    """Agent 群聊服务"""

    def __init__(self, store: AgentGroupStore | None = None, logger: logging.Logger | None = None):
        self.store = store or AgentGroupStore()
        self.logger = logger or logging.getLogger(__name__)

    # ===== 群聊会话管理 =====

    def list_groups(self) -> list[dict[str, Any]]:
        """列出所有群聊"""
        return self.store.list_groups()

    def create_group(self, title: str, member_package_ids: list[str]) -> dict[str, Any]:
        """创建新群聊"""
        self.logger.info(f"Creating group: {title} with {len(member_package_ids)} members")
        group = self.store.create_group(title, member_package_ids)
        self.logger.info(f"Created group: {group['group_id']}")
        return group

    def get_group(self, group_id: str) -> dict[str, Any]:
        """获取群聊详情"""
        return self.store.get_group(group_id)

    def update_group(self, group_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """更新群聊元数据"""
        self.logger.info(f"Updating group {group_id}: {payload}")
        group = self.store.update_group(group_id, payload)
        return group

    def delete_group(self, group_id: str) -> dict[str, Any]:
        """删除群聊（返回需清理的 session_ids）"""
        self.logger.info(f"Deleting group: {group_id}")
        result = self.store.delete_group(group_id)
        self.logger.info(f"Deleted group {group_id}, member_sessions: {len(result['member_session_ids'])}")
        return result

    # ===== 成员管理 =====

    def add_member(self, group_id: str, package_id: str) -> dict[str, Any]:
        """添加成员"""
        self.logger.info(f"Adding member {package_id} to group {group_id}")
        group = self.store.add_member(group_id, package_id)
        return group

    def remove_member(self, group_id: str, package_id: str) -> dict[str, Any]:
        """移除成员"""
        self.logger.info(f"Removing member {package_id} from group {group_id}")
        result = self.store.remove_member(group_id, package_id)
        self.logger.info(f"Removed member, session_id: {result.get('removed_session_id')}")
        return result

    # ===== 消息管理 =====

    def send_user_message(
        self, group_id: str, content: str, client_message_id: str, target_package_ids: list[str]
    ) -> dict[str, Any]:
        """发送用户消息（幂等）"""
        self.logger.info(
            f"User message to group {group_id}: {len(content)} chars, targets: {target_package_ids}"
        )

        # 添加消息并创建 runs
        group = self.store.add_user_message(group_id, content, client_message_id, target_package_ids)

        # TODO（下一轮）：触发 orchestrator 执行 runs
        # 当前返回群聊状态，runs 处于 queued

        return group

    def record_agent_message(
        self,
        group_id: str,
        group_run_id: str,
        message_kind: str,
        content: str,
        event_ref: str | None = None,
    ) -> None:
        """记录 Agent 消息（由 orchestrator 调用）"""
        self.store.record_agent_message(group_id, group_run_id, message_kind, content, event_ref)

    # ===== Run 管理 =====

    def get_run(self, group_run_id: str) -> dict[str, Any] | None:
        """获取 run 记录"""
        return self.store.get_run(group_run_id)

    def update_run(self, group_run_id: str, payload: dict[str, Any]) -> None:
        """更新 run 状态"""
        self.store.update_run(group_run_id, payload)

    def list_queued_runs(self, group_id: str) -> list[dict[str, Any]]:
        """列出待执行的 runs"""
        return self.store.list_queued_runs(group_id)

    def cancel_run(self, group_run_id: str) -> None:
        """取消运行"""
        self.logger.info(f"Cancelling run: {group_run_id}")
        self.store.cancel_run(group_run_id)

    # ===== 上下文与工作区（占位，供下一轮 orchestrator 调用） =====

    def get_context_version(self, group_id: str, version: int) -> dict[str, Any] | None:
        """获取上下文版本"""
        return self.store.get_context_version(group_id, version)

    def add_context_version(
        self, group_id: str, kind: str, content: str, token_count: int, from_version: int | None = None
    ) -> int:
        """添加新上下文版本"""
        return self.store.add_context_version(group_id, kind, content, token_count, from_version)

    def get_workspace_revision(self, group_id: str, revision: int) -> dict[str, Any] | None:
        """获取工作区版本"""
        return self.store.get_workspace_revision(group_id, revision)

    def add_workspace_revision(
        self, group_id: str, file_manifest: dict[str, str], parent_revision: int | None
    ) -> int:
        """添加新工作区版本"""
        return self.store.add_workspace_revision(group_id, file_manifest, parent_revision)

    def record_workspace_change(
        self, group_id: str, group_run_id: str, file_path: str, change_type: str, content_sha256: str | None
    ) -> None:
        """记录工作区变更"""
        self.store.record_workspace_change(group_id, group_run_id, file_path, change_type, content_sha256)

    def get_run_workspace_changes(self, group_run_id: str) -> list[dict[str, Any]]:
        """获取 run 的工作区变更"""
        return self.store.get_run_workspace_changes(group_run_id)

    def clear_run_workspace_changes(self, group_run_id: str) -> None:
        """清除 run 的 staging 变更"""
        self.store.clear_run_workspace_changes(group_run_id)

    def create_workspace_commit(self, group_id: str, group_run_id: str, source_revision: int) -> str:
        """创建工作区提交事务"""
        return self.store.create_workspace_commit(group_id, group_run_id, source_revision)

    def update_workspace_commit(self, commit_id: str, payload: dict[str, Any]) -> None:
        """更新提交事务"""
        self.store.update_workspace_commit(commit_id, payload)

    def get_workspace_commit(self, commit_id: str) -> dict[str, Any] | None:
        """获取提交事务"""
        return self.store.get_workspace_commit(commit_id)

    # ===== 辅助方法 =====

    def group_workspace_root(self, group_id: str):
        """群聊工作区根目录"""
        return self.store.group_workspace_root(group_id)

    def group_staging_root(self, group_id: str, group_run_id: str):
        """群聊 run staging 目录"""
        return self.store.group_staging_root(group_id, group_run_id)
