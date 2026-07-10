"""
Agent 群聊系统 - Orchestrator（Runtime 驱动器）

职责：
1. 驱动单个 member run 端到端执行
2. 调用 runtime.stream() / resume_stream()
3. 消费事件流并投影为消息
4. 管理 staging workspace
5. 工作区提交与冲突处理
6. 更新 run 状态

复用模式：镜像 collaboration_system/orchestrator.py
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Iterator

from typing import TYPE_CHECKING

from agent_factory.agent_group_system.context_compactor import GroupContextCompactor
from agent_factory.agent_group_system.event_projection import create_event_recorder
from agent_factory.agent_group_system.store import AgentGroupStore
from agent_factory.agent_group_system.workspace_transaction import WorkspaceTransactionManager
from agent_factory.factory_graph.frontend_bridge.protocol import FactoryFrontendEvent

if TYPE_CHECKING:
    from agent_factory.factory_graph.frontend_bridge.agent_package_runtime import (
        AgentPackageRuntimeManager,
    )


@dataclass(frozen=True)
class GroupRunResult:
    """Run 执行结果"""

    group_run_id: str
    status: str  # completed | failed | cancelled
    response_message_id: str | None
    error_message: str | None = None


class AgentGroupOrchestrator:
    """Agent 群聊 Orchestrator"""

    def __init__(
        self,
        store: AgentGroupStore,
        runtime: Any,  # AgentPackageRuntimeManager (避免循环导入)
        context_compactor: GroupContextCompactor | None = None,
        workspace_manager: WorkspaceTransactionManager | None = None,
        logger: logging.Logger | None = None,
    ):
        self.store = store
        self.runtime = runtime
        self.context_compactor = context_compactor or GroupContextCompactor(store)
        self.workspace_manager = workspace_manager or WorkspaceTransactionManager(store)
        self.logger = logger or logging.getLogger(__name__)

    def start_run(self, group_run_id: str) -> GroupRunResult:
        """
        执行单个 member run（阻塞直到完成）

        流程：
        1. 准备 staging workspace
        2. 构建共享上下文
        3. 调用 runtime.stream()
        4. 消费事件流并投影
        5. 提交 workspace 变更
        6. 更新 run 状态
        """
        self.logger.info(f"Starting run: {group_run_id}")

        # 1. 加载 run 信息
        run = self.store.get_run(group_run_id)
        if run is None:
            self.logger.error(f"Run not found: {group_run_id}")
            return GroupRunResult(
                group_run_id=group_run_id,
                status="failed",
                response_message_id=None,
                error_message="Run not found",
            )

        group_id = run["group_id"]
        speaker_package_id = run["speaker_package_id"]
        package_session_id = run["package_session_id"]
        base_context_version = run["base_context_version"]
        base_workspace_revision = run["base_workspace_revision"]

        # 2. 准备 staging workspace
        try:
            staging_root = self.workspace_manager.prepare_staging(
                group_id, group_run_id, base_workspace_revision
            )
        except Exception as e:
            self.logger.error(f"Failed to prepare staging: {e}")
            self.store.update_run(group_run_id, {"status": "failed"})
            return GroupRunResult(
                group_run_id=group_run_id,
                status="failed",
                response_message_id=None,
                error_message=f"Staging preparation failed: {e}",
            )

        # 3. 构建共享上下文
        try:
            shared_context = self.context_compactor.build_context_for_run(
                group_id, base_context_version
            )
        except Exception as e:
            self.logger.error(f"Failed to build context: {e}")
            shared_context = ""

        # 4. 构建用户消息（触发此 run 的消息）
        message = self._get_trigger_message(run["message_id"])
        if message is None:
            self.logger.error(f"Trigger message not found: {run['message_id']}")
            self.store.update_run(group_run_id, {"status": "failed"})
            return GroupRunResult(
                group_run_id=group_run_id,
                status="failed",
                response_message_id=None,
                error_message="Trigger message not found",
            )

        user_input = self._build_user_input(message["content"], shared_context)

        # 5. 更新 run 状态为 running
        self.store.update_run(group_run_id, {"status": "running"})

        # 6. 调用 runtime.stream()
        try:
            run_result = self._consume_runtime_stream(
                speaker_package_id,
                package_session_id,
                user_input,
                group_id,
                group_run_id,
                staging_root,
            )
        except Exception as e:
            self.logger.error(f"Runtime stream failed: {e}")
            self.store.update_run(group_run_id, {"status": "failed"})
            return GroupRunResult(
                group_run_id=group_run_id,
                status="failed",
                response_message_id=None,
                error_message=str(e),
            )

        # 7. 如果成功，尝试提交 workspace
        if run_result.status == "completed":
            commit_result = self._try_commit_workspace(group_id, group_run_id, base_workspace_revision)
            if not commit_result["success"]:
                self.logger.warning(
                    f"Workspace commit failed: {len(commit_result['conflicts'])} conflicts"
                )
                # 冲突不视为 run 失败，但不提交 workspace
                # TODO: 生成冲突消息通知用户

        # 8. 更新 run 状态
        self.store.update_run(
            group_run_id,
            {
                "status": run_result.status,
                "response_message_id": run_result.response_message_id,
            },
        )

        return run_result

    def resume_run_approval(self, group_run_id: str, approved: bool, user_response: str | None) -> GroupRunResult:
        """
        恢复因工具审批中断的 run

        TODO: 本期暂不实现，留给下一轮
        """
        self.logger.warning(f"resume_run_approval not implemented yet: {group_run_id}")
        return GroupRunResult(
            group_run_id=group_run_id,
            status="failed",
            response_message_id=None,
            error_message="Approval resume not implemented",
        )

    def _consume_runtime_stream(
        self,
        package_id: str,
        session_id: str,
        user_input: str,
        group_id: str,
        group_run_id: str,
        staging_root,
    ) -> GroupRunResult:
        """
        消费 runtime 事件流

        返回：运行结果
        """
        self.logger.info(f"Streaming runtime for {package_id}:{session_id[:8]}")

        # 创建事件记录器
        event_recorder = create_event_recorder(self.store, group_id, group_run_id, package_id)

        # 调用 runtime.stream()
        # TODO: 需要扩展 runtime 支持 session_kind='group_member'
        stream_run = self.runtime.stream(
            package_id=package_id,
            user_input=user_input,
            session_id=session_id,
            session_kind="normal",  # 本期暂用 normal，下一轮扩展为 group_member
            # TODO: 传递 group_id / group_run_id 到 event payload
        )

        # 消费事件流
        terminal_status = "completed"
        final_message_id = None

        try:
            for stream_mode, chunk in stream_run.events:
                if stream_mode != "frontend_event":
                    continue

                event = (
                    chunk
                    if isinstance(chunk, FactoryFrontendEvent)
                    else FactoryFrontendEvent.model_validate(chunk)
                )

                # 投影事件为消息
                event_recorder.accept(event)

                # 检测终止事件
                if event.event_type == "run_completed":
                    terminal_status = "completed"
                    break
                elif event.event_type == "run_failed":
                    terminal_status = "failed"
                    break
                elif event.event_type == "run_cancelled":
                    terminal_status = "cancelled"
                    break
                elif event.event_type == "tool_approval_requested":
                    terminal_status = "awaiting_approval"
                    # TODO: 保存 interrupt_payload 供 resume 使用
                    break

        except Exception as e:
            self.logger.error(f"Stream consumption failed: {e}")
            terminal_status = "failed"

        # 生成 Agent 响应消息（汇总）
        if terminal_status == "completed":
            response_content = f"✅ {package_id} 已完成任务"
            final_message_id = self._record_response_message(group_id, group_run_id, response_content)

        return GroupRunResult(
            group_run_id=group_run_id,
            status=terminal_status,
            response_message_id=final_message_id,
        )

    def _try_commit_workspace(
        self, group_id: str, group_run_id: str, base_revision: int
    ) -> dict[str, Any]:
        """
        尝试提交 workspace 变更

        返回：{"success": bool, "target_revision": int | None, "conflicts": [...]}
        """
        try:
            result = self.workspace_manager.commit_staging(group_id, group_run_id, base_revision)
            if result["success"]:
                self.logger.info(f"Workspace committed: revision {result['target_revision']}")
            return result
        except Exception as e:
            self.logger.error(f"Workspace commit exception: {e}")
            return {"success": False, "target_revision": None, "conflicts": []}

    def _get_trigger_message(self, message_id: str) -> dict[str, Any] | None:
        """获取触发此 run 的用户消息"""
        # 简化实现：直接查 store（完整实现应该优化查询）
        # 本期暂用遍历方式
        # TODO: store 增加 get_message(message_id) 方法
        return {"message_id": message_id, "content": "用户消息内容"}  # 占位

    def _build_user_input(self, user_message: str, shared_context: str) -> str:
        """
        构建注入到 Agent 的用户输入

        格式：
        <shared_context>
        ...共享上下文...
        </shared_context>

        <user_message>
        ...用户消息...
        </user_message>
        """
        return f"""<shared_context>
{shared_context}
</shared_context>

<user_message>
{user_message}
</user_message>"""

    def _record_response_message(
        self, group_id: str, group_run_id: str, content: str
    ) -> str:
        """
        记录 Agent 的最终响应消息

        返回：message_id
        """
        from uuid import uuid4

        message_id = uuid4().hex
        self.store.record_agent_message(
            group_id, group_run_id, "agent_response", content, event_ref=f"response:{group_run_id}"
        )
        return message_id
