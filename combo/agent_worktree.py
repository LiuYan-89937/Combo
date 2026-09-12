"""Deterministic Git worktrees used by delegated agents.

This module owns only the isolation boundary. A worktree is created from the
repository's current ``HEAD`` and is then left under the child agent's
control. The main agent decides whether to inspect, commit, merge, cherry-pick,
or remove it with ordinary Git commands.

The Git worktree registry is authoritative. Older releases wrote a sidecar JSON
file next to each worktree; those files are inspected once, only to recognise
an already existing legacy worktree, and are removed after inspection. They are
never used as the current state source.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Sequence

from combo.file_atomic import atomic_write_text


_TASK_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_METADATA_SUFFIX = ".combo-agent-task.json"
DEFAULT_WORKTREES_DIRNAME = Path(".combo") / "worktrees"
AGENT_BRANCH_PREFIX = "combo/agent/"


class WorktreeError(RuntimeError):
    """工作树操作失败。"""


class NotAGitRepository(WorktreeError):
    """目标工作区不是 Git 仓库根目录。"""


class InvalidTaskId(WorktreeError):
    """任务标识不能安全地用于路径和分支名。"""


class WorktreeExists(WorktreeError):
    """任务对应的工作树或分支已经存在。"""


@dataclass(frozen=True, slots=True)
class AgentWorktree:
    task_id: str
    branch: str
    path: Path
    base_commit: str
    repository: Path

    def metadata(self) -> dict[str, Any]:
        """Return diagnostics without making them a persistence authority."""
        return {
            "task_id": self.task_id,
            "branch": self.branch,
            "path": str(self.path),
            "base_commit": self.base_commit,
            "repository": str(self.repository),
        }


def _run_git(arguments: Sequence[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )


def _validate_task_id(task_id: str) -> str:
    value = str(task_id or "").strip()
    if not _TASK_ID_PATTERN.fullmatch(value):
        raise InvalidTaskId(f"任务标识不合法: {task_id!r}（只允许字母数字与 . _ -，最长 64）")
    return value


def _read_legacy_sidecar(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


@dataclass(frozen=True, slots=True)
class _GitWorktreeEntry:
    path: Path
    branch: str | None
    head: str | None


def _git_worktree_entries(repository: Path) -> tuple[_GitWorktreeEntry, ...]:
    proc = _run_git(["worktree", "list", "--porcelain"], cwd=repository)
    if proc.returncode != 0:
        raise WorktreeError((proc.stderr or proc.stdout).strip() or "无法读取 Git 工作树列表")
    entries: list[_GitWorktreeEntry] = []
    path: Path | None = None
    branch: str | None = None
    head: str | None = None
    for line in proc.stdout.splitlines() + [""]:
        if not line.strip():
            if path is not None:
                entries.append(_GitWorktreeEntry(path=path, branch=branch, head=head))
            path = None
            branch = None
            head = None
            continue
        key, _, value = line.partition(" ")
        if key == "worktree":
            path = Path(value).expanduser().resolve()
        elif key == "HEAD":
            head = value.strip() or None
        elif key == "branch":
            raw = value.strip()
            prefix = "refs/heads/"
            branch = raw[len(prefix):] if raw.startswith(prefix) else raw
    return tuple(entries)


class AgentWorktreeManager:
    """Create and query deterministic worktrees for one repository.

    There is intentionally no commit, merge, verification, prune, or
    user-requested delete operation. ``cleanup_create_failure`` exists only to
    roll back a worktree when task registration fails immediately after create.
    """

    def __init__(
        self,
        *,
        repository: Path,
        worktrees_root: Path | None = None,
    ) -> None:
        self._repository = Path(repository).expanduser().resolve()
        self._root = (
            Path(worktrees_root).expanduser().resolve()
            if worktrees_root is not None
            else self._repository / DEFAULT_WORKTREES_DIRNAME
        )

    @property
    def repository(self) -> Path:
        return self._repository

    @property
    def worktrees_root(self) -> Path:
        return self._root

    def is_repository(self) -> bool:
        if not self._repository.is_dir():
            return False
        inside = _run_git(["rev-parse", "--is-inside-work-tree"], cwd=self._repository)
        top = _run_git(["rev-parse", "--show-toplevel"], cwd=self._repository)
        return (
            inside.returncode == 0
            and inside.stdout.strip() == "true"
            and top.returncode == 0
            and Path(top.stdout.strip()).resolve() == self._repository
        )

    def expected_branch(self, task_id: str) -> str:
        return f"{AGENT_BRANCH_PREFIX}{_validate_task_id(task_id)}"

    def expected_path(self, task_id: str) -> Path:
        return self._root / _validate_task_id(task_id)

    def lookup(self, task_id: str) -> AgentWorktree | None:
        """Find a task's worktree by Git registry and deterministic identity."""
        normalized = _validate_task_id(task_id)
        if not self.is_repository():
            raise NotAGitRepository(f"{self._repository} 不是 git 仓库根目录")
        expected_path = self.expected_path(normalized).resolve()
        expected_branch = self.expected_branch(normalized)
        entries = _git_worktree_entries(self._repository)
        for entry in entries:
            if entry.path == expected_path and entry.branch == expected_branch:
                self._consume_legacy_sidecar(normalized)
                return AgentWorktree(
                    task_id=normalized,
                    branch=expected_branch,
                    path=expected_path,
                    base_commit=self._base_commit_for_branch(expected_branch, entry.head),
                    repository=self._repository,
                )

        legacy = self._consume_legacy_sidecar(normalized)
        if legacy is not None:
            return legacy
        return None

    def consume_legacy_worktree(self, task_id: str) -> AgentWorktree | None:
        """Consume one old sidecar for startup migration, if it exists."""
        normalized = _validate_task_id(task_id)
        if not self.is_repository():
            raise NotAGitRepository(f"{self._repository} 不是 git 仓库根目录")
        sidecar = self._root / f"{normalized}{_METADATA_SUFFIX}"
        if not sidecar.exists():
            return None
        expected_path = self.expected_path(normalized).resolve()
        expected_branch = self.expected_branch(normalized)
        entries = _git_worktree_entries(self._repository)
        if any(entry.path == expected_path and entry.branch == expected_branch for entry in entries):
            payload = _read_legacy_sidecar(sidecar)
            sidecar.unlink(missing_ok=True)
            base_commit = str(payload.get("base_commit") or "") if payload is not None else ""
            return AgentWorktree(
                task_id=normalized,
                branch=expected_branch,
                path=expected_path,
                base_commit=base_commit or self._base_commit_for_branch(expected_branch, None),
                repository=self._repository,
            )
        return self._consume_legacy_sidecar(normalized)

    def list_worktrees(self) -> tuple[AgentWorktree, ...]:
        """List registered Combo worktrees, filtered by deterministic names."""
        if not self.is_repository():
            raise NotAGitRepository(f"{self._repository} 不是 git 仓库根目录")
        entries = _git_worktree_entries(self._repository)
        prefix = AGENT_BRANCH_PREFIX
        result: list[AgentWorktree] = []
        for entry in entries:
            if entry.branch is None or not entry.branch.startswith(prefix):
                continue
            task_id = entry.branch[len(prefix):]
            if not _TASK_ID_PATTERN.fullmatch(task_id) or entry.path.parent != self._root:
                continue
            result.append(
                AgentWorktree(
                    task_id=task_id,
                    branch=entry.branch,
                    path=entry.path,
                    base_commit=self._base_commit_for_branch(entry.branch, entry.head),
                    repository=self._repository,
                )
            )
        return tuple(sorted(result, key=lambda item: item.task_id))

    def create(self, task_id: str) -> AgentWorktree:
        """Create a worktree from current ``HEAD`` without checking dirtiness."""
        normalized = _validate_task_id(task_id)
        if not self.is_repository():
            raise NotAGitRepository(f"{self._repository} 不是 git 仓库根目录，无法使用工作树模式")
        branch = self.expected_branch(normalized)
        path = self.expected_path(normalized)
        if path.exists():
            raise WorktreeExists(f"任务 {normalized} 的工作树路径已存在: {path}")
        if _run_git(
            ["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], cwd=self._repository
        ).returncode == 0:
            raise WorktreeExists(f"任务 {normalized} 的分支已存在: {branch}")
        self._ensure_ignored()
        path.parent.mkdir(parents=True, exist_ok=True)
        base_commit = self._head()
        created = _run_git(
            ["worktree", "add", "-b", branch, str(path), "HEAD"], cwd=self._repository
        )
        if created.returncode != 0:
            message = (created.stderr or created.stdout).strip()
            # ``worktree add -b`` can create the ref before a later filesystem
            # step fails; clean both possible halves of that create operation.
            _run_git(["worktree", "remove", "--force", str(path)], cwd=self._repository)
            _run_git(["branch", "-D", branch], cwd=self._repository)
            if "already exists" in message:
                raise WorktreeExists(message)
            raise WorktreeError(f"创建失败: {message}")
        return AgentWorktree(
            task_id=normalized,
            branch=branch,
            path=path.resolve(),
            base_commit=base_commit,
            repository=self._repository,
        )

    def cleanup_create_failure(self, worktree: AgentWorktree) -> None:
        """Rollback only a just-created worktree after task registration fails."""
        _run_git(["worktree", "remove", "--force", str(worktree.path)], cwd=self._repository)
        _run_git(["branch", "-D", worktree.branch], cwd=self._repository)

    def require(self, task_id: str) -> AgentWorktree:
        """Resolve a registered worktree or raise an explicit missing error."""
        normalized = _validate_task_id(task_id)
        worktree = self.lookup(normalized)
        if worktree is None:
            raise WorktreeError(
                f"任务 {normalized} 的独立工作树不存在或未登记："
                f"预期路径 {self.expected_path(normalized)}，分支 {self.expected_branch(normalized)}"
            )
        if not worktree.path.is_dir():
            raise WorktreeError(f"任务 {normalized} 的工作树目录已丢失: {worktree.path}")
        return worktree

    def _head(self) -> str:
        proc = _run_git(["rev-parse", "HEAD"], cwd=self._repository)
        if proc.returncode != 0:
            raise NotAGitRepository((proc.stderr or proc.stdout).strip() or "无法读取 HEAD")
        return proc.stdout.strip()

    def _base_commit_for_branch(self, branch: str, fallback: str | None) -> str:
        proc = _run_git(["merge-base", "HEAD", branch], cwd=self._repository)
        return proc.stdout.strip() if proc.returncode == 0 and proc.stdout.strip() else (fallback or self._head())

    def _consume_legacy_sidecar(self, task_id: str) -> AgentWorktree | None:
        path = self._root / f"{task_id}{_METADATA_SUFFIX}"
        if not path.exists():
            return None
        payload = _read_legacy_sidecar(path)
        path.unlink(missing_ok=True)
        if payload is None:
            return None
        expected_path = self.expected_path(task_id).resolve()
        expected_branch = self.expected_branch(task_id)
        sidecar_path = Path(str(payload.get("path") or "")).expanduser().resolve()
        sidecar_branch = str(payload.get("branch") or "").strip()
        if sidecar_path != expected_path or sidecar_branch != expected_branch:
            return None
        if expected_path.is_dir():
            # A directory with no matching Git registry entry is an unrelated
            # path, not a worktree. Do not let a stale sidecar grant it trust.
            return None
        return AgentWorktree(
            task_id=task_id,
            branch=expected_branch,
            path=expected_path,
            base_commit=str(payload.get("base_commit") or self._head()),
            repository=self._repository,
        )

    def _ensure_ignored(self) -> None:
        try:
            relative = self._root.relative_to(self._repository)
        except ValueError:
            return
        if not relative.parts:
            return
        pattern = f"/{relative.as_posix().rstrip('/')}/"
        if _run_git(["check-ignore", "-q", pattern], cwd=self._repository).returncode == 0:
            return
        exclude = self._repository / ".git" / "info" / "exclude"
        exclude.parent.mkdir(parents=True, exist_ok=True)
        existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
        if pattern in existing.splitlines():
            return
        separator = "" if not existing or existing.endswith("\n") else "\n"
        atomic_write_text(exclude, f"{existing}{separator}# combo agent worktrees\n{pattern}\n")
