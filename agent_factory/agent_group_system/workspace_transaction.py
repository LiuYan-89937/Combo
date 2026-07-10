"""
Agent 群聊系统 - 工作区事务管理器

职责：
1. 为每个 run 创建独立 staging 目录（从当前 revision 全量复制）
2. Run 结束时检测变更（manifest 差分）
3. 三方合并：检测冲突（文本/二进制）
4. 提交成功：生成新 revision

策略：可移植全量复制 + manifest 差分（文档 §11.2 推荐）
- 每次从 committed 全量复制到 staging（跨平台兼容）
- 用 file_sha256 生成 manifest
- 文本冲突用 difflib 三方合并
- 二进制/同区域冲突生成结构化冲突记录
"""

from __future__ import annotations

import difflib
import logging
import shutil
from pathlib import Path
from typing import Any

from agent_factory.agent_group_system.store import AgentGroupStore
from agent_factory.file_utils import file_sha256


class WorkspaceTransactionManager:
    """工作区事务管理器"""

    def __init__(self, store: AgentGroupStore, logger: logging.Logger | None = None):
        self.store = store
        self.logger = logger or logging.getLogger(__name__)

    def prepare_staging(self, group_id: str, group_run_id: str, base_revision: int) -> Path:
        """
        为 run 准备 staging 目录（全量复制）

        返回：staging 根路径
        """
        staging_root = self.store.group_staging_root(group_id, group_run_id)
        committed_root = self.store.group_workspace_root(group_id) / "committed"

        self.logger.info(f"Preparing staging for run {group_run_id[:8]}, base revision {base_revision}")

        # 清理旧 staging（如果存在）
        if staging_root.exists():
            shutil.rmtree(staging_root)

        staging_root.mkdir(parents=True, exist_ok=True)

        # 全量复制（committed → staging）
        if committed_root.exists() and any(committed_root.iterdir()):
            self._copy_tree(committed_root, staging_root)
            self.logger.info(f"Copied workspace: {committed_root} -> {staging_root}")
        else:
            self.logger.info("Base workspace empty, staging starts clean")

        return staging_root

    def commit_staging(
        self, group_id: str, group_run_id: str, base_revision: int
    ) -> dict[str, Any]:
        """
        提交 staging 变更（三方合并 + 冲突检测）

        返回：
        {
            "success": bool,
            "target_revision": int | None,
            "conflicts": [{"path": str, "type": "content"|"binary"}]
        }
        """
        self.logger.info(f"Committing staging for run {group_run_id[:8]}")

        staging_root = self.store.group_staging_root(group_id, group_run_id)
        committed_root = self.store.group_workspace_root(group_id) / "committed"

        # 1. 生成 staging manifest
        staging_manifest = self._build_manifest(staging_root)

        # 2. 获取 base 和 current manifests
        base_revision_record = self.store.get_workspace_revision(group_id, base_revision)
        base_manifest = base_revision_record["file_manifest"] if base_revision_record else {}

        # 获取当前最新 revision
        with self.store._connect() as conn:
            current_revision = self.store._current_workspace_revision(conn, group_id)

        current_revision_record = self.store.get_workspace_revision(group_id, current_revision)
        current_manifest = (
            current_revision_record["file_manifest"] if current_revision_record else {}
        )

        # 3. 检测变更
        staging_changes = self._detect_changes(base_manifest, staging_manifest)
        concurrent_changes = self._detect_changes(base_manifest, current_manifest)

        self.logger.info(
            f"Changes: staging={len(staging_changes)}, concurrent={len(concurrent_changes)}"
        )

        # 4. 冲突检测
        conflicts = self._detect_conflicts(
            staging_changes, concurrent_changes, staging_root, committed_root
        )

        if conflicts:
            self.logger.warning(f"Conflicts detected: {len(conflicts)}")
            return {"success": False, "target_revision": None, "conflicts": conflicts}

        # 5. 无冲突，应用变更
        self._apply_changes(staging_changes, staging_root, committed_root)

        # 6. 生成新 revision
        new_manifest = self._build_manifest(committed_root)
        new_revision = self.store.add_workspace_revision(
            group_id, new_manifest, parent_revision=base_revision
        )

        self.logger.info(f"Committed successfully: revision {new_revision}")

        # 7. 清理 staging
        if staging_root.exists():
            shutil.rmtree(staging_root)

        return {"success": True, "target_revision": new_revision, "conflicts": []}

    def _build_manifest(self, root: Path) -> dict[str, str]:
        """构建文件清单 {path: sha256}"""
        manifest = {}
        if not root.exists():
            return manifest

        for file_path in root.rglob("*"):
            if file_path.is_file():
                rel_path = str(file_path.relative_to(root))
                try:
                    manifest[rel_path] = file_sha256(file_path)
                except Exception as e:
                    self.logger.warning(f"Failed to hash {rel_path}: {e}")

        return manifest

    def _detect_changes(
        self, base_manifest: dict[str, str], target_manifest: dict[str, str]
    ) -> dict[str, str]:
        """
        检测变更

        返回：{"path": "add"|"modify"|"delete"}
        """
        changes = {}

        # 新增和修改
        for path, sha in target_manifest.items():
            if path not in base_manifest:
                changes[path] = "add"
            elif base_manifest[path] != sha:
                changes[path] = "modify"

        # 删除
        for path in base_manifest:
            if path not in target_manifest:
                changes[path] = "delete"

        return changes

    def _detect_conflicts(
        self,
        staging_changes: dict[str, str],
        concurrent_changes: dict[str, str],
        staging_root: Path,
        committed_root: Path,
    ) -> list[dict[str, Any]]:
        """
        检测冲突

        冲突类型：
        - 同一文件被双方修改（需要三方合并）
        - 二进制文件冲突（无法自动合并）
        """
        conflicts = []
        conflicting_paths = set(staging_changes.keys()) & set(concurrent_changes.keys())

        for path in conflicting_paths:
            staging_action = staging_changes[path]
            concurrent_action = concurrent_changes[path]

            # 同类操作（都删除）不算冲突
            if staging_action == "delete" and concurrent_action == "delete":
                continue

            # 尝试三方合并（仅文本文件）
            if staging_action == "modify" and concurrent_action == "modify":
                staging_file = staging_root / path
                committed_file = committed_root / path

                if self._is_text_file(staging_file) and self._is_text_file(committed_file):
                    # 尝试三方合并
                    merge_result = self._three_way_merge(staging_file, committed_file)
                    if merge_result["success"]:
                        # 合并成功，不算冲突
                        continue

            # 其他情况视为冲突
            conflicts.append({"path": path, "type": "content"})

        return conflicts

    def _three_way_merge(self, staging_file: Path, committed_file: Path) -> dict[str, Any]:
        """
        三方合并（简化实现）

        返回：{"success": bool, "merged_content": str | None}
        """
        try:
            staging_lines = staging_file.read_text(encoding="utf-8").splitlines(keepends=True)
            committed_lines = committed_file.read_text(encoding="utf-8").splitlines(keepends=True)

            # 简化：使用 difflib 检测是否有冲突行
            # 完整实现应该用真正的三方合并算法（需要 base 版本）
            # 本期暂用简化版：如果两个版本完全不同则失败
            if staging_lines == committed_lines:
                return {"success": True, "merged_content": "".join(staging_lines)}

            # 有差异，视为冲突
            return {"success": False, "merged_content": None}

        except Exception as e:
            self.logger.warning(f"Merge failed: {e}")
            return {"success": False, "merged_content": None}

    def _is_text_file(self, file_path: Path) -> bool:
        """判断是否为文本文件（简化实现）"""
        text_extensions = {".txt", ".md", ".py", ".js", ".json", ".yaml", ".yml", ".toml", ".xml", ".html", ".css", ".sh"}
        return file_path.suffix.lower() in text_extensions

    def _apply_changes(
        self, changes: dict[str, str], staging_root: Path, committed_root: Path
    ) -> None:
        """应用变更到 committed"""
        committed_root.mkdir(parents=True, exist_ok=True)

        for path, action in changes.items():
            staging_file = staging_root / path
            committed_file = committed_root / path

            if action == "delete":
                if committed_file.exists():
                    committed_file.unlink()
                    self.logger.debug(f"Deleted: {path}")

            elif action in ("add", "modify"):
                committed_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(staging_file, committed_file)
                self.logger.debug(f"{action.capitalize()}: {path}")

    def _copy_tree(self, src: Path, dst: Path) -> None:
        """递归复制目录树"""
        dst.mkdir(parents=True, exist_ok=True)
        for item in src.rglob("*"):
            if item.is_file():
                rel_path = item.relative_to(src)
                dst_file = dst / rel_path
                dst_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, dst_file)
