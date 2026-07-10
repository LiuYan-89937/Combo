"""
Agent 群聊系统 - 共享上下文压缩器

职责：
1. 将群聊消息编译为共享上下文（含成员列表、文件清单、历史摘要）
2. 上下文版本管理（snapshot / delta）
3. Token 计数与压缩触发
4. 调用 task model 的 structured_json 生成结构化上下文摘要

复用基础设施：
- agent_factory.context_system.token_counter (count_text_tokens)
- agent_factory.runtime_kernel.model_operations.service (structured_json)
- agent_factory.models.chat_model (get_task_model)
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from agent_factory.agent_group_system.store import AgentGroupStore
from agent_factory.context_system.token_counter import count_text_tokens
from agent_factory.models.chat_model import get_task_model
from agent_factory.runtime_kernel.model_operations.service import ModelOperationService


# ===== 结构化上下文输出模型（task model 输出） =====


class GroupContextSummary(BaseModel):
    """群聊上下文摘要（structured output）"""

    members: list[str] = Field(description="当前成员 package_id 列表")
    recent_topics: list[str] = Field(
        default_factory=list, description="最近讨论的主要话题（最多5个）"
    )
    key_decisions: list[str] = Field(
        default_factory=list, description="关键决策或结论（最多5个）"
    )
    shared_files: list[str] = Field(default_factory=list, description="共享工作区文件路径列表")
    message_summary: str = Field(description="消息历史摘要（200-500字）")


# ===== 压缩器 =====


class GroupContextCompactor:
    """群聊共享上下文压缩器"""

    def __init__(
        self,
        store: AgentGroupStore,
        model_service: ModelOperationService | None = None,
        logger: logging.Logger | None = None,
        compression_threshold: int = 150000,  # 默认 15 万 token 触发压缩
    ):
        self.store = store
        self.model_service = model_service or ModelOperationService()
        self.logger = logger or logging.getLogger(__name__)
        self.compression_threshold = compression_threshold

    def build_context_for_run(self, group_id: str, base_context_version: int) -> str:
        """
        为 member run 构建上下文正文

        返回：纯文本上下文（用于注入到 Agent prompt）
        """
        self.logger.info(f"Building context for group {group_id}, version {base_context_version}")

        # 获取群聊完整视图
        group = self.store.get_group(group_id)

        # 1. 基础版本（snapshot 或重建的完整内容）
        base_snapshot = self._get_or_rebuild_snapshot(group_id, base_context_version)

        # 2. 增量（base_version 之后的新消息）
        delta_messages = [
            msg
            for msg in group["messages"]
            if self._message_version(msg) > base_context_version
        ]

        # 3. 组装上下文
        context_parts = [base_snapshot]

        if delta_messages:
            context_parts.append("\n\n## 最新消息\n")
            for msg in delta_messages[-20:]:  # 最多 20 条增量
                speaker = msg.get("speaker_package_id") or "用户"
                context_parts.append(f"- [{speaker}]: {msg['content'][:200]}")

        # 4. 工作区文件清单
        current_revision = group["current_workspace_revision"]
        if current_revision > 0:
            revision = self.store.get_workspace_revision(group_id, current_revision)
            if revision and revision["file_manifest"]:
                context_parts.append("\n\n## 共享工作区文件\n")
                for path in sorted(revision["file_manifest"].keys())[:50]:  # 最多 50 个文件
                    context_parts.append(f"- {path}")

        full_context = "\n".join(context_parts)

        # 5. Token 计数与压缩检查
        token_result = count_text_tokens(full_context)
        token_count = token_result.token_count or 0

        self.logger.info(f"Context built: {token_count} tokens")

        # 如果超过阈值，触发压缩（异步，不阻塞当前 run）
        if token_count > self.compression_threshold:
            self.logger.warning(
                f"Context too large ({token_count} > {self.compression_threshold}), "
                "compression should be triggered"
            )
            # TODO: 异步触发压缩任务（本期暂不实现后台压缩）

        return full_context

    def compress_context(self, group_id: str) -> int:
        """
        压缩群聊上下文（生成新 snapshot）

        返回：新版本号
        """
        self.logger.info(f"Compressing context for group {group_id}")

        group = self.store.get_group(group_id)
        current_version = group["current_context_version"]

        # 构建当前完整上下文
        full_context = self.build_context_for_run(group_id, current_version)

        # 调用 task model 生成结构化摘要
        try:
            summary = self.model_service.structured_json(
                output_model=GroupContextSummary,
                state=None,
                prebuilt_messages=[
                    {
                        "role": "user",
                        "content": f"""请分析以下群聊上下文，生成结构化摘要：

{full_context}

要求：
- members: 提取当前参与成员的 package_id
- recent_topics: 最近讨论的主要话题（最多5个）
- key_decisions: 关键决策或结论（最多5个）
- shared_files: 共享文件路径列表
- message_summary: 消息历史摘要（200-500字，中文）
""",
                    }
                ],
                model_role="task",
                max_attempts=2,
            )

            # 将结构化摘要转为纯文本 snapshot
            snapshot_text = self._format_snapshot(summary)

        except Exception as e:
            self.logger.error(f"Compression failed: {e}")
            # 失败时降级为截断
            snapshot_text = full_context[: self.compression_threshold]

        # 计算 token
        token_result = count_text_tokens(snapshot_text)
        token_count = token_result.token_count or 0

        # 保存新 snapshot
        new_version = self.store.add_context_version(
            group_id, kind="snapshot", content=snapshot_text, token_count=token_count
        )

        self.logger.info(f"Compressed to version {new_version}: {token_count} tokens")
        return new_version

    def _get_or_rebuild_snapshot(self, group_id: str, target_version: int) -> str:
        """
        获取指定版本的 snapshot（如果是 delta 则重建）
        """
        if target_version == 0:
            return ""  # 初始版本为空

        version_record = self.store.get_context_version(group_id, target_version)
        if version_record is None:
            self.logger.warning(f"Version {target_version} not found, using empty")
            return ""

        if version_record["kind"] == "snapshot":
            return version_record["content"]

        # 如果是 delta，需要回溯重建（简化实现：直接返回 delta 内容）
        # 完整实现应该递归重建，本期暂用简化版
        return version_record["content"]

    def _format_snapshot(self, summary: GroupContextSummary) -> str:
        """将结构化摘要格式化为纯文本"""
        parts = [
            f"## 群聊成员\n{', '.join(summary.members)}",
            f"\n## 讨论话题\n" + "\n".join(f"- {t}" for t in summary.recent_topics),
            f"\n## 关键决策\n" + "\n".join(f"- {d}" for d in summary.key_decisions),
            f"\n## 消息摘要\n{summary.message_summary}",
        ]

        if summary.shared_files:
            parts.append(
                f"\n## 共享文件\n" + "\n".join(f"- {f}" for f in summary.shared_files[:30])
            )

        return "\n".join(parts)

    def _message_version(self, message: dict[str, Any]) -> int:
        """
        推断消息所属的上下文版本（简化实现）

        完整实现应该在消息表增加 context_version 字段，本期暂用时间戳推断
        """
        # 简化：所有消息都属于当前版本
        return 0
